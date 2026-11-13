"""The Printers tool's part of Settings: General (Printer lists, Startup), Warnings and supplies
(Refresh on its own, which reasons warn, the low supply level, the bar marks, how the Toner column
shows) and Connecting (the SNMP version and its account, the Doc360 MPS account)."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import credstore
from capypanel.core.hosts import locations
from capypanel.core.i18n import N_, _
from capypanel.core.printers import doc360, usm
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import notes
from capypanel.ui.printers_tool import marks as bar_marks
from capypanel.ui.printers_tool import refresh
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.printers_tool.status import Reason
from capypanel.ui.printers_tool.table import swatch
from capypanel.ui.printers_tool.warnings_table import WarningsTable
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import (
    ListsGeneralPage,
    Page,
    Section,
    SettingRow,
    add_rows,
    every_text,
)
from capypanel.ui.tables import fit_rows, grid_table, with_buttons

if TYPE_CHECKING:
    from capypanel.ui.printers_tool.tool import PrintersTool

MAX_COMMUNITY = 255
MAX_V3_USER, MAX_V3_PASSWORD = 32, 255  # RFC 3414's longest user name
MAX_DOC360 = 255  # the Doc360 MPS partner, user name and password
SNMP_VERSION = "snmp_version"  # refresh.V2C or refresh.V3
LOWEST, HIGHEST = 1, 50  # the low supply level's range, in %
TONER_VIEW, TEXT, BARS = "toner_view", "text", "bars"  # the Toner column: "Black 24 %", or a bar
AUTO_REFRESH = "auto_refresh"  # minutes between Refreshes on its own; 0 is off
AUTO_EVERY = (5, 15, 30, 60)
# The Warnings table's ticks, as lists of status.Reason values: In CapyPanel, and the Windows
# notification after a Refresh on its own.
WARN_HERE, WARN_NOTIFY = "warn_here", "warn_notify"
# Until 0.27 the notification was one choice; it's carried over once (PrintersTool.notify_reasons).
NOTIFY, NOTIFY_OFF, NOTIFY_LOW = "notify", "off", "low"


class _SecretWindow(QDialog):
    """The frame the Printers' account windows share: a note on top, the window's own boxes,
    a Show tick for the secret ones, then Save and Cancel. Save keeps what's typed in Windows
    Credential Manager."""

    def __init__(self, parent: QWidget | None, title: str, note: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(16, 16, 16, 16)
        self.column.setSpacing(10)
        self.column.addWidget(notes(note))

    @staticmethod
    def _secret_box(longest: int, *, kept: bool) -> QLineEdit:
        """A password box; one already kept stays empty and keeps it unless typed over."""
        box = QLineEdit()
        box.setEchoMode(QLineEdit.EchoMode.Password)
        box.setMaxLength(longest)
        if kept:
            box.setPlaceholderText(_("Kept: type to change it"))
        return box

    def _add_show_box(self, text: str, secrets: tuple[QLineEdit, ...]) -> None:
        self.show_box = QCheckBox(text)
        self.show_box.toggled.connect(
            lambda on: [
                box.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password)
                for box in secrets
            ]
        )
        self.column.addWidget(self.show_box)

    def _add_buttons(self) -> None:
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
        self.column.addLayout(buttons)


class _LoginWindow[A](_SecretWindow):
    """An account window with a user name: a password already kept isn't shown, and an empty
    user name forgets the kept account. Save waits until the account is complete."""

    def __init__(self, parent: QWidget | None, kept: A | None, title: str, note: str) -> None:
        super().__init__(parent, title, note)
        self._kept = kept
        self.user = QLineEdit()
        self.problem = notes("")

    def account(self) -> A | None:
        raise NotImplementedError

    def forgets(self) -> bool:
        """Save would forget the kept account: its user name was emptied."""
        return self._kept is not None and not self.user.text().strip()

    def _problem(self) -> str:
        raise NotImplementedError

    def _update(self) -> None:
        self.problem.setText(self._problem())
        self.problem.setVisible(bool(self.problem.text()))
        self.save_button.setEnabled(self.account() is not None or self.forgets())

    def _finish(self, show_text: str, secrets: tuple[QLineEdit, ...]) -> None:
        """Under the window's own boxes: the Show tick, what's still missing, Save and Cancel."""
        self._add_show_box(show_text, secrets)
        self.column.addWidget(self.problem)
        self._add_buttons()
        self._update()
        self.resize(460, self.sizeHint().height())


class CommunityDialog(_SecretWindow):
    """The SNMP community string's own small window: Save keeps it in Windows Credential
    Manager. An empty one goes back to "public"."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(
            parent,
            _("SNMP community string"),
            _("The read-only community string your printers answer to. Most use "
              "\"public\". It's kept in Windows Credential Manager."),
        )  # fmt: skip
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setMaxLength(MAX_COMMUNITY)
        self.column.addWidget(self.field)
        self._add_show_box(_("&Show"), (self.field,))
        self._add_buttons()
        self.resize(420, self.sizeHint().height())


class V3AccountDialog(_LoginWindow[usm.Account]):
    """The SNMP v3 account's own small window (Save keeps it in Windows Credential Manager).
    A password already kept isn't shown: its box stays empty and keeps it unless typed over.
    An empty user name forgets the kept account, as an empty community string does."""

    def __init__(self, parent: QWidget | None, kept: usm.Account | None) -> None:
        super().__init__(
            parent,
            kept,
            _("SNMP v3 account"),
            _("The read-only SNMP v3 user your printers know. The passwords are kept in "
              "Windows Credential Manager."),
        )  # fmt: skip
        self.user.setText(kept.user if kept else "")
        self.user.setMaxLength(MAX_V3_USER)
        self.auth = QComboBox()
        self.auth.addItem(_("None"), None)
        for auth in usm.Auth:
            self.auth.addItem(auth.label, auth)
        self.auth_password = self._secret_box(MAX_V3_PASSWORD, kept=bool(kept and kept.auth))
        self.privacy = QComboBox()
        self.privacy.addItem(_("None"), None)
        for privacy in usm.Privacy:
            self.privacy.addItem(privacy.value, privacy)
        self.privacy_password = self._secret_box(MAX_V3_PASSWORD, kept=bool(kept and kept.privacy))
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
        self.column.addLayout(form)
        for box in (self.user, self.auth_password, self.privacy_password):
            box.textChanged.connect(self._update)
        for choice in (self.auth, self.privacy):
            choice.currentIndexChanged.connect(self._update)
        self._finish(_("&Show passwords"), (self.auth_password, self.privacy_password))

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
        super()._update()

    def _problem(self) -> str:
        """What's still missing, in words; "" when the account is complete."""
        if self.forgets():
            return _("Save forgets the saved account.")
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


class Doc360AccountDialog(_LoginWindow[doc360.Account]):
    """The Doc360 MPS login's own small window (Save keeps it in Windows Credential Manager),
    for printers whose page counters come from Doc360. A password already kept isn't shown;
    an empty user name forgets the kept login."""

    def __init__(self, parent: QWidget | None, kept: doc360.Account | None) -> None:
        super().__init__(
            parent,
            kept,
            _("Doc360 MPS account"),
            _("The login you use on the Doc360 MPS portal. CapyPanel signs in once per "
              "Refresh to fetch the latest page counters, then signs out. The password is "
              "kept in Windows Credential Manager."),
        )  # fmt: skip
        self.partner = self._box(kept.partner if kept else "")
        self.user.setText(kept.user if kept else "")
        self.user.setMaxLength(MAX_DOC360)
        self.password = self._secret_box(MAX_DOC360, kept=kept is not None)
        form = QFormLayout()
        form.addRow(_("&Partner"), self.partner)
        form.addRow(_("&User name"), self.user)
        form.addRow(_("Pass&word"), self.password)
        self.column.addLayout(form)
        for box in (self.partner, self.user, self.password):
            box.textChanged.connect(self._update)
        self._finish(_("&Show password"), (self.password,))

    def account(self) -> doc360.Account | None:
        """The login as filled in, or None while something's missing."""
        partner, user = self.partner.text().strip(), self.user.text().strip()
        password = self.password.text() or (self._kept.password if self._kept else "")
        return doc360.Account(partner, user, password) if partner and user and password else None

    def _problem(self) -> str:
        if self.forgets():
            return _("Save forgets the saved account.")
        if not self.partner.text().strip():
            return _("Type the partner, as on Doc360's login page.")
        if not self.user.text().strip():
            return _("Type the user name.")
        if self.account() is None:
            return _("Type the password.")
        return ""

    @staticmethod
    def _box(text: str) -> QLineEdit:
        box = QLineEdit(text)
        box.setMaxLength(MAX_DOC360)
        return box


class BarMarksDialog(QDialog):
    """The supply bars' marks: the low level's, always there, plus any the user adds, each in
    the theme's text colour or one picked here. Save keeps them in Settings."""

    def __init__(self, parent: QWidget | None, chosen: tuple[Mark, ...]) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Bar marks"))
        self._marks = list(chosen)
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(
            notes(
                _("Lines across the supply bars, in Details and the Toner column. The low level's "
                  "follows Low supply level. A colour you pick may be hard to see on some bars; "
                  "Reset to default goes back to one mark in the theme's colour.")
            )
        )  # fmt: skip
        self.table = grid_table([_("Mark"), _("Colour")])
        self.table.setColumnWidth(0, 170)
        self.table.itemSelectionChanged.connect(self._update)
        self.table.itemDoubleClicked.connect(lambda *_a: self.pick_colour())
        self.add_button = QPushButton(_("&Add…"))
        self.colour_button = QPushButton(_("&Colour…"))
        self.theme_button = QPushButton(_("&Theme colour"))
        self.remove_button = QPushButton(_("&Remove"))
        self.reset_button = QPushButton(_("Reset to &default"))
        self.add_button.clicked.connect(self.add)
        self.colour_button.clicked.connect(self.pick_colour)
        self.theme_button.clicked.connect(lambda: self._set_colour(""))
        self.remove_button.clicked.connect(self.remove)
        self.reset_button.clicked.connect(self.reset)
        buttons = [self.add_button, self.colour_button, self.theme_button, self.remove_button,
                   self.reset_button]  # fmt: skip
        column.addWidget(with_buttons(self.table, buttons))
        row = QHBoxLayout()
        row.addStretch(1)
        self.save_button = QPushButton(_("&Save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        row.addWidget(self.save_button)
        row.addWidget(cancel)
        column.addLayout(row)
        self._fill(0)
        self.resize(560, 380)

    def marks(self) -> tuple[Mark, ...]:
        return tuple(self._marks)

    def picked(self) -> int:
        rows = [self.table.indexOfTopLevelItem(i) for i in self.table.selectedItems()]
        return rows[0] if rows else -1

    def add(self) -> None:
        taken = {m.percent for m in self._marks}
        start = next((p for p in (50, 25, 75, *range(5, 100, 5)) if p not in taken), 50)
        percent, ok = QInputDialog.getInt(
            self, _("Add a mark"), _("Where the mark goes, in %:"), start,
            bar_marks.LOWEST, bar_marks.HIGHEST,
        )  # fmt: skip
        if not ok:
            return
        if percent in taken:
            QMessageBox.information(self, _("Bar marks"), _("There's a mark at {n} % already.")
                                    .format(n=percent))  # fmt: skip
            return
        self._marks.append(Mark(percent))
        low, *extra = self._marks
        self._marks = [low, *sorted(extra, key=lambda m: m.percent)]
        self._fill(next(i for i, m in enumerate(self._marks) if m.percent == percent))

    def pick_colour(self) -> None:
        row = self.picked()
        if row < 0:
            return
        start = QColor(self._marks[row].color or self.palette().color(QPalette.ColorRole.Text))
        colour = QColorDialog.getColor(start, self, _("Mark colour"))
        if colour.isValid():
            self._set_colour(colour.name())

    def remove(self) -> None:
        row = self.picked()
        if row > 0:  # the low mark stays
            del self._marks[row]
            self._fill(min(row, len(self._marks) - 1))

    def reset(self) -> None:
        self._marks = [Mark(self._marks[0].percent, low=True)]
        self._fill(0)

    def _set_colour(self, colour: str) -> None:
        row = self.picked()
        if row >= 0:
            mark = self._marks[row]
            self._marks[row] = Mark(mark.percent, colour, mark.low)
            self._fill(row)

    def _fill(self, pick: int) -> None:
        self.table.clear()
        for mark in self._marks:
            where = _("{percent} %").format(percent=mark.percent)
            if mark.low:
                where = _("{level} (low level)").format(level=where)
            item = QTreeWidgetItem([where, mark.color or _("Theme colour")])
            item.setIcon(1, swatch(mark.color or self.palette().color(QPalette.ColorRole.Text)
                                   .name()))  # fmt: skip
            self.table.addTopLevelItem(item)
        fit_rows(self.table)
        if (row := self.table.topLevelItem(pick)) is not None:
            self.table.setCurrentItem(row)
        self._update()

    def _update(self) -> None:
        row = self.picked()
        self.colour_button.setEnabled(row >= 0)
        self.theme_button.setEnabled(row >= 0 and bool(self._marks[row].color))
        self.remove_button.setEnabled(row > 0)
        self.add_button.setEnabled(len(self._marks) <= bar_marks.MOST)


class PrintersPage(ListsGeneralPage):
    """The Printers tool's General page (its lists, startup). It also builds the rows of the
    other two pages and lays them out there: Warnings and supplies (Refresh on its own, the
    Warnings table, the low supply level, the bar marks, the Toner column) and Connecting (the
    SNMP version and account, the Doc360 MPS account). Every choice fires this page's
    `changed`."""

    def __init__(
        self,
        *,
        low: int,
        bars: bool,
        version: str,
        account: str,
        doc360_text: str,
        marks_text: str,
        auto: int,
        warn_here: frozenset[Reason],
        warn_notify: frozenset[Reason],
        **lists: object,
    ) -> None:
        super().__init__(**lists)  # type: ignore[arg-type]
        self.version = QComboBox()
        self.version.addItem("v2c", refresh.V2C)
        self.version.addItem("v3", refresh.V3)
        self.version.setCurrentIndex(self.version.findData(version))
        self.version.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.change_button = QPushButton(_("Change…"))
        self.change_button.setAutoDefault(False)
        self.account_row = SettingRow(_("SNMP &account"), account, self.change_button)
        self.doc360_button = QPushButton(_("Change…"))
        self.doc360_button.setAutoDefault(False)
        self.doc360_row = SettingRow(_("Doc360 &MPS account"), doc360_text, self.doc360_button)
        self.auto_every = QComboBox()
        self.auto_every.addItem(_("Off"), 0)
        for minutes in AUTO_EVERY:
            self.auto_every.addItem(every_text(minutes), minutes)
        self.auto_every.setCurrentIndex(max(self.auto_every.findData(auto), 0))
        self.auto_every.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.warnings = WarningsTable(warn_here, warn_notify)
        self.warnings.changed.connect(self.changed)
        self.low_level = QSpinBox()
        self.low_level.setRange(LOWEST, HIGHEST)
        self.low_level.setValue(low)
        self.low_level.setSuffix(_(" %"))
        self.low_level.valueChanged.connect(self.changed)
        self.marks_button = QPushButton(_("Change…"))
        self.marks_button.setAutoDefault(False)
        self.marks_row = SettingRow(_("Bar &marks"), marks_text, self.marks_button)
        self.toner_view = QComboBox()
        self.toner_view.addItem(_("Text"), TEXT)
        self.toner_view.addItem(_("Bar"), BARS)
        self.toner_view.setCurrentIndex(1 if bars else 0)
        self.toner_view.currentIndexChanged.connect(lambda _i: self.changed.emit())
        self.warnings_page = Page(_("Warnings and supplies"))
        self.connecting_page = Page(_("Connecting"))
        own = Section(_("Refresh"))
        add_rows(
            own.content,
            SettingRow(
                _("Refresh on its &own"),
                _(
                    "Every printer in the open list, 8 at a time, while CapyPanel is open or in "
                    "the tray."
                ),
                self.auto_every,
            ),
        )
        warnings = Section(_("Warnings"))
        warnings.content.addWidget(self.warnings)
        supplies = Section(_("Supplies"))
        add_rows(
            supplies.content,
            SettingRow(
                _("&Low supply level"),
                _("A toner, ink, drum or box at or below this shows as low."),
                self.low_level,
            ),
            self.marks_row,
            SettingRow(
                _("&Toner column"),
                _('The lowest toner as text ("Black 24 %") or as a bar, like in Details.'),
                self.toner_view,
            ),
        )
        snmp = Section(_("SNMP"))
        add_rows(
            snmp.content,
            SettingRow(
                _("SNMP &version"),
                _("v2c: a community string. v3: a user, with a password and encryption."),
                self.version,
            ),
            self.account_row,
        )
        doc360_section = Section(_("Doc360 MPS"))
        add_rows(doc360_section.content, self.doc360_row)
        for page, sections in (
            (self.warnings_page, (own, warnings, supplies)),
            (self.connecting_page, (snmp, doc360_section)),
        ):
            for section in sections:
                page.body.addWidget(section)
            page.body.addStretch(1)

    def show_account(self, text: str) -> None:
        self.account_row.description.setText(text)


def marks_text(marks: tuple[Mark, ...]) -> str:
    """The Bar marks row's line: where the marks are."""
    return _("Lines across the supply bars at {marks}.").format(
        marks=bar_marks.percents_text(marks)
    )


def doc360_text() -> str:
    """The Doc360 MPS account row's line: what's set."""
    account = refresh.doc360_account()
    if account is None:
        return _("Not set. Needed only for printers whose page counters come from Doc360 MPS.")
    return _("Partner {partner}, user {user}. Kept in Windows Credential Manager.").format(
        partner=account.partner, user=account.user
    )


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
    TITLES = (N_("General"), N_("Warnings and supplies"), N_("Connecting"))

    general: PrintersPage

    def __init__(self, tool: "PrintersTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in the lists table, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        texts = tool.list_texts()
        self.general = PrintersPage(
            low=tool.low_level(),
            bars=tool.toner_bars(),
            version=tool.snmp_version(),
            account=account_text(tool.snmp_version()),
            doc360_text=doc360_text(),
            marks_text=marks_text(tool.bar_marks()),
            auto=tool.auto_refresh(),
            warn_here=tool.warn_reasons(),
            warn_notify=tool.notify_reasons(),
            texts=texts,
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            document=doc,
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.general.changed.connect(self._changed)
        self.general.change_button.clicked.connect(self._change_account)
        self.general.doc360_button.clicked.connect(self._change_doc360_account)
        self.general.marks_button.clicked.connect(self._change_marks)
        self.general.view.open_requested.connect(self._open)
        self._building = False
        return [
            ("printers", self.general),
            ("printer_warnings", self.general.warnings_page),
            ("printer_connecting", self.general.connecting_page),
        ]

    def before_rebuild(self) -> None:
        self._chosen = self.general.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.general.view.select(self._chosen)

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_list_prefs(
                self.general.start_choice(),
                self.general.show_first_choice(),
                self.general.added(),
                self.general.hidden(),
            )
            self._tool.set_low_level(self.general.low_level.value())
            self._tool.set_toner_bars(self.general.toner_view.currentData() == BARS)
            self._tool.set_snmp_version(str(self.general.version.currentData()))
            self._tool.set_auto_refresh(int(self.general.auto_every.currentData()))
            self._tool.set_warnings(self.general.warnings.here(), self.general.warnings.notify())
            self.general.show_account(account_text(self._tool.snmp_version()))
            self.general.marks_row.description.setText(marks_text(self._tool.bar_marks()))
            self._tool.prefs_applied()

    def _change_account(self) -> None:
        if self._tool.snmp_version() == refresh.V3:
            self._change_v3_account()
        else:
            self._change_community()
        self.general.show_account(account_text(self._tool.snmp_version()))

    def _change_v3_account(self) -> None:
        dialog = V3AccountDialog(self.general.window(), refresh.v3_account())
        _save_login(self.general, dialog, refresh.V3_ACCOUNT, refresh.save_v3_account)

    def _change_marks(self) -> None:
        dialog = BarMarksDialog(self.general.window(), self._tool.bar_marks())
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._tool.set_bar_marks(dialog.marks())
            self.general.marks_row.description.setText(marks_text(self._tool.bar_marks()))

    def _change_doc360_account(self) -> None:
        change_doc360_account(self.general)
        self.general.doc360_row.description.setText(doc360_text())

    def _change_community(self) -> None:
        dialog = CommunityDialog(self.general.window())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        secret = dialog.field.text().strip()

        def keep() -> None:
            if secret:
                credstore.save(refresh.COMMUNITY, secret)
            else:
                credstore.forget(refresh.COMMUNITY)

        _kept_by_windows(self.general, dialog.windowTitle(), keep)

    def _open(self, path: Path) -> None:
        """A list opened from the lists table: Settings then shows it as the open one."""
        self._tool.open_list(path)
        doc = self._tool.document
        self.general.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)


def change_doc360_account(parent: QWidget) -> bool:
    """The Doc360 MPS account's window, from Settings or from Details; True when Save kept or
    forgot the login."""
    dialog = Doc360AccountDialog(parent.window(), refresh.doc360_account())
    return _save_login(parent, dialog, refresh.DOC360_ACCOUNT, refresh.save_doc360_account)


def _save_login[A](
    parent: QWidget, dialog: _LoginWindow[A], name: str, save: Callable[[A], None]
) -> bool:
    """Runs an account window; Save keeps the account, or forgets it when the user name was
    emptied. True when Windows did."""
    if run_modal(dialog) != QDialog.DialogCode.Accepted:
        return False
    account = dialog.account()

    def keep() -> None:
        if dialog.forgets():
            credstore.forget(name)
        elif account is not None:
            save(account)

    return _kept_by_windows(parent, dialog.windowTitle(), keep)


def _kept_by_windows(parent: QWidget, title: str, keep: Callable[[], None]) -> bool:
    """Runs `keep` against Windows Credential Manager; says so when Windows refused."""
    try:
        keep()
    except (OSError, ValueError) as e:
        QMessageBox.warning(parent, title, _("Windows didn't keep it: {error}").format(error=e))
        return False
    return True


def community_is_set() -> bool:
    try:
        return credstore.load(refresh.COMMUNITY) is not None
    except OSError:
        return False
