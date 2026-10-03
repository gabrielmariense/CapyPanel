"""Settings > Connections: the shared connection profiles (add, edit, duplicate, delete, the
default one) and where each remote tool was found on this PC. Profile and tool changes are
saved when made; only the default profile waits for Save, like every other setting."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
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

from capypanel.core.hosts.document import OpenList
from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.definitions import ToolDefinition
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError, login_label, logins_of
from capypanel.ui.hosts import confirm
from capypanel.ui.settings.pages import Page, PathLabel, hint

MAX_PROFILE_NAME = 64


class ProfileDialog(QDialog):
    """Add, edit or duplicate a profile: name, tool, login, the tool's options, port."""

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

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Tool:"), self.tool)
        form.addRow(_("&Login:"), self.login)
        self._options_label = QLabel(_("Options:"))
        form.addRow(self._options_label, self._options_box)
        form.addRow(_("P&ort:"), self.port)
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
            self.login.addItem(login_label(login).capitalize(), login)
        self.login.setCurrentIndex(max(self.login.findData(wanted_login), 0))
        self.login.setEnabled(self.login.count() > 1)
        ticked = set(profile.options) if profile else set()
        for box in self.option_boxes.values():
            self._options.removeWidget(box)
            box.deleteLater()
        self.option_boxes = {}
        for option_id, name in tool.options.items():
            box = QCheckBox(name)
            box.setChecked(option_id in ticked)
            self._options.addWidget(box)
            self.option_boxes[option_id] = box
        self._options_label.setVisible(bool(tool.options))
        self._options_box.setVisible(bool(tool.options))
        self.port.setSpecialValueText(
            _("Default ({port})").format(port=tool.port) if tool.port else _("Default")
        )

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
        )


class ConnectionsPage(Page):
    def __init__(self, catalogs: Catalogs, document: OpenList | None) -> None:
        super().__init__(_("Connections"))
        self.catalogs = catalogs
        self.store = catalogs.profiles
        self.document = document
        self.can_edit = self.store.can_edit()

        profiles_box = QGroupBox(_("Connection profiles"))
        folder = PathLabel(self.store.folder)
        access = (
            _("Shared by everyone who uses CapyPanel from this folder. You can change them.")
            if self.can_edit
            else _(
                "Shared by everyone who uses CapyPanel from this folder. Read-only: only people "
                "Windows lets write this folder can change them."
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

        tools_box = QGroupBox(_("Remote tools on this PC"))
        self._tools_grid = QGridLayout(tools_box)
        self._tools_grid.setColumnStretch(1, 1)

        self.body.addWidget(profiles_box, 1)
        self.body.addWidget(tools_box)
        self._fill_profiles(select=None)
        self.default.setCurrentIndex(max(self.default.findData(self.store.default_id()), 0))
        self._fill_tools()

    # ---- profiles ----

    def _fill_profiles(self, select: str | None) -> None:
        current_default = self.default.currentData() or self.store.default_id()
        self.list.clear()
        self.default.clear()
        for profile in self.store.all():
            item = QListWidgetItem(profile.name)
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self.list.addItem(item)
            if profile.id == select:
                item.setSelected(True)
                self.list.setCurrentItem(item)
            self.default.addItem(profile.name, profile.id)
        self.default.setCurrentIndex(max(self.default.findData(current_default), 0))
        self._update_buttons()

    def _selected(self) -> str | None:
        items = self.list.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _update_buttons(self) -> None:
        picked = self.can_edit and self._selected() is not None
        self.add_button.setEnabled(self.can_edit)
        for button in (self.edit_button, self.duplicate_button, self.delete_button):
            button.setEnabled(picked)

    def _dialog(self, title: str, profile: ConnectionProfile | None) -> ProfileDialog:
        tools = [e.item for e in self.catalogs.tools.all()]
        installed = {t.id for t in tools if detect.find_executable(t) is not None}
        return ProfileDialog(self, title, tools, installed, profile)

    def add(self) -> None:
        dialog = self._dialog(_("New connection profile"), None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name.text().strip()
            self._save(dialog.profile(self.store.new_id(name)))

    def edit(self) -> None:
        selected = self._selected()
        profile = self.store.find(selected) if selected else None
        if profile is None or not self.can_edit:
            return
        dialog = self._dialog(_("Edit connection profile"), profile)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save(replace(dialog.profile(profile.id), extra=profile.extra))

    def duplicate(self) -> None:
        selected = self._selected()
        profile = self.store.find(selected) if selected else None
        if profile is None:
            return
        copy = replace(profile, name=_("{profile} (copy)").format(profile=profile.name))
        dialog = self._dialog(_("Duplicate connection profile"), copy)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.name.text().strip()
            self._save(dialog.profile(self.store.new_id(name)))

    def delete(self) -> None:
        selected = self._selected()
        profile = self.store.find(selected) if selected else None
        if profile is None:
            return
        text = _("Delete the connection profile “{profile}”? Everyone who uses this folder "
                 "loses it.").format(profile=profile.name)  # fmt: skip
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
        try:
            self.store.delete(profile.id)
        except (ProfileError, OSError) as e:
            self._error(_("Couldn't delete the profile: {error}").format(error=e))
        self._fill_profiles(select=None)

    def _uses(self, profile_id: str) -> tuple[int, int]:
        if self.document is None:
            return 0, 0
        hosts = self.document.hosts
        return (
            sum(h.profile == profile_id for h in hosts.hosts),
            sum(g.profile == profile_id for g in hosts.groups),
        )

    def _save(self, profile: ConnectionProfile) -> None:
        try:
            self.store.save(profile)
        except (ProfileError, OSError) as e:
            self._error(_("Couldn't save the profile: {error}").format(error=e))
            return
        self._fill_profiles(select=profile.id)

    def default_choice(self) -> str:
        return self.default.currentData() or self.store.default_id()

    # ---- tools ----

    def _fill_tools(self) -> None:
        while self._tools_grid.count():
            item = self._tools_grid.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()
        for row, entry in enumerate(self.catalogs.tools.all()):
            tool = entry.item
            found = detect.find_executable(tool)
            status = (
                PathLabel(found) if found else hint(_("Not found: install it, or select its .exe."))
            )
            locate = QPushButton(_("Locate…"))
            locate.clicked.connect(lambda _c=False, t=tool: self.locate(t))
            automatic = QPushButton(_("Automatic"))
            automatic.setToolTip(_("Forget the chosen path and find the tool by itself again"))
            automatic.setEnabled(bool(tool.executable))
            automatic.clicked.connect(lambda _c=False, t=tool: self.automatic(t))
            self._tools_grid.addWidget(QLabel(tool.name), row, 0)
            self._tools_grid.addWidget(status, row, 1)
            self._tools_grid.addWidget(locate, row, 2)
            self._tools_grid.addWidget(automatic, row, 3)

    def locate(self, tool: ToolDefinition) -> None:
        name, _filter = QFileDialog.getOpenFileName(
            self,
            _("Where is {tool}?").format(tool=tool.name),
            str(Path.home()),
            _("Programs (*.exe)"),
        )
        if name:
            self.catalogs.tools.save_user_copy(replace(tool, executable=name))
            self._fill_tools()

    def automatic(self, tool: ToolDefinition) -> None:
        self.catalogs.tools.reset(tool.id)
        self._fill_tools()

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "CapyPanel", message)
