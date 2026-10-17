"""The Settings pages. Each one shows the current values and reports the user's choices;
nothing here changes the app, except the host-list buttons that write a file when clicked."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
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
from capypanel.ui.themes import engine as themes


class Page(QWidget):
    """A settings page: its sections, one under the other. Its title shows in the page list
    only. `changed` fires when validity may change."""

    changed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)  # between sections

    def is_valid(self) -> bool:
        return True


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
    """The app's language and theme. Both apply as soon as they're picked, with no Save."""

    def __init__(self, *, language: str, registry: themes.Registry, theme_id: str) -> None:
        super().__init__(_("General"))
        # Each language is named in its own language, so anyone can find theirs.
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(self.language.findData(language), 0))
        language_box = Section(_("Language"))
        language_row = QHBoxLayout(language_box.inner)
        language_row.setContentsMargins(0, 2, 0, 0)
        language_row.addWidget(self.language)
        language_row.addStretch(1)
        # The Windows themes, then the app's own. The window shows the theme picked: no preview.
        self.theme = QComboBox()
        previous = None
        for theme in registry.all():
            if previous and theme.engine != previous:
                self.theme.insertSeparator(self.theme.count())
            previous = theme.engine
            self.theme.addItem(theme.title(), theme.id)
        self.theme.setCurrentIndex(max(self.theme.findData(theme_id), 0))
        theme_box = Section(_("Theme"))
        theme_layout = QVBoxLayout(theme_box.inner)
        theme_layout.setContentsMargins(0, 2, 0, 0)
        theme_row = QHBoxLayout()
        theme_row.addWidget(self.theme)
        theme_row.addStretch(1)
        theme_layout.addLayout(theme_row)
        theme_layout.addWidget(
            notes(
                _("Windows themes use Windows' own look, with your accent color."),
                _("CapyPanel themes look the same on every computer."),
            )
        )
        self.body.addWidget(language_box)
        self.body.addWidget(theme_box)
        self.body.addStretch(1)

    def language_choice(self) -> str:
        return str(self.language.currentData() or i18n.DEFAULT_LANGUAGE)

    def theme_id(self) -> str:
        return str(self.theme.currentData() or themes.DEFAULT_THEME.id)


class FilesPage(Page):
    """Where CapyPanel keeps everything, each folder a click away."""

    def __init__(self, paths: settings.Paths) -> None:
        super().__init__(_("Files"))
        files = Section(_("Where CapyPanel keeps its files"))
        grid = QGridLayout(files.inner)
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setColumnStretch(1, 1)
        folders = (
            (_("Shared files"), paths.root),
            (_("Shared lists"), paths.shared_lists_dir),
            (_("Your files"), paths.user_dir),
            (_("Your lists"), paths.user_lists_dir),
            (_("Logs"), paths.log_dir),
        )
        for row, (label, folder) in enumerate(folders):
            button = QPushButton(_("Open folder"))
            button.clicked.connect(lambda _checked=False, f=folder: open_folder(f))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(PathLabel(folder), row, 1)
            grid.addWidget(button, row, 2)
        lines = [
            _("Shared files: connection profiles and tools, for everyone."),
            _("Shared lists: the default list, and every list saved there, for everyone."),
            _("Your files: your settings, private to you and admins."),
            _("Your lists: your personal list, and every list saved there, only for you."),
            _("Logs: one per user, named after the account."),
        ]
        if paths.portable:
            lines.append(_("Portable mode: everything stays in the app's own folder."))
        grid.addWidget(notes(*lines), len(folders), 0, 1, 3)
        self.body.addWidget(files)
        self.body.addStretch(1)


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
        label = QLabel(_("&Open on startup:"))
        label.setBuddy(self.start_list)
        # Labels in one column, the dropdowns lined up beside them at the same width.
        start_layout = QGridLayout(start.inner)
        start_layout.setContentsMargins(0, 2, 0, 0)
        start_layout.setColumnStretch(1, 1)
        start_layout.addWidget(label, 0, 0)
        start_layout.addWidget(self.start_list, 0, 1)
        start_layout.addWidget(
            notes(_("If that list can't be opened: the default list, then your personal list.")),
            1, 0, 1, 2,
        )  # fmt: skip
        # What the open list shows first; each list keeps its own choice. One button: its menu
        # has All hosts, Where I left off, and "A chosen group" with the groups as a tree.
        self._host_list = host_list
        self._first = start_view or (locations.SHOW_ALL, "")
        self.show_first = MenuCombo()
        self.show_first.setEnabled(start_view is not None)
        self.show_first.menu().aboutToShow.connect(self._fill_first_menu)
        self._show_first_text()
        first_label = QLabel(_("Show &first:"))
        first_label.setBuddy(self.show_first)
        start_layout.addWidget(first_label, 2, 0)
        start_layout.addWidget(self.show_first, 2, 1)
        start_layout.addWidget(
            notes(
                _("For the list open now; each list keeps its own. A group's right-click menu "
                  "can choose it too.")
                if start_view is not None
                else _("Open a host list to choose what it shows first.")
            ),
            3, 0, 1, 2,
        )  # fmt: skip

        refresh = Section(_("Refresh"))
        self.auto_status = QCheckBox(_("&Refresh the status of the hosts shown every"))
        self.auto_status.setChecked(auto_status[0])
        self.auto_minutes = QSpinBox()
        self.auto_minutes.setRange(1, 120)
        self.auto_minutes.setValue(auto_status[1])
        self.auto_minutes.setSuffix(_(" min"))
        self.auto_minutes.setEnabled(auto_status[0])
        self.auto_status.toggled.connect(self.auto_minutes.setEnabled)
        auto_row = QHBoxLayout()
        auto_row.addWidget(self.auto_status)
        auto_row.addWidget(self.auto_minutes)
        auto_row.addStretch(1)
        refresh_layout = QVBoxLayout(refresh.inner)
        refresh_layout.setContentsMargins(0, 2, 0, 0)
        refresh_layout.addLayout(auto_row)
        refresh_layout.addWidget(
            notes(
                _("Only ping and ports, never logged-on users, so no account is used."),
                _("Off by default; Refresh in the toolbar always works."),
            )
        )

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
    """The same lists as the list dropdown; the one picked here opens on Save."""

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
        found: list[Path] | None = None,
    ) -> None:
        super().__init__(_("Host lists"))
        self.view = HostListsView(
            default_list=default_list,
            personal_list=personal_list,
            added=added,
            document=document,
            found=found,
        )
        box = Section(_("Lists"))
        lists = QVBoxLayout(box.inner)
        lists.setContentsMargins(0, 2, 0, 0)
        lists.addWidget(self.view)
        self.body.addWidget(box, 1)
        self.view.changed.connect(self.changed.emit)

    @property
    def written(self) -> list[Path]:
        return self.view.written

    def chosen(self) -> Path | None:
        return self.view.selected()

    def added(self) -> list[Path]:
        return list(self.view.added)

    def is_valid(self) -> bool:
        return self.view.can_open(self.chosen())
