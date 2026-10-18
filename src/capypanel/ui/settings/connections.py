"""Settings > Connections: the shared connection profiles (add, edit, duplicate, delete, the
default one) and where each remote tool was found on this PC. Like every other setting, each
change is written at once."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts.document import OpenList
from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect, viewer_settings
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.definitions import ToolDefinition
from capypanel.core.tools.profile_store import UNTRUSTED, make_id
from capypanel.core.tools.profiles import (
    ConnectionProfile,
    ProfileError,
    login_label,
    logins_of,
)
from capypanel.ui.connect import ask_for_program
from capypanel.ui.hosts import confirm
from capypanel.ui.notes import hint, notes
from capypanel.ui.settings.pages import Page, Section, SettingRow
from capypanel.ui.tables import add_action, fit_rows, grid_table, row_menu, with_buttons

MAX_PROFILE_NAME = 64


class ProfileDialog(QDialog):
    """Add, edit or duplicate a profile: name, tool, login, the tool's options, port, and the
    viewer settings file for tools that read one."""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        tools: list[ToolDefinition],
        installed: set[str],
        profile: ConnectionProfile | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._tools = {tool.id: tool for tool in tools}
        self.name = QLineEdit(profile.name if profile else "")
        self.name.setMaxLength(MAX_PROFILE_NAME)
        self.tool = QComboBox()
        for tool in tools:
            text = tool.name if tool.id in installed else _("{tool} (not installed on this PC)")
            self.tool.addItem(text.format(tool=tool.name), tool.id)
        # A new profile starts on a tool this PC has, when there is one.
        wanted = profile.tool if profile else next((t.id for t in tools if t.id in installed), "")
        self.tool.setCurrentIndex(max(self.tool.findData(wanted), 0))
        self.login = QComboBox()
        self._options_box = QWidget()
        self._options = QVBoxLayout(self._options_box)
        self._options.setContentsMargins(0, 0, 0, 0)
        self.option_boxes: dict[str, QCheckBox] = {}
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.port.setValue((profile.port or 0) if profile else 0)
        self._first_tool = profile.tool if profile else ""
        self._has_settings = bool(profile and profile.settings_file)
        self.new_settings: bytes | None = None  # a file chosen here, already cleaned
        self.settings_state = QLabel()
        self.choose_settings = QPushButton(_("C&hoose file…"))
        self.default_settings = QPushButton(_("Use &defaults"))
        self.choose_settings.clicked.connect(self._choose_settings)
        self.default_settings.clicked.connect(self._use_default_settings)
        settings_buttons = QHBoxLayout()
        settings_buttons.addWidget(self.choose_settings)
        settings_buttons.addWidget(self.default_settings)
        settings_buttons.addStretch(1)
        self._settings_box = QWidget()
        settings_column = QVBoxLayout(self._settings_box)
        settings_column.setContentsMargins(0, 0, 0, 0)
        settings_column.addWidget(self.settings_state)
        settings_column.addLayout(settings_buttons)
        self._settings_label = QLabel(_("Viewer settings:"))
        self.settings_hint = hint()

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Tool:"), self.tool)
        form.addRow(_("&Credentials:"), self.login)
        self._options_label = QLabel(_("Options:"))
        form.addRow(self._options_label, self._options_box)
        form.addRow(_("P&ort:"), self.port)
        form.addRow(self._settings_label, self._settings_box)
        form.addRow("", self.settings_hint)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.tool.currentIndexChanged.connect(lambda _i: self._tool_changed(None))
        self._tool_changed(profile)
        self.name.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(440, self.sizeHint().height())

    def _current_tool(self) -> ToolDefinition | None:
        return self._tools.get(self.tool.currentData() or "")

    def _tool_changed(self, profile: ConnectionProfile | None) -> None:
        """Offers only what the chosen tool supports: its logins, its options, its port."""
        tool = self._current_tool()
        if tool is None:
            return
        wanted_login = profile.login if profile else self.login.currentData()
        self.login.clear()
        for login in logins_of(tool):
            text = login_label(login, tool.name)
            self.login.addItem(text[:1].upper() + text[1:], login)  # keeps the tool's capitals
        self.login.setCurrentIndex(max(self.login.findData(wanted_login), 0))
        self.login.setEnabled(self.login.count() > 1)
        ticked = set(profile.options) if profile else set()
        for box in self.option_boxes.values():
            self._options.removeWidget(box)
            box.deleteLater()
        self.option_boxes = {}
        for option_id in tool.options:
            box = QCheckBox(tool.option_name(option_id, i18n.language()))
            box.setChecked(option_id in ticked)
            self._options.addWidget(box)
            self.option_boxes[option_id] = box
        self._options_label.setVisible(bool(tool.options))
        self._options_box.setVisible(bool(tool.options))
        self.port.setSpecialValueText(
            _("Default ({port})").format(port=tool.port) if tool.port else _("Default")
        )
        if tool.id != self._first_tool:  # another viewer's file wouldn't fit this one
            self._first_tool, self._has_settings, self.new_settings = tool.id, False, None
        reads = tool.settings_file is not None
        for widget in (self._settings_label, self._settings_box, self.settings_hint):
            widget.setVisible(reads)
        if tool.settings_file is not None:
            self.settings_hint.setText(
                _(
                    "Optional: a {extension} file saved from {tool}. It's used exactly as saved, "
                    "including its encryption plugin; only the host is emptied, since the address "
                    "comes from the host you open."
                ).format(extension=tool.settings_file.extension, tool=tool.name)
            )
        self._show_settings(None)

    def _show_settings(self, chosen: str | None) -> None:
        if chosen:
            text = _("From “{file}”").format(file=chosen)
        elif self._has_settings:
            text = _("Its own settings file")
        else:
            text = _("The viewer's defaults")
        self.settings_state.setText(text)
        self.default_settings.setEnabled(self._has_settings)
        # With a settings file, the file decides: the options here would change it.
        for box in self.option_boxes.values():
            if self._has_settings:
                box.setChecked(False)
            box.setEnabled(not self._has_settings)
            box.setToolTip(_("Set in the settings file") if self._has_settings else "")

    def _choose_settings(self) -> None:
        tool = self._current_tool()
        if tool is None or tool.settings_file is None:
            return
        extension = tool.settings_file.extension
        name, _filter = QFileDialog.getOpenFileName(
            self,
            _("Choose a {tool} settings file").format(tool=tool.name),
            str(Path.home()),
            _("Viewer settings (*{extension})").format(extension=extension),
        )
        if not name:
            return
        try:
            content = viewer_settings.read(Path(name), tool.settings_file.clear)
        except (OSError, viewer_settings.SettingsFileError) as e:
            message = _("Couldn't use “{file}”: {error}").format(file=Path(name).name, error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return
        self._has_settings, self.new_settings = True, content
        self._show_settings(Path(name).name)

    def _use_default_settings(self) -> None:
        self._has_settings, self.new_settings = False, None
        self._show_settings(None)

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.name.text().strip()) and self._current_tool() is not None)

    def profile(self, profile_id: str) -> ConnectionProfile:
        return ConnectionProfile(
            id=profile_id,
            name=self.name.text().strip(),
            tool=self.tool.currentData(),
            login=self.login.currentData(),
            options=tuple(o for o, box in self.option_boxes.items() if box.isChecked()),
            port=self.port.value() or None,
            settings_file=self._settings_file(profile_id),
        )

    def _settings_file(self, profile_id: str) -> str:
        tool = self._current_tool()
        if not self._has_settings or tool is None or tool.settings_file is None:
            return ""
        return f"{profile_id}{tool.settings_file.extension}"


def skipped_note(problems: list[tuple[Path, str]]) -> QLabel:
    """The files in a folder that aren't used, and why: hidden when there are none. The full
    paths and errors are in its tooltip and the log."""
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
    label = notes(  # a note like the page's others
        ngettext("{n} file skipped: {files}", "{n} files skipped: {files}", len(names)).format(
            n=len(names), files=", ".join(names)
        )
    )
    label.setToolTip("\n".join(f"{path}: {reason}" for path, reason in seen.items()))
    label.setVisible(bool(names))
    return label


class SharedSection(Section):
    """A part of Connections whose changes go to files shared by everyone on this PC, written
    at once; `changed` fires after each."""

    changed = Signal()

    def __init__(self, title: str, catalogs: Catalogs) -> None:
        super().__init__(title)
        self.catalogs = catalogs

    def _write(self, change: Callable[[], object], failed: str) -> bool:
        """Runs a change to the shared files; says what went wrong when it can't."""
        try:
            change()
        except (ProfileError, OSError) as e:
            QMessageBox.warning(self, "CapyPanel", failed.format(error=e))
            return False
        self._written()
        self.changed.emit()
        return True

    def _written(self) -> None:
        """After a change was written."""


class ProfilesSection(SharedSection):
    """The connection profiles everyone on this PC connects with."""

    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connection profiles"), catalogs)
        self.store = catalogs.profiles
        self.document = document
        self.can_edit = self.store.can_edit()

        # The folder is made at start; where this user couldn't, the app's own copies are shown.
        self.builtin_note = notes(
            _("These are the built-in profiles: the folder is created when you change one.")
            if self.can_edit
            else _("These are the built-in profiles: the folder isn't there yet.")
        )
        self._show_folder_state()
        access = (
            _("Shared by everyone on this PC.")
            if self.can_edit
            else _(
                "Shared by everyone on this PC. Read-only: only people Windows lets write this "
                "folder can change them."
            )
        )
        self.list = grid_table([_("Profile"), _("Tool"), _("Signs in with")])
        self.list.setColumnWidth(0, 190)
        self.list.setColumnWidth(1, 150)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda *_a: self.edit())
        self.add_button = QPushButton(_("&Add…"))
        self.edit_button = QPushButton(_("&Edit…"))
        self.delete_button = QPushButton(_("&Delete…"))
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.delete_button.clicked.connect(self.delete)
        profile_buttons = [self.add_button, self.edit_button, self.delete_button]
        row_menu(self.list, self.fill_row_menu)  # Duplicate too
        self.default = QComboBox()
        self.default.setEnabled(self.can_edit)
        self.default.currentIndexChanged.connect(lambda _i: self._default_picked())
        inner = self.content
        inner.addWidget(with_buttons(self.list, profile_buttons))
        self.profiles_skipped = skipped_note(self.store.problems)
        inner.addWidget(notes(access))
        inner.addWidget(self.builtin_note)
        inner.addWidget(self.profiles_skipped)
        inner.addWidget(
            SettingRow(
                _("Hosts with no profile &use"),
                _("The profile a host connects with when it has none of its own."),
                self.default,
            )
        )

        self._fill_profiles(select=None)

    def _written(self) -> None:
        self._show_folder_state()  # the first change makes the folder

    def _save_failed(self) -> str:
        return _("Couldn't save the connection profiles: {error}")

    def _fill_profiles(self, select: str | None) -> None:
        self.list.clear()
        self.default.blockSignals(True)  # filling it isn't picking a default
        self.default.clear()
        for profile in sorted(self.store.all(), key=lambda p: p.name.casefold()):
            entry = self.catalogs.tools.find(profile.tool)
            tool = entry.item.name if entry else profile.tool
            item = QTreeWidgetItem([profile.name, tool, login_label(profile.login, tool)])
            item.setData(0, Qt.ItemDataRole.UserRole, profile.id)
            for column in range(3):
                item.setToolTip(column, item.text(column))  # whole, if the column cuts it
            if profile.login == "none":
                item.setToolTip(
                    2,
                    _(
                        "CapyPanel asks for nothing: {tool} asks for the user and "
                        "password itself when it connects."
                    ).format(tool=tool),
                )
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

    def fill_row_menu(self, menu: QMenu) -> None:
        picked = self.can_edit and self._selected() is not None
        add_action(menu, _("&Edit…"), self.edit, picked)
        add_action(menu, _("D&uplicate…"), self.duplicate, picked)
        menu.addSeparator()
        add_action(menu, _("&Delete…"), self.delete, picked)

    def _dialog(self, title: str, profile: ConnectionProfile | None) -> ProfileDialog:
        tools = [e.item for e in self.catalogs.tools.all()]
        installed = {t.id for t in tools if detect.find_executable(t) is not None}
        return ProfileDialog(self, title, tools, installed, profile)

    def _taken(self) -> dict[str, ConnectionProfile]:
        return {p.id: p for p in self.store.all()}

    def add(self) -> None:
        dialog = self._dialog(_("New connection profile"), None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = dialog.profile(make_id(dialog.name.text().strip(), self._taken()))
            self._save(new, dialog.new_settings)

    def edit(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        dialog = self._dialog(_("Edit connection profile"), profile)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited = replace(dialog.profile(profile.id), extra=profile.extra)
            self._save(edited, dialog.new_settings)

    def duplicate(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        copy = replace(profile, name=_("{profile} (copy)").format(profile=profile.name))
        dialog = self._dialog(_("Duplicate connection profile"), copy)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = dialog.profile(make_id(dialog.name.text().strip(), self._taken()))
            content = dialog.new_settings
            if content is None and new.settings_file:
                content = self._settings_content(profile)  # the copy gets its own file
                if content is None:
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
    """Where each remote tool is on this PC, set once for everyone."""

    def __init__(self, catalogs: Catalogs) -> None:
        super().__init__(_("Remote tools"), catalogs)
        self.can_edit_tools = catalogs.tools.can_edit()
        tools_layout = self.content
        # The same table as the profiles: the buttons act on the tool picked.
        self.tools = grid_table([_("Tool"), _("Status"), _("Where")])
        self.tools.setColumnWidth(0, 190)
        self.tools.setColumnWidth(1, 150)
        self.tools.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # a path keeps both ends
        self.tools.itemSelectionChanged.connect(self._update_tool_buttons)
        self.tools.itemDoubleClicked.connect(lambda *_a: self._double_clicked())
        self.locate_button = QPushButton(_("Change path…"))
        self.download_button = QPushButton(_("Download"))
        for button, action in ((self.locate_button, "locate"), (self.download_button, "download")):
            button.clicked.connect(lambda _c=False, a=action: self._picked_tool_action(a))
        tool_buttons = [self.locate_button, self.download_button]
        row_menu(self.tools, self.fill_row_menu)  # Use the automatic path too
        tools_layout.addWidget(with_buttons(self.tools, tool_buttons))
        tools_layout.addWidget(
            notes(
                _("Where each tool is installed, set once for everyone on this PC.")
                if self.can_edit_tools
                else _(
                    "Where each tool is installed, set once for everyone on this PC. Read-only: "
                    "only people Windows lets write the tools folder can change it."
                )
            )
        )
        self.tools_skipped = skipped_note([(p.path, p.reason) for p in catalogs.tools.problems])
        tools_layout.addWidget(self.tools_skipped)

        self._fill_tools()

    # ---- tools: a path chosen here is written at once ----

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
        """What the buttons can do for a tool, in this state: locate, automatic, download."""
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
        """Only the actions that make sense for the tool picked, in its state."""
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
        if "automatic" in actions:  # only once a path was chosen
            add_action(
                menu,
                _("Use the &automatic path"),
                lambda: self._picked_tool_action("automatic"),
                self.can_edit_tools,
            )
        if "download" in actions:
            add_action(menu, _("Download"), lambda: self._picked_tool_action("download"))

    def _double_clicked(self) -> None:
        """Like a double-click on a profile edits it: the tool's path is changed."""
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
    """Settings > Connections: the profiles, and where the tools they open are."""

    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connections"))
        self.profiles = ProfilesSection(catalogs, document)
        self.tools = ToolsSection(catalogs)
        for section in (self.profiles, self.tools):
            self.body.addWidget(section)
            section.changed.connect(self.changed.emit)
        self.body.addStretch(1)
