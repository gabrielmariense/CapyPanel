"""The Settings window: a search and a list of pages on the left, the page on the right. No
buttons: the window's X or Esc closes it, and every choice applies as soon as it's made. The app's
own pages come first (General, Appearance, Files), then each tool's group of pages, and About at
the very bottom. A tool's pages apply their choices through the tool (see SettingsGroup)."""

from collections.abc import Collection, Sequence

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QShowEvent
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
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import hint
from capypanel.ui.settings import search
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import AppearancePage, FilesPage, GeneralPage, Page, Section
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import ToolInfo
from capypanel.ui.tool_switches import ToolsDialog

# The app's own pages' titles, as the pages set them: with the tools' titles and the groups'
# labels, the page list is sized for the longest in any language.
PAGE_TITLES = ("General", "Appearance", "Files", "About")
APP_GROUP = ("CapyPanel", ("general", "appearance", "files"))
PINNED = ("about",)  # pages kept at the very bottom of the page list, apart from the groups
SEARCH_FROM = 3  # letters typed before the search shows its results
ROOM = 60  # spare width past the widest page: a button row never ends just short of its table


class SettingsDialog(QDialog):
    language_picked = Signal(str)
    theme_picked = Signal(str)
    start_picked = Signal(str)
    restart_picked = Signal(list)  # the ids of the tools to turn off, then restart

    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        registry: themes.Registry,
        groups: Sequence[SettingsGroup] = (),
        tools: Sequence[ToolInfo] = (),
        tools_on: Collection[str] = (),
        start: str = settings.START_HOME,
    ) -> None:
        """tools: every tool CapyPanel has; tools_on: the ids of those on; start: what the
        window shows at start."""
        super().__init__(parent)
        self._paths = paths
        self._registry = registry
        self._tools = list(tools)
        self._tools_on = set(tools_on)
        self._start = start
        self._groups = list(groups)
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch (see DECISIONS, code cleanup).
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._build(themes.current().id)
        self.resize(860, 700)  # fixed: taller pages scroll, the window never grows for them

    def _build(self, theme_id: str) -> None:
        """The pages and buttons, in the current language, showing what's set."""
        self.setWindowTitle(_("Settings"))
        on = [(t.tool_id, _(t.name)) for t in self._tools if t.tool_id in self._tools_on]
        self.general = GeneralPage(tools=on, start=self._start)
        self.appearance = AppearancePage(
            language=i18n.language(), registry=self._registry, theme_id=theme_id
        )
        self.files = FilesPage(self._paths)
        self.about = AboutPage(self._paths.log_dir, portable=self._paths.portable)
        self.pages: dict[str, Page] = {
            "general": self.general,
            "appearance": self.appearance,
            "files": self.files,
            "about": self.about,
        }
        # The app's pages, then each tool's group: its label (not a page), then its pages.
        self._layout_groups: list[tuple[str, tuple[str, ...]]] = [APP_GROUP]
        for group in self._groups:
            built = group.build()
            self.pages.update(built)
            self._layout_groups.append((group.LABEL, tuple(page_id for page_id, _p in built)))
        self.general.changed.connect(self._start_changed)
        self.general.choose_tools.clicked.connect(self._choose_tools)
        self.appearance.language.currentIndexChanged.connect(self._language_changed)
        self.appearance.theme.currentIndexChanged.connect(
            lambda: self.theme_picked.emit(self.appearance.theme_id())
        )

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        # No setUniformItemSizes: it caches a row height measured before the theme reaches the
        # list, and the rows then overlap (13 px rows for 27 px of text).
        self.stack = QStackedWidget()
        # Each group: its label (not a page), then its pages. _rows maps rows to page ids.
        self._rows: list[str | None] = []
        for group, ids in self._layout_groups:
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
            for message in (*PAGE_TITLES, *self._tool_titles(), *self._labels())
            for title in i18n.in_every_language(message)
        )
        self.page_list.setFixedWidth(longest + 64)
        self.page_list.currentRowChanged.connect(self._page_picked)
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

    def group[G: SettingsGroup](self, kind: type[G]) -> G:
        """A tool's group of pages, by its kind."""
        return next(g for g in self._groups if isinstance(g, kind))

    def _labels(self) -> list[str]:
        return [label for label, _ids in self._layout_groups]

    def _tool_titles(self) -> list[str]:
        return [title for group in self._groups for title in group.TITLES]

    def _start_changed(self) -> None:
        self._start = self.general.start_choice()
        self.start_picked.emit(self._start)

    def _choose_tools(self) -> None:
        """The Tools window; its Restart CapyPanel hands the choice on."""
        dialog = ToolsDialog(self, tools=self._tools, on=self._tools_on)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self.restart_picked.emit(dialog.off())

    def _language_changed(self) -> None:
        code = self.appearance.language_choice()
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
        self._build(self.appearance.theme_id())
        for group in self._groups:
            group.after_rebuild()
        self.show_page(page)
        self._make_room()
        self.appearance.language.setFocus()

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):  # the pages' buttons too
            button.setAutoDefault(False)
            button.setDefault(False)

    def _page_picked(self, row: int) -> None:
        page_id = self._rows[row] if 0 <= row < len(self._rows) else None
        if page_id is None:
            return  # a group's label, never picked
        self._unpick(self.pinned_list)
        self._show(page_id)

    def _pinned_picked(self, row: int) -> None:
        if 0 <= row < len(PINNED):
            self._unpick(self.page_list)
            self._show(PINNED[row])

    def _show(self, page_id: str) -> None:
        if self._lent:  # picking a page ends the search: its sections go home first
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._end_search()
        self.stack.setCurrentIndex(list(self.pages).index(page_id))

    @staticmethod
    def _unpick(pages: QListWidget) -> None:
        """One page is picked across both lists: the other list shows none."""
        pages.blockSignals(True)
        pages.setCurrentRow(-1)
        pages.blockSignals(False)

    def _fit_pinned(self) -> None:
        """Just tall enough for its rows, measured once the theme's padding is in."""
        rows = sum(self.pinned_list.sizeHintForRow(r) for r in range(self.pinned_list.count()))
        frame = 2 * self.pinned_list.frameWidth()
        self.pinned_list.setFixedHeight(rows + frame + 2)

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
        group_of = {pid: group for group, ids in self._layout_groups for pid in ids}
        group_of.update(dict.fromkeys(PINNED, "CapyPanel"))  # About is the app's own
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
        for row, page_id in enumerate(PINNED):
            self.pinned_list.setRowHidden(row, page_id not in shown)
        for pages in (self.page_list, self.pinned_list):
            self._unpick(pages)
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
        for pages in (self.page_list, self.pinned_list):
            for row in range(pages.count()):
                pages.setRowHidden(row, False)

    def _shown_page(self) -> str:
        """The page shown, or the one shown before the search."""
        if self.stack.currentIndex() < len(self.pages):
            return list(self.pages)[self.stack.currentIndex()]
        return getattr(self, "_before_search", "general")

    def show_page(self, page_id: str) -> None:
        if page_id in PINNED:
            self.pinned_list.setCurrentRow(PINNED.index(page_id))
        else:
            self.page_list.setCurrentRow(self.row_of(page_id))

    def row_of(self, page_id: str) -> int:
        return self._rows.index(page_id)

    def current_page(self) -> str:
        """The page shown; "search" while the search's results are."""
        index = self.stack.currentIndex()
        return list(self.pages)[index] if index < len(self.pages) else "search"

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
