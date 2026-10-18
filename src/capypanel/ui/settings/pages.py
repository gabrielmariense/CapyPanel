"""The Settings pages. Each one shows the current values and reports each choice as it's
made (`changed`); the Settings window hands it on, to apply at once."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.locations import ListKind
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.ui.groups import TreeMenu, fill_host_move_menu
from capypanel.ui.host_lists import HostListsView
from capypanel.ui.hosts import group_path
from capypanel.ui.menus import MenuCombo
from capypanel.ui.notes import notes
from capypanel.ui.tables import fit_rows, grid_table, with_buttons
from capypanel.ui.themes import engine as themes


class Page(QWidget):
    """A settings page: its sections, one under the other. Its title shows in the page list
    only. `changed` fires on every choice made on it."""

    changed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)  # between sections


class Section(QWidget):
    """A part of a page: a heading in the accent colour over a thin line, as in the Details
    pane, then its content in `inner`. No frame around it."""

    def __init__(self, title: str) -> None:
        super().__init__()
        heading = QLabel(title)
        heading.setObjectName("detailsSection")
        rule = QFrame()
        rule.setObjectName("detailsRule")
        self.inner = QWidget()
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(heading)
        column.addWidget(rule)
        column.addWidget(self.inner, 1)


class SettingRow(QWidget):
    """A setting: its name over a one-line description, its control at the right end. Every
    row's control has the same width, so controls line up on both edges down the page."""

    CONTROL_WIDTH = 240

    def __init__(self, name: str, description: str, control: QWidget) -> None:
        super().__init__()
        self.name = QLabel(name)
        self.name.setObjectName("rowName")
        self.name.setBuddy(control)
        self.description = notes(description)  # the size of the notes under tables
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addWidget(self.name)
        words.addWidget(self.description)
        control.setFixedWidth(self.CONTROL_WIDTH)
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 4, 0, 4)
        line.setSpacing(16)
        line.addLayout(words, 1)
        line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


def add_rows(layout: QVBoxLayout, *rows: SettingRow) -> None:
    """Rows one under the other, a faint line between two."""
    for index, row in enumerate(rows):
        if index:
            line = QFrame()
            line.setObjectName("rowLine")
            layout.addWidget(line)
        layout.addWidget(row)


def _section_layout(section: "Section") -> QVBoxLayout:
    layout = QVBoxLayout(section.inner)
    layout.setContentsMargins(0, 2, 0, 0)
    layout.setSpacing(6)
    return layout


class PathLabel(QLabel):
    """A file path cut in the middle ("C:\\Users\\…\\hosts.json") when it doesn't fit."""

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("hint")
        self.setMinimumWidth(80)
        self._full = ""
        if path is not None:
            self.set_path(path)

    def set_path(self, path: Path) -> None:
        self._full = str(path)
        self.setToolTip(self._full)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(self.width(), self.minimumWidth())
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width))


def open_folder(folder: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


# ---- CapyPanel: General and Files ----


class GeneralPage(Page):
    """The app's language and theme. Both apply as soon as they're picked."""

    def __init__(self, *, language: str, registry: themes.Registry, theme_id: str) -> None:
        super().__init__(_("General"))
        # Each language is named in its own language, so anyone can find theirs.
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(self.language.findData(language), 0))
        # The Windows themes, then the app's own. The window shows the theme picked: no preview.
        self.theme = QComboBox()
        previous = None
        for theme in registry.all():
            if previous and theme.engine != previous:
                self.theme.insertSeparator(self.theme.count())
            previous = theme.engine
            self.theme.addItem(theme.title(), theme.id)
        self.theme.setCurrentIndex(max(self.theme.findData(theme_id), 0))
        section = Section(_("Language and theme"))
        add_rows(
            _section_layout(section),
            SettingRow(_("&Language"), _("The app's language. Changes at once."), self.language),
            SettingRow(
                _("&Theme"),
                _("Windows themes follow Windows' look and accent; CapyPanel themes look the "
                  "same everywhere."),
                self.theme,
            ),
        )  # fmt: skip
        self.body.addWidget(section)
        self.body.addStretch(1)

    def language_choice(self) -> str:
        return str(self.language.currentData() or i18n.DEFAULT_LANGUAGE)

    def theme_id(self) -> str:
        return str(self.theme.currentData() or themes.DEFAULT_THEME.id)


class FilesPage(Page):
    """Where CapyPanel keeps everything, each folder a click away."""

    def __init__(self, paths: settings.Paths) -> None:
        super().__init__(_("Files"))
        section = Section(_("Folders"))
        folders = (
            (_("Shared files"), paths.root,
             _("Connection profiles and remote tools, for everyone on this PC.")),
            (_("Shared lists"), paths.shared_lists_dir,
             _("The default list, and every list saved there, for everyone on this PC.")),
            (_("Your files"), paths.user_dir,
             _("Your settings, private to you and administrators.")),
            (_("Your lists"), paths.user_lists_dir,
             _("Your personal list, and every list saved there, only for you.")),
            (_("Logs"), paths.log_dir, _("One per user, named after the account.")),
        )  # fmt: skip
        # The one table design; a double-click opens the folder too.
        self.folders = grid_table([_("Folder"), _("Where")])
        self.folders.setColumnWidth(0, 170)
        self.folders.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # a path keeps both ends
        for label, folder, holds in folders:
            item = QTreeWidgetItem([label, str(folder)])
            item.setToolTip(0, holds)  # what it holds: hover the folder's name
            item.setToolTip(1, str(folder))
            item.setData(0, Qt.ItemDataRole.UserRole, str(folder))
            self.folders.addTopLevelItem(item)
        first = self.folders.topLevelItem(0)
        if first is not None:
            self.folders.setCurrentItem(first)
        fit_rows(self.folders)
        self.open_button = QPushButton(_("Open folder"))
        self.open_button.clicked.connect(self._open_picked)
        self.folders.itemDoubleClicked.connect(lambda *_a: self._open_picked())
        layout = _section_layout(section)
        layout.addWidget(with_buttons(self.folders, [self.open_button]))
        lines = [_("Hover a folder to see what it holds.")]
        if paths.portable:
            lines.append(_("Portable mode: everything stays in the app's own folder."))
        layout.addWidget(notes(*lines))
        self.body.addWidget(section)
        self.body.addStretch(1)

    def _open_picked(self) -> None:
        item = self.folders.currentItem()
        if item is not None:
            open_folder(Path(item.data(0, Qt.ItemDataRole.UserRole)))


# ---- Hosts: General ----


class HostsPage(Page):
    """The Hosts tool's own settings: which list opens, what it shows first, and Refresh."""

    def __init__(
        self,
        *,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        added: list[Path],
        auto_status: tuple[bool, int] = (False, 5),
        start_view: tuple[str, str] | None = None,
        host_list: HostList | None = None,
    ) -> None:
        """start_view: the open list's (show, group); None when no list is open. host_list: that
        list, for its groups."""
        super().__init__(_("General"))
        start = Section(_("Startup"))
        self.start_list = QComboBox()
        self.start_list.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.start_list.setMinimumContentsLength(24)
        self.start_list.addItem(_("The last used list"), locations.START_LAST)
        self.start_list.addItem(_("The default list"), locations.START_DEFAULT)
        self.start_list.addItem(_("My personal list"), locations.START_PERSONAL)
        others = [
            p
            for p in added
            if locations.list_kind(p, default=default_list, personal=personal_list)
            is ListKind.SHARED
        ]
        if (
            isinstance(start_list, str)
            and start_list
            not in (locations.START_LAST, locations.START_DEFAULT, locations.START_PERSONAL)
            and not any(locations.same_path(Path(start_list), p) for p in others)
        ):
            others.insert(0, Path(start_list))
        for path in others:
            self.start_list.addItem(str(path), str(path))
            self.start_list.setItemData(
                self.start_list.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole
            )
        index = self.start_list.findData(start_list)
        self.start_list.setCurrentIndex(max(index, 0))
        self.start_list.currentIndexChanged.connect(lambda _i: self.changed.emit())
        # What the open list shows first; each list keeps its own choice. One button: its menu
        # has All hosts, Where I left off, and "A chosen group" with the groups as a tree.
        self._host_list = host_list
        self._first = start_view or (locations.SHOW_ALL, "")
        self.show_first = MenuCombo()
        self.show_first.setEnabled(start_view is not None)
        self.show_first.menu().aboutToShow.connect(self._fill_first_menu)
        self._show_first_text()
        self._first_row = SettingRow(_("Show &first"), "", self.show_first)
        self._show_first_note(start_view is not None)
        add_rows(
            _section_layout(start),
            SettingRow(
                _("&Open on startup"),
                _("If that list can't be opened: the default list, then your personal list."),
                self.start_list,
            ),
            self._first_row,
        )

        refresh = Section(_("Refresh"))
        # The tick and how often, together at the row's right end.
        self.auto_status = QCheckBox(_("&every"))
        self.auto_status.setChecked(auto_status[0])
        self.auto_minutes = QSpinBox()
        self.auto_minutes.setRange(1, 120)
        self.auto_minutes.setValue(auto_status[1])
        self.auto_minutes.setSuffix(_(" min"))
        self.auto_minutes.setEnabled(auto_status[0])
        self.auto_status.toggled.connect(self.auto_minutes.setEnabled)
        self.auto_status.toggled.connect(lambda _on: self.changed.emit())
        self.auto_minutes.valueChanged.connect(lambda _v: self.changed.emit())
        every = QWidget()
        controls = QHBoxLayout(every)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.auto_status)
        controls.addWidget(self.auto_minutes, 1)
        auto_row = SettingRow(
            _("Refresh status by itself"),
            _("Only ping and ports, never logged-on users, so no account is needed. Refresh in "
              "the toolbar always works."),
            every,
        )  # fmt: skip
        auto_row.name.setBuddy(self.auto_status)
        add_rows(_section_layout(refresh), auto_row)

        self.body.addWidget(start)
        self.body.addWidget(refresh)
        self.body.addStretch(1)

    def start_choice(self) -> str:
        return str(self.start_list.currentData())

    def _fill_first_menu(self) -> None:
        menu = self.show_first.menu()
        menu.clear()
        show, group = self._first
        for text, value in (
            (_("All hosts"), locations.SHOW_ALL),
            (_("Where I left off"), locations.SHOW_LAST),
        ):
            item = menu.addAction(text)
            item.setCheckable(True)
            item.setChecked(show == value)
            item.triggered.connect(lambda _c=False, v=value: self.pick_first(v))
        chosen = TreeMenu(_("A chosen &group"), menu)
        menu.addMenu(chosen)
        if self._host_list is not None:
            current = group if show == locations.SHOW_GROUP else None
            fill_host_move_menu(
                chosen,
                self._host_list,
                lambda g: self.pick_first(locations.SHOW_GROUP, g),
                current=current,
            )

    def pick_first(self, show: str, group: str = "") -> None:
        self._first = (show, group)
        self._show_first_text()
        self.changed.emit()

    def list_opened(self, start_view: tuple[str, str] | None, host_list: HostList | None) -> None:
        """Another list is open: Show first is now about it."""
        self._host_list, self._first = host_list, start_view or (locations.SHOW_ALL, "")
        self.show_first.setEnabled(start_view is not None)
        self._show_first_text()
        self._show_first_note(start_view is not None)

    def _show_first_note(self, open_list: bool) -> None:
        self._first_row.description.setText(
            _("For the list open now; each list keeps its own.")
            if open_list
            else _("Open a host list to choose what it shows first.")
        )

    def _show_first_text(self) -> None:
        show, group = self._first
        if show == locations.SHOW_GROUP:
            name = group_path(self._host_list, group) if self._host_list is not None else group
            self.show_first.setText(_("Group: {name}").format(name=name))
        else:
            labels = {locations.SHOW_LAST: _("Where I left off")}
            self.show_first.setText(labels.get(show, _("All hosts")))

    def show_first_choice(self) -> tuple[str, str] | None:
        """(show, group) for the open list; None when no list is open."""
        return self._first if self.show_first.isEnabled() else None

    def auto_status_choice(self) -> tuple[bool, int]:
        return self.auto_status.isChecked(), self.auto_minutes.value()


# ---- Host lists ----


class HostListsPage(Page):
    """The same lists as the list dropdown; a double-click opens one."""

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
        found: list[Path] | None = None,
        hidden: list[Path] | None = None,
    ) -> None:
        super().__init__(_("Host lists"))
        self.view = HostListsView(
            default_list=default_list,
            personal_list=personal_list,
            added=added,
            document=document,
            found=found,
            hidden=hidden,
        )
        box = Section(_("Host lists"))
        lists = QVBoxLayout(box.inner)
        lists.setContentsMargins(0, 2, 0, 0)
        lists.addWidget(self.view)
        self.body.addWidget(box)
        self.body.addStretch(1)
        self.view.changed.connect(self.changed.emit)

    def chosen(self) -> Path | None:
        return self.view.selected()

    def added(self) -> list[Path]:
        return list(self.view.added)

    def hidden(self) -> list[Path]:
        return list(self.view.hidden)
