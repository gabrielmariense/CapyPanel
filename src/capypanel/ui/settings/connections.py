from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts.document import OpenList
from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.definitions import ToolDefinition
from capypanel.core.tools.profile_store import UNTRUSTED, make_id
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError, logins_of
from capypanel.ui import dialogs, help_links
from capypanel.ui.connect import ask_for_program
from capypanel.ui.dialogs import ok_cancel
from capypanel.ui.hosts import confirm
from capypanel.ui.notes import notes
from capypanel.ui.settings.pages import Page, Section, SettingRow, add_rows
from capypanel.ui.tables import add_action, fit_rows, grid_table, row_menu, with_buttons

MAX_PROFILE_NAME = 64


def sends_label(login: str) -> str:
    return _("User and password") if login == "account" else _("Password only")


def typed_in_label(login: str, tool: str) -> str:
    if login == "none":
        return tool
    if login == "account":
        return _("CapyPanel (user and password)")
    return _("CapyPanel (password only)")


class _WidestRadio(QRadioButton):
    """As wide as its widest text, so the window's width holds when Tool changes the text."""

    def __init__(self, texts: list[str]) -> None:
        super().__init__()
        self._texts = texts

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        metrics = self.fontMetrics()
        widest = max((metrics.horizontalAdvance(text) for text in self._texts), default=0)
        extra = max(widest - metrics.horizontalAdvance(self.text()), 0)
        return QSize(hint.width() + extra, hint.height())


class _RowLabel(QLabel):
    """As tall as its field: Qt caps a form label at 7/4 of its text line, from the row's top."""

    def __init__(self, text: str, field: QWidget) -> None:
        super().__init__(text)
        self._field = field
        self.setBuddy(field)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(hint.width(), max(hint.height(), self._field.sizeHint().height()))


class ProfileDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        tools: list[ToolDefinition],
        installed: set[str],
        profile: ConnectionProfile | None = None,
        *,
        new: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._tools = {tool.id: tool for tool in tools}
        is_new = profile is None if new is None else new
        saved_tool = self._tools.get(profile.tool) if profile else None
        self._on_command_line = bool(
            profile is not None
            and not is_new
            and profile.login != "none"
            and saved_tool is not None
            and saved_tool.credentials == "arguments"
        )
        self._warned = False
        self.name = QLineEdit(profile.name if profile else "")
        self.name.setMaxLength(MAX_PROFILE_NAME)
        self.tool = QComboBox()
        for tool in tools:
            text = tool.name if tool.id in installed else _("{tool} (not installed on this PC)")
            self.tool.addItem(text.format(tool=tool.name), tool.id)
        wanted = profile.tool if profile else next((t.id for t in tools if t.id in installed), "")
        self.tool.setCurrentIndex(max(self.tool.findData(wanted), 0))
        self.viewer_asks = _WidestRadio([_("Typed in {tool}").format(tool=t.name) for t in tools])
        self.capypanel_asks = QRadioButton(_("Typed in CapyPanel"))
        self.capypanel_asks.clicked.connect(self._capypanel_picked)
        self.viewer_asks.toggled.connect(lambda _on: self._show_login())
        self.asks_label = QLabel(_("&Password:"))
        self.asks_label.setBuddy(self.viewer_asks)
        self.login = QComboBox()
        self.login.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        labels = [sends_label(login) for login in ("account", "password")]
        self.login.setMinimumContentsLength(max(map(len, labels)))
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.port.setValue((profile.port or 0) if profile else 0)
        self._first_tool = profile.tool if profile else ""
        self._has_settings = bool(profile and profile.settings_file)
        self._had_settings = self._has_settings
        self._settings_name = profile.settings_file if profile and not is_new else ""
        self.settings_state = QLabel()
        self.default_settings = QPushButton(_("Use &defaults"))
        self.default_settings.clicked.connect(self._use_default_settings)
        self._settings_buttons = QWidget()
        buttons_row = QHBoxLayout(self._settings_buttons)
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.addWidget(self.default_settings)
        buttons_row.addStretch(1)
        self._option_places: list[QCheckBox] = []
        self._more_options = QWidget()
        more_column = QVBoxLayout(self._more_options)
        more_column.setContentsMargins(0, 0, 0, 0)
        for place in range(max((len(t.options) for t in tools), default=0)):
            box = QCheckBox(" ")
            policy = box.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
            box.setSizePolicy(policy)
            if place:
                more_column.addWidget(box)
            self._option_places.append(box)
        self.option_boxes: dict[str, QCheckBox] = {}

        self._form = form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Tool:"), self.tool)
        form.addRow(_("P&ort:"), self.port)
        form.addRow(self.asks_label, self.viewer_asks)
        form.addRow("", self.capypanel_asks)
        form.addRow("", self.login)
        form.addRow(_("Settings:"), self.settings_state)
        form.addRow("", self._settings_buttons)
        if self._option_places:
            first = self._option_places[0]
            form.addRow(_RowLabel(_("Options:"), first), first)
        if len(self._option_places) > 1:
            form.addRow("", self._more_options)
        # A form's label column is as wide as its visible labels: hiding a row would move fields.
        widths = [
            label.sizeHint().width()
            for row in range(form.rowCount())
            if (item := form.itemAt(row, QFormLayout.ItemRole.LabelRole))
            and (label := item.widget()) is not None
        ]
        if widths and (name_label := form.labelForField(self.name)) is not None:
            name_label.setMinimumWidth(max(widths))
        self.buttons = ok_cancel(self, _("Save") if profile else _("Add"))
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.help_button = help_links.HelpButton("connecting-set-up-connection-profiles")
        layout.addLayout(help_links.row(self.help_button, self.buttons))

        self.tool.currentIndexChanged.connect(lambda _i: self._tool_changed(None))
        self._tool_changed(profile)
        self.name.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(440, self.sizeHint().height())

    def _current_tool(self) -> ToolDefinition | None:
        return self._tools.get(self.tool.currentData() or "")

    def _tool_changed(self, profile: ConnectionProfile | None) -> None:
        tool = self._current_tool()
        if tool is None:
            return
        if profile is not None:
            by_capypanel, wanted = profile.login != "none", profile.login
        else:
            by_capypanel, wanted = self.capypanel_asks.isChecked(), self.login.currentData()
        sends = [login for login in logins_of(tool) if login != "none"]
        self.login.clear()
        for login in sends:
            self.login.addItem(sends_label(login), login)
        self.login.setCurrentIndex(max(self.login.findData(wanted), 0))
        self.viewer_asks.setText(_("Typed in {tool}").format(tool=tool.name))
        (self.capypanel_asks if by_capypanel and sends else self.viewer_asks).setChecked(True)
        for field in (self.viewer_asks, self.capypanel_asks, self.login):
            self._form.setRowVisible(field, bool(sends))
        self._show_login()
        ticked = set(profile.options) if profile else set()
        options = list(tool.options)
        self.option_boxes = {}
        for index, box in enumerate(self._option_places):
            if index < len(options):
                box.setText(tool.option_name(options[index], i18n.language()))
                box.setChecked(options[index] in ticked)
                self.option_boxes[options[index]] = box
            if index:
                box.setVisible(index < len(options))
        if self._option_places:
            self._form.setRowVisible(self._option_places[0], bool(options))
        if len(self._option_places) > 1:
            self._form.setRowVisible(self._more_options, len(options) > 1)
        self.port.setSpecialValueText(
            _("Default ({port})").format(port=tool.port) if tool.port else _("Default")
        )
        if tool.id != self._first_tool:
            self._first_tool, self._has_settings = tool.id, False
        for row in (self.settings_state, self._settings_buttons):
            self._form.setRowVisible(row, self._had_settings and tool.settings_file is not None)
        self._show_settings()
        if profile is None:
            self._fit_height()
            if self.capypanel_asks.isChecked():
                self._capypanel_picked(True)

    def _fit_height(self) -> None:
        if (layout := self.layout()) is not None:
            layout.activate()
        self.resize(self.width(), self.sizeHint().height())

    def _show_login(self) -> None:
        tool = self._current_tool()
        name = tool.name if tool is not None else ""
        by_capypanel = self.capypanel_asks.isChecked()
        self.asks_label.setBuddy(self.capypanel_asks if by_capypanel else self.viewer_asks)
        self.login.setEnabled(by_capypanel and self.login.count() > 1)
        if not by_capypanel:
            self.login.setToolTip(_("{tool} asks for these when it connects.").format(tool=name))
        elif self.login.count() > 1:
            self.login.setToolTip("")
        else:
            self.login.setToolTip(_("{tool} only takes a password.").format(tool=name))

    def _capypanel_picked(self, checked: bool) -> None:
        tool = self._current_tool()
        if not checked or tool is None or tool.credentials != "arguments":
            return
        if self._on_command_line or self._warned:
            return
        self._warned = True
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("Security tools may log this password"),
            _("CapyPanel passes it to {tool} on the command line, where security tools and this "
              "PC's admins can see it.").format(tool=tool.name),
            parent=self,
        )  # fmt: skip
        box.setTextFormat(Qt.TextFormat.PlainText)
        use = box.addButton(_("Use CapyPanel anyway"), QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton(
            _("Let {tool} ask").format(tool=tool.name), QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        help_links.add_link(box, "connecting-set-up-connection-profiles")
        dialogs.run_modal(box)
        if box.clickedButton() is not use:
            self.viewer_asks.setChecked(True)

    def _show_settings(self) -> None:
        self.settings_state.setText(
            _("Its own settings file") if self._has_settings else _("The viewer's defaults")
        )
        self.default_settings.setEnabled(self._has_settings)
        self.default_settings.setToolTip(
            "" if self._has_settings else _("This profile already uses the viewer's defaults.")
        )
        for box in self.option_boxes.values():
            if self._has_settings:
                box.setChecked(False)
            box.setEnabled(not self._has_settings)
            box.setToolTip(_("Set in the settings file") if self._has_settings else "")

    def _use_default_settings(self) -> None:
        self._has_settings = False
        self._show_settings()

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.name.text().strip()) and self._current_tool() is not None)

    def profile(self, profile_id: str) -> ConnectionProfile:
        return ConnectionProfile(
            id=profile_id,
            name=self.name.text().strip(),
            tool=self.tool.currentData(),
            login="none" if self.viewer_asks.isChecked() else self.login.currentData(),
            options=tuple(o for o, box in self.option_boxes.items() if box.isChecked()),
            port=self.port.value() or None,
            settings_file=self._settings_file(profile_id),
        )

    def _settings_file(self, profile_id: str) -> str:
        tool = self._current_tool()
        if not self._has_settings or tool is None or tool.settings_file is None:
            return ""
        return self._settings_name or f"{profile_id}{tool.settings_file.extension}"


def skipped_note(problems: list[tuple[Path, str]]) -> QLabel:
    seen: dict[Path, str] = {}
    for path, reason in problems:
        seen.setdefault(path, reason)
    names = [
        "{name} ({why})".format(
            name=path.name,
            why=_("made by another user") if reason == UNTRUSTED else _("can't be read"),
        )
        for path, reason in seen.items()
    ]
    label = notes(
        ngettext("{n} file skipped: {files}", "{n} files skipped: {files}", len(names)).format(
            n=len(names), files=", ".join(names)
        )
    )
    label.setToolTip("\n".join(f"{path}: {reason}" for path, reason in seen.items()))
    label.setVisible(bool(names))
    return label


class SharedSection(Section):
    changed = Signal()

    def __init__(self, title: str, catalogs: Catalogs) -> None:
        super().__init__(title)
        self.catalogs = catalogs

    def _write(self, change: Callable[[], object], failed: str) -> bool:
        try:
            change()
        except (ProfileError, OSError) as e:
            message = failed.format(error=e)
            help_links.warning(self, "CapyPanel", message, place="connect-settings-not-saved")
            return False
        self._written()
        self.changed.emit()
        return True

    def _written(self) -> None:
        pass


class ProfilesSection(SharedSection):
    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connection profiles"), catalogs)
        self.store = catalogs.profiles
        self.document = document
        self.can_edit = self.store.can_edit()

        self.builtin_note = notes(
            _("These are the built-in profiles: the folder is created when you change one.")
            if self.can_edit
            else _("These are the built-in profiles: the folder isn't there yet.")
        )
        self._show_folder_state()
        self.for_everyone(self.can_edit)
        self.list = grid_table([_("Profile"), _("Tool"), _("Password typed in")])
        self.list.setColumnWidth(0, 190)
        self.list.setColumnWidth(1, 150)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda *_a: self.edit())
        self.add_button = QPushButton(_("&Add…"))
        self.edit_button = QPushButton(_("&Edit…"))
        self.delete_button = QPushButton(_("&Delete…"))
        self.restore_button = QPushButton(_("&Restore built-in…"))
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.delete_button.clicked.connect(self.delete)
        self.restore_button.clicked.connect(self.restore_builtin)
        profile_buttons = [
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.restore_button,
        ]
        row_menu(self.list, self.fill_row_menu)
        self.default = QComboBox()
        self.default.setEnabled(self.can_edit)
        self.default.currentIndexChanged.connect(lambda _i: self._default_picked())
        inner = self.content
        inner.addWidget(with_buttons(self.list, profile_buttons))
        self.profiles_skipped = skipped_note(self.store.problems)
        inner.addWidget(self.builtin_note)
        inner.addWidget(self.profiles_skipped)
        self.manage_button = QPushButton(_("&Manage…"))
        self.manage_button.setToolTip(
            _("Logins you ticked Remember for: Windows encrypts them for your account, so anyone "
              "using your Windows session can connect with them.")
        )  # fmt: skip
        self.saved_row = SettingRow(_("Sa&ved credentials"), "", self.manage_button)
        add_rows(
            inner,
            SettingRow(
                _("Hosts with no profile &use"),
                _("The profile a host connects with when it has none of its own."),
                self.default,
            ),
        )
        self.passwords_section = Section(_("Passwords"))
        add_rows(self.passwords_section.content, self.saved_row)

        self._fill_profiles(select=None)

    def _written(self) -> None:
        self._show_folder_state()

    def _save_failed(self) -> str:
        return _("Couldn't save the connection profiles: {error}")

    def _fill_profiles(self, select: str | None) -> None:
        self.list.clear()
        self.default.blockSignals(True)
        self.default.clear()
        for profile in sorted(self.store.all(), key=lambda p: p.name.casefold()):
            entry = self.catalogs.tools.find(profile.tool)
            tool = entry.item.name if entry else profile.tool
            item = QTreeWidgetItem([profile.name, tool, typed_in_label(profile.login, tool)])
            item.setData(0, Qt.ItemDataRole.UserRole, profile.id)
            for column in range(3):
                item.setToolTip(column, item.text(column))
            self.list.addTopLevelItem(item)
            if profile.id == select:
                item.setSelected(True)
                self.list.setCurrentItem(item)
            self.default.addItem(profile.name, profile.id)
        self.default.setCurrentIndex(max(self.default.findData(self.store.default_id()), 0))
        self.default.blockSignals(False)
        fit_rows(self.list)
        self._update_buttons()
        self._show_folder_state()

    def _selected(self) -> ConnectionProfile | None:
        items = self.list.selectedItems()
        return self.store.find(items[0].data(0, Qt.ItemDataRole.UserRole)) if items else None

    def _update_buttons(self) -> None:
        picked = self.can_edit and self._selected() is not None
        self.add_button.setEnabled(self.can_edit)
        for button in (self.edit_button, self.delete_button):
            button.setEnabled(picked)
        self.restore_button.setEnabled(self.can_edit and bool(self.store.missing_starters()))

    def fill_row_menu(self, menu: QMenu) -> None:
        picked = self.can_edit and self._selected() is not None
        add_action(menu, _("&Edit…"), self.edit, picked)
        add_action(menu, _("D&uplicate…"), self.duplicate, picked)
        menu.addSeparator()
        add_action(menu, _("&Delete…"), self.delete, picked)

    def _dialog(
        self, title: str, profile: ConnectionProfile | None, *, new: bool = False
    ) -> ProfileDialog:
        tools = [e.item for e in self.catalogs.tools.all()]
        installed = {t.id for t in tools if detect.find_executable(t) is not None}
        return ProfileDialog(self, title, tools, installed, profile, new=new)

    def _taken(self) -> dict[str, ConnectionProfile]:
        return {p.id: p for p in self.store.all()}

    def add(self) -> None:
        dialog = self._dialog(_("New connection profile"), None, new=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = dialog.profile(make_id(dialog.name.text().strip(), self._taken()))
            self._save(new)

    def edit(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        dialog = self._dialog(_("Edit connection profile"), profile)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited = replace(dialog.profile(profile.id), extra=profile.extra)
            self._save(edited)

    def duplicate(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        copy = replace(profile, name=_("{profile} (copy)").format(profile=profile.name))
        dialog = self._dialog(_("Duplicate connection profile"), copy, new=True)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = dialog.profile(make_id(dialog.name.text().strip(), self._taken()))
            content = self._settings_content(profile) if new.settings_file else None
            if new.settings_file and content is None:
                new = replace(new, settings_file="")
            self._save(new, content)

    def delete(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        text = _("Delete the connection profile “{profile}”? Everyone on this PC loses "
                 "it.").format(profile=profile.name)  # fmt: skip
        hosts, groups = self._uses(profile.id)
        if hosts or groups:
            text += "\n\n" + _(
                "In the open list it's set on {hosts} and {groups}. They'll use their group's "
                "profile, or the default, instead."
            ).format(
                hosts=ngettext("{n} host", "{n} hosts", hosts).format(n=hosts),
                groups=ngettext("{n} group", "{n} groups", groups).format(n=groups),
            )
        if not confirm(self, _("Delete connection profile"), text, _("Delete")):
            return
        self._write(lambda: self.store.delete(profile.id), self._save_failed())
        self._fill_profiles(select=None)

    def restore_builtin(self) -> None:
        missing = self.store.missing_starters()
        if not missing or not self.can_edit:
            return
        names = ", ".join(p.name for p in missing)
        text = ngettext(
            "Bring back {n} built-in profile: {names}?",
            "Bring back {n} built-in profiles: {names}?",
            len(missing),
        ).format(n=len(missing), names=names)
        text += "\n\n" + _("Profiles you changed or made yourself stay as they are.")
        if not confirm(self, _("Restore built-in profiles"), text, _("&Restore")):
            return
        self._write(self.store.restore_starters, self._save_failed())
        self._fill_profiles(select=None)

    def _uses(self, profile_id: str) -> tuple[int, int]:
        if self.document is None:
            return 0, 0
        hosts = self.document.hosts
        return (
            sum(h.profile == profile_id for h in hosts.hosts),
            sum(g.profile == profile_id for g in hosts.groups),
        )

    def _settings_content(self, profile: ConnectionProfile) -> bytes | None:
        path = self.store.settings_path(profile)
        try:
            return path.read_bytes() if path is not None else None
        except OSError:
            return None

    def _save(self, profile: ConnectionProfile, settings: bytes | None = None) -> None:
        self._write(lambda: self.store.save(profile, settings), self._save_failed())
        self._fill_profiles(select=profile.id)

    def _default_picked(self) -> None:
        chosen = self.default_choice()
        if chosen and chosen != self.store.default_id():
            self._write(lambda: self.store.set_default(chosen), self._save_failed())

    def default_choice(self) -> str:
        return self.default.currentData() or ""

    def _show_folder_state(self) -> None:
        self.builtin_note.setVisible(not self.store.folder.is_dir())


class ToolsSection(SharedSection):
    def __init__(self, catalogs: Catalogs) -> None:
        super().__init__(_("Remote tools"), catalogs)
        self.can_edit_tools = catalogs.tools.can_edit()
        tools_layout = self.content
        self.tools = grid_table([_("Tool"), _("Status"), _("Where")])
        self.tools.setColumnWidth(0, 190)
        self.tools.setColumnWidth(1, 150)
        self.tools.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tools.itemSelectionChanged.connect(self._update_tool_buttons)
        self.tools.itemDoubleClicked.connect(lambda *_a: self._double_clicked())
        self.locate_button = QPushButton(_("Change path…"))
        self.download_button = QPushButton(_("Download"))
        for button, action in ((self.locate_button, "locate"), (self.download_button, "download")):
            button.clicked.connect(lambda _c=False, a=action: self._picked_tool_action(a))
        tool_buttons = [self.locate_button, self.download_button]
        row_menu(self.tools, self.fill_row_menu)
        tools_layout.addWidget(with_buttons(self.tools, tool_buttons))
        self.for_everyone(self.can_edit_tools)
        self.tools_skipped = skipped_note([(p.path, p.reason) for p in catalogs.tools.problems])
        tools_layout.addWidget(self.tools_skipped)
        tools_layout.addLayout(self._reads_row())

        self._fill_tools()

    def _reads_row(self) -> QHBoxLayout:
        self.reads_label = QLabel(_("Read PC data with:"))
        self.reads = QComboBox()
        for way, text in (
            ("auto", _("Automatic (recommended)")),
            ("direct", _("WMI directly")),
            ("powershell", _("WMI through PowerShell")),
        ):
            self.reads.addItem(text, way)
        self.reads.setToolTip(
            _("Both read over WMI; only what starts on this PC changes. Automatic reads directly, "
              "and through PowerShell only when that can't be used here.")
        )  # fmt: skip
        self.reads.setCurrentIndex(max(0, self.reads.findData(self.catalogs.tools.reads())))
        self.reads.setEnabled(self.can_edit_tools)
        self.reads.activated.connect(self._reads_picked)
        self.reads_note = QLabel()
        self.reads_note.setObjectName("hint")
        row = QHBoxLayout()
        row.addWidget(self.reads_label)
        row.addWidget(self.reads)
        row.addWidget(self.reads_note)
        row.addStretch(1)
        self._show_reads_note()
        return row

    def _reads_picked(self) -> None:
        from capypanel.core.remote import inventory

        way = str(self.reads.currentData())
        if self._write(
            lambda: self.catalogs.tools.set_reads(way),
            _("Couldn't save how PCs are read: {error}"),
        ):
            inventory.transport = way
        else:
            self.reads.setCurrentIndex(max(0, self.reads.findData(self.catalogs.tools.reads())))
        self._show_reads_note()

    def _show_reads_note(self) -> None:
        from capypanel.core.remote import wmi

        if self.reads.currentData() != "auto":
            self.reads_note.setText("")
            return
        way = _("WMI directly") if wmi.available() else _("WMI through PowerShell")
        self.reads_note.setText(_("in use: {way}").format(way=way))

    def _fill_tools(self) -> None:
        picked = self._picked_tool()
        self.tools.clear()
        for entry in self.catalogs.tools.all():
            tool = entry.item
            found = detect.find_executable(tool)
            if found is None:
                status, where = _("✗ Not found"), "—"
                tip = _("Install it, or locate its .exe.")
            else:
                status = _("✓ Your choice") if tool.executable else _("✓ Found")
                where = tip = str(found)
            item = QTreeWidgetItem([tool.name, status, where])
            item.setData(0, Qt.ItemDataRole.UserRole, tool.id)
            for column in (1, 2):
                item.setToolTip(column, tip)
            self.tools.addTopLevelItem(item)
            if picked is not None and picked.id == tool.id:
                self.tools.setCurrentItem(item)
        first = self.tools.topLevelItem(0)
        if self.tools.currentItem() is None and first is not None:
            self.tools.setCurrentItem(first)
        fit_rows(self.tools)
        self._update_tool_buttons()

    def _picked_tool(self) -> ToolDefinition | None:
        item = self.tools.currentItem() if hasattr(self, "tools") else None
        entry = self.catalogs.tools.find(item.data(0, Qt.ItemDataRole.UserRole)) if item else None
        return entry.item if entry else None

    def tool_actions(self, tool_id: str) -> list[str]:
        entry = self.catalogs.tools.find(tool_id)
        if entry is None:
            return []
        tool = entry.item
        found = detect.find_executable(tool)
        actions = ["locate"]
        if tool.executable:
            actions.append("automatic")
        if found is None and tool.website:
            actions.append("download")
        return actions

    def select_tool(self, tool_id: str) -> None:
        for index in range(self.tools.topLevelItemCount()):
            item = self.tools.topLevelItem(index)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == tool_id:
                self.tools.setCurrentItem(item)

    def _update_tool_buttons(self) -> None:
        tool = self._picked_tool()
        actions = self.tool_actions(tool.id) if tool else []
        self.locate_button.setEnabled("locate" in actions and self.can_edit_tools)
        self.download_button.setEnabled("download" in actions)

    def fill_row_menu(self, menu: QMenu) -> None:
        tool = self._picked_tool()
        actions = self.tool_actions(tool.id) if tool else []
        add_action(
            menu,
            _("Change path…"),
            lambda: self._picked_tool_action("locate"),
            "locate" in actions and self.can_edit_tools,
        )
        if "automatic" in actions:
            add_action(
                menu,
                _("Use the &automatic path"),
                lambda: self._picked_tool_action("automatic"),
                self.can_edit_tools,
            )
        if "download" in actions:
            add_action(menu, _("Download"), lambda: self._picked_tool_action("download"))

    def _double_clicked(self) -> None:
        if self.locate_button.isEnabled():
            self._picked_tool_action("locate")

    def _picked_tool_action(self, action: str) -> None:
        tool = self._picked_tool()
        if tool is not None:
            self._tool_action(tool, action)

    def _tool_action(self, tool: ToolDefinition, action: str) -> None:
        if action == "locate":
            self.locate(tool)
        elif action == "automatic":
            self.automatic(tool)
        else:
            QDesktopServices.openUrl(QUrl(tool.website))  # the browser downloads; we never do

    def locate(self, tool: ToolDefinition) -> None:
        name = ask_for_program(self, tool)
        if name:
            self._set_path(tool, name)

    def automatic(self, tool: ToolDefinition) -> None:
        self._set_path(tool, "")

    def _set_path(self, tool: ToolDefinition, executable: str) -> None:
        self._write(
            lambda: self.catalogs.tools.set_paths({tool.id: executable}),
            _("Couldn't save where the tools are: {error}"),
        )
        self._fill_tools()


class ConnectionsPage(Page):
    HELP_PLACE = "settings-hosts-connecting"

    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connecting"))
        self.profiles = ProfilesSection(catalogs, document)
        self.tools = ToolsSection(catalogs)
        for section in (self.profiles, self.tools):
            self.body.addWidget(section)
        for shared in (self.profiles, self.tools):
            shared.changed.connect(self.changed.emit)
        self.body.addStretch(1)
