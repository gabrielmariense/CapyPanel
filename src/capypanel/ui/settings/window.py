"""The Settings window: a search and a list of pages on the left, Close at the bottom. Every
choice applies as soon as it's made, with no Save: the main window applies what the signals hand
over, and profiles and tool paths are written by their page at once."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.core.tools.catalog import Catalogs
from capypanel.ui.notes import hint
from capypanel.ui.settings import search
from capypanel.ui.settings.connections import ConnectionsPage
from capypanel.ui.settings.pages import (
    FilesPage,
    GeneralPage,
    HostListsPage,
    HostsPage,
    Page,
    Section,
)
from capypanel.ui.themes import engine as themes

# The pages' titles, as the pages set them, and the groups' labels: the page list is sized for the
# longest in any language. The app's pages first, then each tool's.
PAGE_TITLES = ("General", "Files", "General", "Host lists", "Connections")
GROUPS = (
    ("CapyPanel", ("general", "files")),
    ("Hosts", ("hosts", "host_lists", "connections")),
)
SEARCH_FROM = 3  # letters typed before the search shows its results
ROOM = 60  # spare width past the widest page: a button row never ends just short of its table


@dataclass(frozen=True)
class SettingsPrefs:
    """The choices the main window keeps in its settings file, handed over on every change."""

    start_list: str  # see locations.START_KEY
    added_lists: list[Path]  # the lists in Host lists, besides the default and personal
    hidden_lists: list[Path]  # lists in a lists folder removed from Host lists
    auto_status: tuple[bool, int] = (False, 5)  # check Status by itself, every N minutes
    start_view: tuple[str, str] | None = None  # the open list's (show, group) first


class SettingsDialog(QDialog):
    language_picked = Signal(str)
    theme_picked = Signal(str)
    prefs_changed = Signal(object)  # SettingsPrefs
    open_requested = Signal(object)  # a list's Path, to open now
    profiles_changed = Signal()  # profiles or tool paths were written

    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
        registry: themes.Registry,
        found: list[Path] | None = None,
        hidden: list[Path] | None = None,
        catalogs: Catalogs,
        auto_status: tuple[bool, int] = (False, 5),
        start_view: tuple[str, str] | None = None,
        host_list: HostList | None = None,
    ) -> None:
        super().__init__(parent)
        self._host_list = host_list
        self._paths = paths
        self._default_list = default_list
        self._personal_list = personal_list
        self._document = document
        self._found = found or []
        self._registry = registry
        self._catalogs = catalogs
        # What's set now: a language switch rebuilds the window with these.
        self._start_list, self._added, self._hidden = start_list, added, hidden or []
        self._auto_status, self._start_view = auto_status, start_view
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch (see DECISIONS, code cleanup).
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._build(themes.current().id)
        self.resize(860, 640)  # one-line descriptions on one line; Connections without scrolling

    def _build(self, theme_id: str) -> None:
        """The pages and buttons, in the current language, showing what's set."""
        self._building = True  # pages report changes while they're filled
        self.setWindowTitle(_("Settings"))
        self.general = GeneralPage(
            language=i18n.language(), registry=self._registry, theme_id=theme_id
        )
        self.files = FilesPage(self._paths)
        self.hosts = HostsPage(
            start_list=self._start_list,
            default_list=self._default_list,
            personal_list=self._personal_list,
            added=self._added,
            auto_status=self._auto_status,
            start_view=self._start_view,
            host_list=self._host_list,
        )
        self.host_lists = HostListsPage(
            default_list=self._default_list,
            personal_list=self._personal_list,
            document=self._document,
            added=self._added,
            found=self._found,
            hidden=self._hidden,
        )
        self.connections = ConnectionsPage(self._catalogs, self._document)
        self.pages: dict[str, Page] = {
            "general": self.general,
            "files": self.files,
            "hosts": self.hosts,
            "host_lists": self.host_lists,
            "connections": self.connections,
        }
        self.general.language.currentIndexChanged.connect(self._language_changed)
        self.general.theme.currentIndexChanged.connect(
            lambda: self.theme_picked.emit(self.general.theme_id())
        )
        for page in (self.hosts, self.host_lists):
            page.changed.connect(self._prefs_changed)
        self.host_lists.view.open_requested.connect(self.open_requested.emit)
        self.connections.changed.connect(self.profiles_changed.emit)

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        # No setUniformItemSizes: it caches a row height measured before the theme reaches the
        # list, and the rows then overlap (13 px rows for 27 px of text).
        self.stack = QStackedWidget()
        # Each group: its label (not a page), then its pages. _rows maps rows to page ids.
        self._rows: list[str | None] = []
        for group, ids in GROUPS:
            label = QListWidgetItem(_(group))
            label.setFlags(Qt.ItemFlag.NoItemFlags)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            self.page_list.addItem(label)
            self._rows.append(None)
            for page_id in ids:
                self.page_list.addItem("   " + self.pages[page_id].title)
                self._rows.append(page_id)
        for page in self.pages.values():
            self.stack.addWidget(_scrolling(page))  # long pages scroll
        # Search results: the matching sections of every page, lent here while searching.
        self._results = Page(_("Search"))
        self.stack.addWidget(_scrolling(self._results))
        self._lent: list[tuple[QVBoxLayout, int, QWidget]] = []  # where each came from
        self._result_labels: list[QLabel] = []
        self._marks = search.SearchMarks(self._results)
        # Wide enough for the longest page name in any language, so the list never cuts it and
        # keeps its width when the language changes.
        metrics = self.page_list.fontMetrics()
        longest = max(
            metrics.horizontalAdvance("   " + title)
            for message in (*PAGE_TITLES, *(group for group, _ids in GROUPS))
            for title in i18n.in_every_language(message)
        )
        self.page_list.setFixedWidth(longest + 64)
        self.page_list.currentRowChanged.connect(self._page_picked)
        self.page_list.setCurrentRow(self.row_of("general"))

        # Only Close: every choice is applied already. Not a default button, so Enter in a
        # field never closes the window by surprise.
        self.buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole.RejectRole
        self.close_button = self.buttons.addButton(_("Close"), role)
        self.buttons.rejected.connect(self.reject)
        content = QWidget()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        # A search above the pages: only the pages that mention what's typed stay listed.
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search settings"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(self.page_list.width())
        self.search.textChanged.connect(self._filter_pages)
        side = QVBoxLayout()
        side.addWidget(self.search)
        side.addWidget(self.page_list, 1)
        columns.addLayout(side)
        columns.addWidget(self.stack, 1)
        inside = QVBoxLayout(content)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addLayout(columns, 1)
        inside.addWidget(self.buttons)
        self._layout.addWidget(content)
        self._content = content
        self._no_default_buttons()
        self._building = False

    def _language_changed(self) -> None:
        code = self.general.language_choice()
        if code != i18n.language():
            self.language_picked.emit(code)  # the app switches now; Settings follows
            QTimer.singleShot(0, self, self._rebuild)  # after the dropdown has closed

    def _rebuild(self) -> None:
        """The same window in the new language, on the same page."""
        page = self._shown_page()  # not "search": the rebuilt window opens without one
        chosen = self.host_lists.chosen()
        old = self._content
        old.hide()
        self._layout.removeWidget(old)
        self._old.append(old)
        self._build(self.general.theme_id())
        if chosen is not None:
            self.host_lists.view.select(chosen)
        self.show_page(page)
        self._make_room()
        self.general.language.setFocus()

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):  # the pages' buttons too
            button.setAutoDefault(False)
            button.setDefault(False)

    def _page_picked(self, row: int) -> None:
        page_id = self._rows[row] if 0 <= row < len(self._rows) else None
        if page_id is None:
            return  # a group's label, never picked
        if self._lent:  # picking a page ends the search: its sections go home first
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._end_search()
        self.stack.setCurrentIndex(list(self.pages).index(page_id))

    # ---- applying at once ----

    def prefs(self) -> SettingsPrefs:
        return SettingsPrefs(
            start_list=self.hosts.start_choice(),
            added_lists=self.host_lists.added(),
            hidden_lists=self.host_lists.hidden(),
            auto_status=self.hosts.auto_status_choice(),
            start_view=self.hosts.show_first_choice(),
        )

    def _prefs_changed(self) -> None:
        if self._building:
            return
        prefs = self.prefs()
        self._start_list, self._added = prefs.start_list, prefs.added_lists
        self._hidden, self._auto_status = prefs.hidden_lists, prefs.auto_status
        self._start_view = prefs.start_view
        self.prefs_changed.emit(prefs)

    def list_opened(
        self,
        document: OpenList | None,
        start_view: tuple[str, str] | None,
        host_list: HostList | None,
    ) -> None:
        """The main window opened a list: Host lists marks it, Show first is now about it."""
        self._document, self._start_view, self._host_list = document, start_view, host_list
        self.host_lists.view.list_opened(document)
        self.hosts.list_opened(start_view, host_list)
        self.connections.profiles.document = document

    def _filter_pages(self, text: str) -> None:
        """From SEARCH_FROM letters on: every section that mentions `text` at the start of a
        word, from every page, on one results page, each under its page's name, to change right
        there, with each match marked. The page list keeps only the pages with a match. Fewer
        letters: back to the pages as they were."""
        page = self._shown_page()
        self._end_search()
        wanted = text.strip().casefold()
        if len(wanted) < SEARCH_FROM:
            self.stack.setCurrentIndex(list(self.pages).index(page))
            return
        group_of = {pid: group for group, ids in GROUPS for pid in ids}
        shown: list[str] = []
        layout = self._results.body
        for page_id, source in self.pages.items():
            title_match = bool(search.spans(source.title, wanted))
            parts = (source.body.itemAt(i) for i in range(source.body.count()))
            sections = [
                w for part in parts
                if part is not None and isinstance(w := part.widget(), Section)
                and (title_match or search.mentions(w, wanted))
            ]  # fmt: skip
            if not sections:
                continue
            shown.append(page_id)
            where = hint(f"{_(group_of[page_id])} › {source.title}")
            self._result_labels.append(where)
            layout.addWidget(where)
            for section in sections:
                self._lent.append((source.body, source.body.indexOf(section), section))
                source.body.removeWidget(section)
                layout.addWidget(section)
        if not shown:
            nothing = hint(_("No settings mention “{text}”.").format(text=text.strip()))
            self._result_labels.append(nothing)
            layout.addWidget(nothing)
        layout.addStretch(1)
        lent = [section for _home, _index, section in self._lent]
        self._marks.mark([*self._result_labels[: len(shown)], *lent], wanted)
        for row, page_id in enumerate(self._rows):
            if page_id is not None:
                self.page_list.setRowHidden(row, page_id not in shown)
        for row, page_id in enumerate(self._rows):  # a group's label: hidden with its pages
            if page_id is None:
                after = self._rows[row + 1 :]
                end = after.index(None) if None in after else len(after)
                self.page_list.setRowHidden(row, not any(p in shown for p in after[:end]))
        self.page_list.blockSignals(True)
        self.page_list.clearSelection()
        self.page_list.blockSignals(False)
        self._before_search = page
        self.stack.setCurrentIndex(len(self.pages))

    def _end_search(self) -> None:
        """Sends the lent sections back to their pages, where they were, and lists every page."""
        self._marks.clear()
        layout = self._results.body
        for home, index, section in reversed(self._lent):
            layout.removeWidget(section)
            home.insertWidget(index, section)
        self._lent.clear()
        for label in self._result_labels:
            label.hide()
            label.deleteLater()  # a plain label: safe to delete, unlike lists and trees
        self._result_labels.clear()
        while layout.count() > 0:  # the stretch under the results
            layout.takeAt(0)
        for row in range(self.page_list.count()):
            self.page_list.setRowHidden(row, False)

    def _shown_page(self) -> str:
        """The page shown, or the one shown before the search."""
        if self.stack.currentIndex() < len(self.pages):
            return list(self.pages)[self.stack.currentIndex()]
        return getattr(self, "_before_search", "general")

    def show_page(self, page_id: str) -> None:
        self.page_list.setCurrentRow(self.row_of(page_id))

    def row_of(self, page_id: str) -> int:
        return self._rows.index(page_id)

    def current_page(self) -> str:
        """The page shown; "search" while the search's results are."""
        index = self.stack.currentIndex()
        return list(self.pages)[index] if index < len(self.pages) else "search"

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._make_room()
        themes.paint_title_bar(self)
        self._no_default_buttons()

    def _make_room(self) -> None:
        """At least ROOM wider than the widest page needs, in this language."""
        width = self.minimumSizeHint().width() + ROOM
        if self.width() < width:
            self.resize(width, self.height())


class _PageArea(QScrollArea):
    """Never narrower than its page: the window widens instead of cutting off a button row."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        page = self.widget()
        if page is None:
            return hint
        bar = self.verticalScrollBar().sizeHint().width()
        return QSize(max(hint.width(), page.minimumSizeHint().width() + bar), hint.height())


def _scrolling(page: Page) -> QScrollArea:
    """A page that scrolls when it's taller than the window, with no frame of its own."""
    area = _PageArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area
