"""The Settings window: a search and the page list on the left, the page on the right. No
buttons: the window's X or Esc closes it, and every choice applies as soon as it's made. The
page list names each group (CapyPanel, then each tool) with its pages under it, and About at the
very bottom; a click shows that one page, which scrolls on its own when it's taller than the
window. A tool's pages apply their choices through the tool (see SettingsGroup)."""

from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
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
from capypanel.core.i18n import _
from capypanel.ui.about import AboutPage
from capypanel.ui.notes import hint
from capypanel.ui.settings import search
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import GeneralPage, Page, Section
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import ToolInfo

APP_GROUP = ("CapyPanel", ("general",))
PINNED = ("about",)  # pages kept at the very bottom of the page list, apart from the groups
SEARCH_FROM = 3  # letters typed before the search shows its results
ROOM = 60  # spare width past the widest page: a button row never ends just short of its table
GUTTER = 16  # right of the pages and under the last one: the columns' gap left of them


class SettingsDialog(QDialog):
    language_picked = Signal(str)
    theme_picked = Signal(str)
    start_picked = Signal(str)
    closing_picked = Signal(str)

    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        registry: themes.Registry,
        groups: Sequence[SettingsGroup] = (),
        tools: Sequence[ToolInfo] = (),
        start: str = settings.START_HOME,
        closing: str = settings.CLOSE_ASK,
    ) -> None:
        """tools: the window's tools; start: what the window shows at start; closing: what
        its X does."""
        super().__init__(parent)
        self._paths = paths
        self._registry = registry
        self._tools = list(tools)
        self._start = start
        self._closing = closing
        self._groups = list(groups)
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch (see DECISIONS, code cleanup).
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._build(themes.current().id)
        self.resize(860, 700)  # fixed: taller pages scroll, the window never grows for them

    def _build(self, theme_id: str) -> None:
        """The pages, in the current language, showing what's set."""
        self.setWindowTitle(_("Settings"))
        tools = [(t.tool_id, _(t.name)) for t in self._tools]
        self.general = GeneralPage(
            tools=tools,
            start=self._start,
            closing=self._closing,
            language=i18n.language(),
            registry=self._registry,
            theme_id=theme_id,
        )
        self.about = AboutPage(
            self._paths.log_dir, portable=self._paths.portable, paths=self._paths
        )
        self.pages: dict[str, Page] = {"general": self.general}
        # CapyPanel's page, then each tool's group: its label, then its pages.
        self._layout_groups: list[tuple[str, tuple[str, ...]]] = [APP_GROUP]
        for group in self._groups:
            built = group.build()
            self.pages.update(built)
            self._layout_groups.append((group.LABEL, tuple(page_id for page_id, _p in built)))
        self.pages["about"] = self.about
        self.general.changed.connect(self._start_changed)
        self.general.language.currentIndexChanged.connect(self._language_changed)
        self.general.theme.currentIndexChanged.connect(
            lambda: self.theme_picked.emit(self.general.theme_id())
        )

        # One scrolling view per page, and one for the search's results.
        self.stack = QStackedWidget()
        self._views: list[QScrollArea] = []
        self._view_of: dict[str, int] = {}  # page id -> its view
        for page_id, page in self.pages.items():
            self._view_of[page_id] = len(self._views)
            self._add_view(page)
        # Search results: the matching sections of every page, lent here while searching.
        self._results = Page(_("Search"))
        self._results_view = len(self._views)
        self._add_view(self._results)
        self._lent: list[tuple[QVBoxLayout, int, QWidget]] = []  # where each came from
        self._result_labels: list[QLabel] = []
        self._marks = search.SearchMarks(self._results)

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        # No setUniformItemSizes: it caches a row height measured before the theme reaches the
        # list, and the rows then overlap (13 px rows for 27 px of text).
        # Each group: its label (not picked), then its pages.
        self._rows: list[str | None] = []
        for group, ids in self._layout_groups:
            label = QListWidgetItem(_(group))
            label.setFlags(Qt.ItemFlag.NoItemFlags)  # never picked; _paint_labels colours it
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            self.page_list.addItem(label)
            self._rows.append(None)
            for page_id in ids:
                self.page_list.addItem("   " + self.pages[page_id].title)
                self._rows.append(page_id)
        # Wide enough for the longest name, so the list never cuts one off.
        metrics = self.page_list.fontMetrics()
        names = [self.page_list.item(r).text() for r in range(self.page_list.count())]  # type: ignore[union-attr]
        longest = max(
            [metrics.horizontalAdvance(name) for name in names]
            + [
                metrics.horizontalAdvance("   " + title)
                for message in (*self._labels(), *self._tool_titles(), "General", "About")
                for title in i18n.in_every_language(message)
            ]
        )
        self.page_list.setFixedWidth(longest + 64)
        self._paint_labels()
        self.page_list.currentRowChanged.connect(self._row_picked)
        # About stays at the very bottom, whatever pages the tools add above it.
        self.pinned_list = QListWidget()
        self.pinned_list.setObjectName("pageList")
        for page_id in PINNED:
            self.pinned_list.addItem("   " + self.pages[page_id].title)
        self.pinned_list.setFixedWidth(self.page_list.width())
        self.pinned_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit_pinned()
        self.pinned_list.currentRowChanged.connect(self._pinned_picked)
        self.page_list.setCurrentRow(self.row_of("general"))

        content = QWidget()
        columns = QHBoxLayout()
        columns.setSpacing(GUTTER)
        # A search above the pages: only the sections that mention what's typed stay listed.
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search settings"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(self.page_list.width())
        self.search.textChanged.connect(self._filter_pages)
        side = QVBoxLayout()
        side.addWidget(self.search)
        side.addWidget(self.page_list, 1)
        side.addWidget(self.pinned_list)
        columns.addLayout(side)
        divider = QFrame()  # a thin line between the page list and the pages
        divider.setObjectName("pagesDivider")
        divider.setFixedWidth(1)
        columns.addWidget(divider)
        columns.addWidget(self.stack, 1)
        inside = QVBoxLayout(content)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addLayout(columns, 1)
        self._layout.addWidget(content)
        self._content = content
        self._no_default_buttons()

    def _add_view(self, widget: QWidget) -> None:
        area = _scrolling(widget)
        self._views.append(area)
        self.stack.addWidget(area)

    def group[G: SettingsGroup](self, kind: type[G]) -> G:
        """A tool's group of pages, by its kind."""
        return next(g for g in self._groups if isinstance(g, kind))

    def credentials_changed(self) -> None:
        for group in self._groups:
            group.credentials_changed()

    def _labels(self) -> list[str]:
        return [label for label, _ids in self._layout_groups]

    def _tool_titles(self) -> list[str]:
        """The tools' page titles: with the labels, they keep the list as wide in every language."""
        return [title for group in self._groups for title in group.TITLES]

    def _paint_labels(self) -> None:
        """Group names in the text colour: rows that can't be picked would be greyed."""
        text = self.palette().color(QPalette.ColorRole.Text)
        for row, entry in enumerate(self._rows):
            item = self.page_list.item(row)
            if entry is None and item is not None:
                item.setForeground(text)

    def _start_changed(self) -> None:
        if self.general.start_choice() != self._start:
            self._start = self.general.start_choice()
            self.start_picked.emit(self._start)
        if self.general.closing_choice() != self._closing:
            self._closing = self.general.closing_choice()
            self.closing_picked.emit(self._closing)

    def _language_changed(self) -> None:
        code = self.general.language_choice()
        if code != i18n.language():
            self.language_picked.emit(code)  # the app switches now; Settings follows
            QTimer.singleShot(0, self, self._rebuild)  # after the dropdown has closed

    def _rebuild(self) -> None:
        """The same window in the new language, on the same page."""
        page = self._shown_page()  # not "search": the rebuilt window opens without one
        for group in self._groups:
            group.before_rebuild()
        old = self._content
        old.hide()
        self._layout.removeWidget(old)
        self._old.append(old)
        self._build(self.general.theme_id())
        for group in self._groups:
            group.after_rebuild()
        self.show_page(page)
        self._make_room()
        self.general.language.setFocus()

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):  # the pages' buttons too
            button.setAutoDefault(False)
            button.setDefault(False)

    # ---- picking ----

    def _row_picked(self, row: int) -> None:
        page_id = self._rows[row] if 0 <= row < len(self._rows) else None
        if page_id is None:
            return  # a group's label, never picked
        self._unpick(self.pinned_list)
        self._leave_search()
        self._show_view(page_id)

    def _pinned_picked(self, row: int) -> None:
        if 0 <= row < len(PINNED):
            self._unpick(self.page_list)
            self._leave_search()
            self._show_view(PINNED[row])

    def _show_view(self, page_id: str) -> None:
        """The page on its own, from its top."""
        view = self._views[self._view_of[page_id]]
        self.stack.setCurrentWidget(view)
        view.verticalScrollBar().setValue(0)

    def _leave_search(self) -> None:
        if self._lent:  # picking ends the search: its sections go home first
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._end_search()

    @staticmethod
    def _unpick(pages: QListWidget) -> None:
        """One row is picked across both lists: the other list shows none."""
        pages.blockSignals(True)
        pages.setCurrentRow(-1)
        pages.blockSignals(False)

    def _fit_pinned(self) -> None:
        """Just tall enough for its rows, measured once the theme's padding is in."""
        rows = sum(self.pinned_list.sizeHintForRow(r) for r in range(self.pinned_list.count()))
        frame = 2 * self.pinned_list.frameWidth()
        self.pinned_list.setFixedHeight(rows + frame + 2)

    # ---- search ----

    def _place_name(self, page_id: str) -> str:
        """Where a page is, as the search's results name it: "Hosts › Connecting", "About"."""
        page = self.pages[page_id]
        if page_id in PINNED:
            return page.title
        group = next(label for label, ids in self._layout_groups if page_id in ids)
        return f"{_(group)} › {page.title}"

    def _filter_pages(self, text: str) -> None:
        """From SEARCH_FROM letters on: every section that mentions `text` at the start of a
        word, from every page, on one results page, each page's under its name, to change right
        there, with each match marked. The page list keeps only the pages with a match. Fewer
        letters: back to the page as it was."""
        page = self._shown_page()
        self._end_search()
        wanted = text.strip().casefold()
        if len(wanted) < SEARCH_FROM:
            self.show_page(page)
            return
        found: list[Section] = []
        matched: set[str] = set()  # the pages with a match
        layout = self._results.body
        for page_id, source in self.pages.items():
            sections = [s for s in _sections(source) if search.mentions(s, wanted)]
            if not sections:
                continue
            matched.add(page_id)
            where = hint(self._place_name(page_id))
            self._result_labels.append(where)
            layout.addWidget(where)
            for section in sections:
                found.append(section)
                self._lent.append((source.body, source.body.indexOf(section), section))
                source.body.removeWidget(section)
                layout.addWidget(section)
        if not found:
            nothing = hint(_("No settings mention “{text}”.").format(text=text.strip()))
            self._result_labels.append(nothing)
            layout.addWidget(nothing)
        layout.addStretch(1)
        marked: list[QWidget] = [*found]
        self._marks.mark(marked, wanted)
        for row, entry in enumerate(self._rows):
            if entry is not None:
                self.page_list.setRowHidden(row, entry not in matched)
        for row, entry in enumerate(self._rows):  # a group's label: hidden with its pages
            if entry is None:
                after = self._rows[row + 1 :]
                end = after.index(None) if None in after else len(after)
                shown = any(e is not None and e in matched for e in after[:end])
                self.page_list.setRowHidden(row, not shown)
        for row, page_id in enumerate(PINNED):
            self.pinned_list.setRowHidden(row, page_id not in matched)
        for pages in (self.page_list, self.pinned_list):
            self._unpick(pages)
        self._before_search = page
        self.stack.setCurrentIndex(self._results_view)

    def _end_search(self) -> None:
        """Sends the lent sections back to their pages, where they were, and lists every row."""
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
        for pages in (self.page_list, self.pinned_list):
            for row in range(pages.count()):
                pages.setRowHidden(row, False)

    # ---- which page ----

    def _shown_page(self) -> str:
        """The page shown, or the one shown before the search."""
        current = self.current_page()
        return current if current != "search" else getattr(self, "_before_search", "general")

    def show_page(self, page_id: str) -> None:
        """Picks the page in the page list, which shows it; About is picked on its own."""
        if page_id in PINNED:
            self.pinned_list.setCurrentRow(PINNED.index(page_id))
        else:
            self.page_list.setCurrentRow(self.row_of(page_id))

    def row_of(self, page_id: str) -> int:
        """The page's row in the page list."""
        return self._rows.index(page_id)

    def current_page(self) -> str:
        """The page picked; "about", or "search" while results are shown."""
        if self.stack.currentIndex() == self._results_view:
            return "search"
        if self.pinned_list.currentRow() >= 0:
            return PINNED[self.pinned_list.currentRow()]
        row = self.page_list.currentRow()
        entry = self._rows[row] if 0 <= row < len(self._rows) else None
        return entry if entry is not None else "general"

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "page_list"):
            self._paint_labels()  # a theme switch

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_pinned()  # the theme's row padding is known now
        self._make_room()
        themes.paint_title_bar(self)
        self._no_default_buttons()

    def _make_room(self) -> None:
        """At least ROOM wider than the widest page needs, in this language."""
        width = self.minimumSizeHint().width() + ROOM
        if self.width() < width:
            self.resize(width, self.height())


def _sections(page: Page) -> list[Section]:
    """The page's sections, in order: the ones lent to the search's results aren't there."""
    parts = (page.body.itemAt(i) for i in range(page.body.count()))
    return [w for part in parts if part is not None and isinstance(w := part.widget(), Section)]


class _PageArea(QScrollArea):
    """Never narrower than its page: the window widens instead of cutting off a button row."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        page = self.widget()
        if page is None:
            return hint
        bar = self.verticalScrollBar().sizeHint().width()
        return QSize(max(hint.width(), page.minimumSizeHint().width() + bar), hint.height())


def _scrolling(widget: QWidget) -> QScrollArea:
    """A page that scrolls when it's taller than the window, with no frame of its own. A
    gutter keeps the cards off the scroll bar and the bottom edge, as wide as the gap left of
    them."""
    area = _PageArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, GUTTER, GUTTER)
    layout.addWidget(widget)
    area.setWidget(holder)
    return area
