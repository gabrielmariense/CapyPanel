"""The Printers tool's part of Settings: Startup, Refresh (the SNMP version and its account,
Refresh on its own, the low supply level and how the Toner column shows) and Printer lists."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import credstore
from capypanel.core.hosts import locations
from capypanel.core.i18n import N_, _
from capypanel.core.printers import usm
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import notes
from capypanel.ui.printers_tool import refresh
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import (
    ListsGeneralPage,
    ListsPage,
    Page,
    Section,
    SettingRow,
    add_rows,
    every_text,
)

if TYPE_CHECKING:
    from capypanel.ui.printers_tool.tool import PrintersTool

MAX_COMMUNITY = 255
MAX_V3_USER, MAX_V3_PASSWORD = 32, 255  # RFC 3414's longest user name
SNMP_VERSION = "snmp_version"  # refresh.V2C or refresh.V3
LOWEST, HIGHEST = 1, 50  # the low supply level's range, in %
TONER_VIEW, TEXT, BARS = "toner_view", "text", "bars"  # the Toner column: "Black 24 %", or a bar
AUTO_REFRESH = "auto_refresh"  # minutes between Refreshes on its own; 0 is off
AUTO_EVERY = (5, 15, 30, 60)
# Windows notifications after a Refresh on its own, for what's new: none, a printer stopping or
# going offline (the default), or that and a supply getting low.
NOTIFY, NOTIFY_OFF, NOTIFY_STOPS, NOTIFY_LOW = "notify", "off", "stops", "low"


class CommunityDialog(QDialog):
    """The SNMP community string's own small window: Save keeps it in Windows Credential
    Manager. An empty one goes back to "public"."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("SNMP community string"))
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(
            notes(
                _("The read-only community string your printers answer to. Most use "
                  "\"public\". It's kept in Windows Credential Manager.")
            )
        )  # fmt: skip
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setMaxLength(MAX_COMMUNITY)
        column.addWidget(self.field)
        self.show_box = QCheckBox(_("&Show"))
        self.show_box.toggled.connect(
            lambda on: self.field.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        column.addWidget(self.show_box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton(_("&Save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        column.addLayout(buttons)
        self.resize(420, self.sizeHint().height())


class V3AccountDialog(QDialog):
    """The SNMP v3 account's own small window (Save keeps it in Windows Credential Manager).
    A password already kept isn't shown: its box stays empty and keeps it unless typed over."""

    def __init__(self, parent: QWidget | None, kept: usm.Account | None) -> None:
        super().__init__(parent)
        self._kept = kept
        self.setWindowTitle(_("SNMP v3 account"))
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(
            notes(
                _("The read-only SNMP v3 user your printers know. The passwords are kept in "
                  "Windows Credential Manager.")
            )
        )  # fmt: skip
        self.user = QLineEdit(kept.user if kept else "")
        self.user.setMaxLength(MAX_V3_USER)
        self.auth = QComboBox()
        self.auth.addItem(_("None"), None)
        for auth in usm.Auth:
            self.auth.addItem(auth.label, auth)
        self.auth_password = self._password_box(bool(kept and kept.auth))
        self.privacy = QComboBox()
        self.privacy.addItem(_("None"), None)
        for privacy in usm.Privacy:
            self.privacy.addItem(privacy.value, privacy)
        self.privacy_password = self._password_box(bool(kept and kept.privacy))
        if kept:
            self.auth.setCurrentIndex(self.auth.findData(kept.auth))
            self.privacy.setCurrentIndex(self.privacy.findData(kept.privacy))
        else:  # what most printers set up for v3 use
            self.auth.setCurrentIndex(self.auth.findData(usm.Auth.SHA))
            self.privacy.setCurrentIndex(self.privacy.findData(usm.Privacy.AES128))
        form = QFormLayout()
        form.addRow(_("&User name"), self.user)
        form.addRow(_("&Authentication"), self.auth)
        form.addRow(_("Authentication &password"), self.auth_password)
        form.addRow(_("&Encryption"), self.privacy)
        form.addRow(_("Encryption pass&word"), self.privacy_password)
        column.addLayout(form)
        self.show_box = QCheckBox(_("&Show passwords"))
        self.show_box.toggled.connect(self._show_passwords)
        column.addWidget(self.show_box)
        self.problem = notes("")
        column.addWidget(self.problem)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton(_("&Save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        column.addLayout(buttons)
        for box in (self.user, self.auth_password, self.privacy_password):
            box.textChanged.connect(self._update)
        for choice in (self.auth, self.privacy):
            choice.currentIndexChanged.connect(self._update)
        self._update()
        self.resize(460, self.sizeHint().height())

    def account(self) -> usm.Account | None:
        """The account as filled in, or None while something's missing."""
        auth: usm.Auth | None = self.auth.currentData()
        privacy: usm.Privacy | None = self.privacy.currentData() if auth else None
        kept = self._kept
        auth_password = self.auth_password.text() or (kept.auth_password if kept else "")
        privacy_password = self.privacy_password.text() or (kept.privacy_password if kept else "")
        try:
            return usm.Account(
                self.user.text().strip(),
                auth,
                auth_password if auth else "",
                privacy,
                privacy_password if privacy else "",
            )
        except ValueError:
            return None

    def _update(self) -> None:
        signing = self.auth.currentData() is not None
        self.auth_password.setEnabled(signing)
        self.privacy.setEnabled(signing)  # encryption needs authentication
        self.privacy_password.setEnabled(signing and self.privacy.currentData() is not None)
        self.problem.setText(self._problem())
        self.problem.setVisible(bool(self.problem.text()))
        self.save_button.setEnabled(self.account() is not None)

    def _problem(self) -> str:
        """What's still missing, in words; "" when the account is complete."""
        if not self.user.text().strip():
            return _("Type the user name.")
        account = self.account()
        if account is not None:
            return ""
        if self.auth_password.isEnabled() and not self._long_enough(self.auth_password, "auth"):
            return _("The authentication password needs at least 8 characters.")
        return _("The encryption password needs at least 8 characters.")

    def _long_enough(self, box: QLineEdit, which: str) -> bool:
        typed = box.text()
        if not typed and self._kept:
            typed = self._kept.auth_password if which == "auth" else self._kept.privacy_password
        return len(typed.encode()) >= usm.MIN_PASSWORD

    def _password_box(self, kept: bool) -> QLineEdit:
        box = QLineEdit()
        box.setEchoMode(QLineEdit.EchoMode.Password)
        box.setMaxLength(MAX_V3_PASSWORD)
        if kept:
            box.setPlaceholderText(_("Kept: type to change it"))
        return box

    def _show_passwords(self, on: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
        self.auth_password.setEchoMode(mode)
        self.privacy_password.setEchoMode(mode)


class PrintersPage(ListsGeneralPage):
    """Startup, then Refresh: the SNMP version, its account behind Change…, Refresh on its own,
    the low supply level, and the Toner column as text or a bar."""

    def __init__(
        self,
        *,
        low: int,
        bars: bool,
        version: str,
        account: str,
        auto: int,
        notify: str,
        **lists: object,
    ) -> None:
        super().__init__(**lists)  # type: ignore[arg-type]
        section = Section(_("Refresh"))
        self.version = QComboBox()
        self.version.addItem("v2c", refresh.V2C)
        self.version.addItem("v3", refresh.V3)
        self.version.setCurrentIndex(self.version.findData(version))
        self.version.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.change_button = QPushButton(_("Change…"))
        self.change_button.setAutoDefault(False)
        self.account_row = SettingRow(_("SNMP &account"), account, self.change_button)
        self.auto_every = QComboBox()
        self.auto_every.addItem(_("Off"), 0)
        for minutes in AUTO_EVERY:
            self.auto_every.addItem(every_text(minutes), minutes)
        self.auto_every.setCurrentIndex(max(self.auto_every.findData(auto), 0))
        self.auto_every.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.notify = QComboBox()
        self.notify.addItem(_("Off"), NOTIFY_OFF)
        self.notify.addItem(_("Stopped or offline"), NOTIFY_STOPS)
        self.notify.addItem(_("Also low supplies"), NOTIFY_LOW)
        self.notify.setCurrentIndex(max(self.notify.findData(notify), 0))
        self.notify.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.low_level = QSpinBox()
        self.low_level.setRange(LOWEST, HIGHEST)
        self.low_level.setValue(low)
        self.low_level.setSuffix(_(" %"))
        self.low_level.valueChanged.connect(self.changed)
        self.toner_view = QComboBox()
        self.toner_view.addItem(_("Text"), TEXT)
        self.toner_view.addItem(_("Bar"), BARS)
        self.toner_view.setCurrentIndex(1 if bars else 0)
        self.toner_view.currentIndexChanged.connect(lambda _i: self.changed.emit())
        add_rows(
            section.content,
            SettingRow(
                _("SNMP &version"),
                _("v2c: a community string. v3: a user, with a password and encryption."),
                self.version,
            ),
            self.account_row,
            SettingRow(
                _("Refresh on its &own"),
                _(
                    "Every printer in the open list, 8 at a time, while CapyPanel is open or in "
                    "the tray."
                ),
                self.auto_every,
            ),
            SettingRow(
                _("Windows &notification"),
                _(
                    "After a Refresh on its own, for printers that stopped or went offline "
                    "(and with low supplies, if picked) since the one before."
                ),
                self.notify,
            ),
            SettingRow(
                _("&Low supply level"),
                _("A toner, ink, drum or box at or below this shows as low."),
                self.low_level,
            ),
            SettingRow(
                _("&Toner column"),
                _('The lowest toner as text ("Black 24 %") or as a bar, like in Details.'),
                self.toner_view,
            ),
        )
        self.add_section(section)

    def show_account(self, text: str) -> None:
        self.account_row.description.setText(text)


def account_text(version: str) -> str:
    """The SNMP account row's line: what's set for the version picked."""
    if version == refresh.V3:
        account = refresh.v3_account()
        if account is None:
            return _("v3: not set. Use Change… to add the user.")
        parts = [account.user]
        parts += [account.auth.label] if account.auth else []
        parts += [account.privacy.value] if account.privacy else []
        return _("v3: user {parts}. Kept in Windows Credential Manager.").format(
            parts=", ".join(parts)
        )
    if community_is_set():
        return _("v2c: community string set. Kept in Windows Credential Manager.")
    return _('v2c: not set, printers are asked with "public".')


class PrintersSettings(SettingsGroup):
    LABEL = N_("Printers")
    TITLES = (N_("General"), N_("Printer lists"))

    general: PrintersPage
    lists: ListsPage

    def __init__(self, tool: "PrintersTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in Printer lists, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        texts = tool.list_texts()
        self.general = PrintersPage(
            low=tool.low_level(),
            bars=tool.toner_bars(),
            version=tool.snmp_version(),
            account=account_text(tool.snmp_version()),
            auto=tool.auto_refresh(),
            notify=tool.notify_choice(),
            texts=texts,
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.lists = ListsPage(
            texts=texts,
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            document=doc,
            added=locations.added_lists(prefs),
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
        )
        for page in (self.general, self.lists):
            page.changed.connect(self._changed)
        self.general.change_button.clicked.connect(self._change_account)
        self.lists.view.open_requested.connect(self._open)
        self._building = False
        return [("printers", self.general), ("printer_lists", self.lists)]

    def before_rebuild(self) -> None:
        self._chosen = self.lists.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.lists.view.select(self._chosen)

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_list_prefs(
                self.general.start_choice(),
                self.general.show_first_choice(),
                self.lists.added(),
                self.lists.hidden(),
            )
            self._tool.set_low_level(self.general.low_level.value())
            self._tool.set_toner_bars(self.general.toner_view.currentData() == BARS)
            self._tool.set_snmp_version(str(self.general.version.currentData()))
            self._tool.set_auto_refresh(int(self.general.auto_every.currentData()))
            self._tool.set_notify_choice(str(self.general.notify.currentData()))
            self.general.show_account(account_text(self._tool.snmp_version()))
            self._tool.prefs_applied()

    def _change_account(self) -> None:
        if self._tool.snmp_version() == refresh.V3:
            self._change_v3_account()
        else:
            self._change_community()
        self.general.show_account(account_text(self._tool.snmp_version()))

    def _change_v3_account(self) -> None:
        dialog = V3AccountDialog(self.general.window(), refresh.v3_account())
        if (
            run_modal(dialog) != QDialog.DialogCode.Accepted
            or (account := dialog.account()) is None
        ):
            return
        try:
            refresh.save_v3_account(account)
        except (OSError, ValueError) as e:
            QMessageBox.warning(
                self.general,
                _("SNMP v3 account"),
                _("Windows didn't keep it: {error}").format(error=e),
            )

    def _change_community(self) -> None:
        dialog = CommunityDialog(self.general.window())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        secret = dialog.field.text().strip()
        try:
            if secret:
                credstore.save(refresh.COMMUNITY, secret)
            else:
                credstore.forget(refresh.COMMUNITY)
        except (OSError, ValueError) as e:
            QMessageBox.warning(
                self.general,
                _("SNMP community string"),
                _("Windows didn't keep it: {error}").format(error=e),
            )
            return

    def _open(self, path: Path) -> None:
        """A list opened from Printer lists: Settings then shows it as the open one."""
        self._tool.open_list(path)
        doc = self._tool.document
        self.lists.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)


def community_is_set() -> bool:
    try:
        return credstore.load(refresh.COMMUNITY) is not None
    except OSError:
        return False
