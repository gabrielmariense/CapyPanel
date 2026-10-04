"""Settings > Connections: the shared connection profiles (add, edit, duplicate, delete, the
default one) and where each remote tool was found on this PC. Like every other setting, nothing
is written until Save; Cancel drops every change made here."""

from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts.document import OpenList
from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect, viewer_settings
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.definitions import ToolDefinition
from capypanel.core.tools.profile_store import make_id
from capypanel.core.tools.profiles import ConnectionProfile, login_label, logins_of
from capypanel.ui.hosts import confirm
from capypanel.ui.settings.pages import Page, PathLabel, hint

MAX_PROFILE_NAME = 64


@dataclass(frozen=True)
class ConnectionChanges:
    """What Save writes: profiles added or changed, profiles deleted, the default, tool paths."""

    saved: tuple[ConnectionProfile, ...] = ()
    deleted: tuple[str, ...] = ()
    default: str = ""
    tool_paths: dict[str, str] = field(default_factory=dict)  # tool id -> .exe; "" = automatic
    settings: dict[str, bytes] = field(default_factory=dict)  # profile id -> new settings file


def apply(catalogs: Catalogs, changes: ConnectionChanges) -> None:
    """Writes what was changed on the page, once Save is clicked. Raises ProfileError, OSError."""
    store = catalogs.profiles
    for profile_id in changes.deleted:
        store.delete(profile_id)
    for profile in changes.saved:
        store.save(profile, changes.settings.get(profile.id))
    if changes.default and changes.default != store.default_id():
        store.set_default(changes.default)
    if changes.tool_paths:
        catalogs.tools.set_paths(changes.tool_paths)


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
        form.addRow(_("&Login:"), self.login)
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
            text = login_label(login).capitalize()
            if not tool.wants_password:  # e.g. Remote Desktop: it asks for the password itself
                text = _("Asked by {tool}").format(tool=tool.name)
            self.login.addItem(text, login)
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


class ConnectionsPage(Page):
    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connections"))
        self.catalogs = catalogs
        self.store = catalogs.profiles
        self.document = document
        self.can_edit = self.store.can_edit()
        self.can_edit_tools = catalogs.tools.can_edit()
        self._profiles = {p.id: p for p in self.store.all()}
        self._changed: set[str] = set()
        self._deleted: set[str] = set()
        self._tool_paths: dict[str, str] = {}
        self._settings: dict[str, bytes] = {}  # settings files chosen here, written on Save

        profiles_box = QGroupBox(_("Connection profiles"))
        folder = PathLabel(self.store.folder)
        access = (
            _("Shared by everyone on this PC. You can change them.")
            if self.can_edit
            else _(
                "Shared by everyone on this PC. Read-only: only people Windows lets write this "
                "folder can change them."
            )
        )
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._update_buttons)
        self.list.itemDoubleClicked.connect(lambda _item: self.edit())
        self.add_button = QPushButton(_("&Add…"))
        self.edit_button = QPushButton(_("&Edit…"))
        self.duplicate_button = QPushButton(_("D&uplicate…"))
        self.delete_button = QPushButton(_("&Delete…"))
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.duplicate_button.clicked.connect(self.duplicate)
        self.delete_button.clicked.connect(self.delete)
        buttons = QVBoxLayout()
        for button in (self.add_button, self.edit_button, self.duplicate_button,
                       self.delete_button):  # fmt: skip
            buttons.addWidget(button)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.list, 1)
        row.addLayout(buttons)
        self.default = QComboBox()
        self.default.setEnabled(self.can_edit)
        default_row = QFormLayout()
        default_row.addRow(_("Hosts with no profile &use:"), self.default)
        inner = QVBoxLayout(profiles_box)
        inner.addWidget(folder)
        inner.addWidget(hint(access))
        inner.addLayout(row)
        inner.addLayout(default_row)

        tools_box = QGroupBox(_("Remote tools"))
        tools_layout = QVBoxLayout(tools_box)
        tools_layout.addWidget(
            hint(
                _("Where each tool is installed, set once for everyone on this PC.")
                if self.can_edit_tools
                else _(
                    "Where each tool is installed, set once for everyone on this PC. Read-only: "
                    "only people Windows lets write the tools folder can change it."
                )
            )
        )
        self._tools_grid = QGridLayout()
        self._tools_grid.setColumnStretch(2, 1)
        tools_layout.addLayout(self._tools_grid)

        self.body.addWidget(profiles_box, 1)
        self.body.addWidget(tools_box)
        self._fill_profiles(select=None)
        self.default.setCurrentIndex(max(self.default.findData(self.store.default_id()), 0))
        self._fill_tools()

    # ---- profiles (a working copy until Save) ----

    def _fill_profiles(self, select: str | None) -> None:
        current_default = self.default.currentData() or self.store.default_id()
        self.list.clear()
        self.default.clear()
        for profile in sorted(self._profiles.values(), key=lambda p: p.name.casefold()):
            item = QListWidgetItem(profile.name)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.list.addItem(item)
            if profile.id == select:
                item.setSelected(True)
                self.list.setCurrentItem(item)
            self.default.addItem(profile.name, profile.id)
        self.default.setCurrentIndex(max(self.default.findData(current_default), 0))
        self._update_buttons()

    def _selected(self) -> ConnectionProfile | None:
        items = self.list.selectedItems()
        return self._profiles.get(items[0].data(Qt.ItemDataRole.UserRole)) if items else None

    def _update_buttons(self) -> None:
        picked = self.can_edit and self._selected() is not None
        self.add_button.setEnabled(self.can_edit)
        for button in (self.edit_button, self.duplicate_button, self.delete_button):
            button.setEnabled(picked)

    def _dialog(self, title: str, profile: ConnectionProfile | None) -> ProfileDialog:
        tools = [self._tool_view(e.item) for e in self.catalogs.tools.all()]
        installed = {t.id for t in tools if detect.find_executable(t) is not None}
        return ProfileDialog(self, title, tools, installed, profile)

    def add(self) -> None:
        dialog = self._dialog(_("New connection profile"), None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_id = make_id(dialog.name.text().strip(), self._profiles)
            self._keep(dialog.profile(new_id), dialog.new_settings)

    def edit(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        dialog = self._dialog(_("Edit connection profile"), profile)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited = replace(dialog.profile(profile.id), extra=profile.extra)
            self._keep(edited, dialog.new_settings)

    def duplicate(self) -> None:
        profile = self._selected()
        if profile is None or not self.can_edit:
            return
        copy = replace(profile, name=_("{profile} (copy)").format(profile=profile.name))
        dialog = self._dialog(_("Duplicate connection profile"), copy)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new = dialog.profile(make_id(dialog.name.text().strip(), self._profiles))
            content = dialog.new_settings
            if content is None and new.settings_file:
                content = self._settings_content(profile)  # the copy gets its own file
                if content is None:
                    new = replace(new, settings_file="")
            self._keep(new, content)

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
        del self._profiles[profile.id]
        self._settings.pop(profile.id, None)
        self._changed.discard(profile.id)
        if self.store.find(profile.id) is not None:
            self._deleted.add(profile.id)
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
        if profile.id in self._settings:
            return self._settings[profile.id]
        path = self.store.settings_path(profile)
        try:
            return path.read_bytes() if path is not None else None
        except OSError:
            return None

    def _keep(self, profile: ConnectionProfile, settings: bytes | None = None) -> None:
        if settings is not None:
            self._settings[profile.id] = settings
        elif not profile.settings_file:
            self._settings.pop(profile.id, None)
        self._profiles[profile.id] = profile
        self._changed.add(profile.id)
        self._deleted.discard(profile.id)
        self._fill_profiles(select=profile.id)

    def default_choice(self) -> str:
        return self.default.currentData() or ""

    def has_changes(self) -> bool:
        edited = self._changed or self._deleted or self._tool_paths or self._settings
        return bool(edited) or self.default_choice() != self.store.default_id()

    def reset(self) -> None:
        """Back to what's saved: after the changes were saved or dropped."""
        self._profiles = {p.id: p for p in self.store.all()}
        for pending in (self._changed, self._deleted, self._tool_paths, self._settings):
            pending.clear()
        self._fill_profiles(select=None)
        self.default.setCurrentIndex(max(self.default.findData(self.store.default_id()), 0))
        self._fill_tools()

    def changes(self) -> ConnectionChanges:
        return ConnectionChanges(
            saved=tuple(self._profiles[pid] for pid in sorted(self._changed)),
            deleted=tuple(sorted(self._deleted)),
            default=self.default_choice(),
            tool_paths=dict(self._tool_paths),
            settings={pid: c for pid, c in self._settings.items() if pid in self._changed},
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Same fix as the Settings page list: place the rows again once the theme's padding
        # has reached the list, or they draw on top of each other.
        self.list.doItemsLayout()

    # ---- tools (paths chosen here are also kept until Save) ----

    def _tool_view(self, tool: ToolDefinition) -> ToolDefinition:
        if tool.id in self._tool_paths:
            return replace(tool, executable=self._tool_paths[tool.id])
        return tool

    def _fill_tools(self) -> None:
        while self._tools_grid.count():
            item = self._tools_grid.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        self.tool_status: dict[str, QLabel] = {}
        self.tool_buttons: dict[str, dict[str, QPushButton]] = {}
        for row, entry in enumerate(self.catalogs.tools.all()):
            tool = self._tool_view(entry.item)
            found = detect.find_executable(tool)
            if found is None:
                status = QLabel(_("✗ Not found"))
                status.setToolTip(_("Install it, or locate its .exe."))
            else:
                status = QLabel(_("✓ Your choice") if tool.executable else _("✓ Found"))
                status.setToolTip(str(found))  # the full path, without filling the page
            # Only the actions that make sense in this state.
            actions = {"locate": _("Change path…") if found else _("Locate…")}
            if tool.executable:
                actions["automatic"] = _("Find automatically")
            if found is None and tool.website:
                actions["download"] = _("Download")
            buttons_row = QHBoxLayout()
            buttons_row.setContentsMargins(0, 0, 0, 0)
            buttons: dict[str, QPushButton] = {}
            for action, text in actions.items():
                button = QPushButton(text)
                button.clicked.connect(lambda _c=False, t=tool, a=action: self._tool_action(t, a))
                button.setEnabled(action == "download" or self.can_edit_tools)
                buttons_row.addWidget(button)
                buttons[action] = button
            buttons_row.addStretch(1)
            buttons_box = QWidget()
            buttons_box.setLayout(buttons_row)
            self._tools_grid.addWidget(QLabel(tool.name), row, 0)
            self._tools_grid.addWidget(status, row, 1)
            self._tools_grid.addWidget(buttons_box, row, 2)
            self.tool_status[tool.id], self.tool_buttons[tool.id] = status, buttons

    def _tool_action(self, tool: ToolDefinition, action: str) -> None:
        if action == "locate":
            self.locate(tool)
        elif action == "automatic":
            self.automatic(tool)
        else:
            QDesktopServices.openUrl(QUrl(tool.website))  # the browser downloads; we never do

    def locate(self, tool: ToolDefinition) -> None:
        name, _filter = QFileDialog.getOpenFileName(
            self,
            _("Where is {tool}?").format(tool=tool.name),
            str(Path.home()),
            _("Programs (*.exe)"),
        )
        if name:
            self._tool_paths[tool.id] = name
            self._fill_tools()

    def automatic(self, tool: ToolDefinition) -> None:
        self._tool_paths[tool.id] = ""
        self._fill_tools()

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "CapyPanel", message)
