from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QItemSelectionModel, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
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
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.i18n import _
from capypanel.ui import help_links, keyboard
from capypanel.ui.notes import hint
from capypanel.ui.settings import search
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import GeneralPage, Page, Section
from capypanel.ui.settings.shortcuts_page import ShortcutsPage
from capypanel.ui.shortcuts import Keys
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import ToolInfo

APP_GROUP = ("CapyPanel", ("general",))
PINNED = ("about",)
SEARCH_FROM = 3
# Room for a domain account's row, and every page listed in Windows' taller-row themes.
WIDTH, HEIGHT = 960, 740
ROOM = 60  # spare width past the widest page: a button row never ends just short of its table
GUTTER = 16


class SettingsDialog(QDialog):
    language_picked = Signal(str)
    theme_picked = Signal(str)
    start_picked = Signal(str)
    closing_picked = Signal(str)
    updates_picked = Signal(str)
    updates_requested = Signal()

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
        updates: str = "start",
        updates_editable: bool = True,
        keys: Keys | None = None,
        place_names: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._registry = registry
        self._tools = list(tools)
        self._start = start
        self._closing = closing
        self._updates, self._updates_editable = updates, updates_editable
        self._groups = list(groups)
        self._keys, self._place_names = keys, dict(place_names or {})
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch.
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.own_size = False
        self._build(themes.current().id)
        self.resize(WIDTH, HEIGHT)

    def _build(self, theme_id: str) -> None:
        self.setWindowTitle(_("Settings"))
        tools = [(t.tool_id, _(t.name)) for t in self._tools]
        self.general = GeneralPage(
            tools=tools,
            start=self._start,
            closing=self._closing,
            updates=self._updates,
            updates_editable=self._updates_editable,
            language=i18n.language(),
            registry=self._registry,
            theme_id=theme_id,
        )
        from capypanel.ui.about import AboutPage

        self.about = AboutPage(
            self._paths.log_dir, portable=self._paths.portable, paths=self._paths
        )
        self.pages: dict[str, Page] = {"general": self.general}
        app_pages = list(APP_GROUP[1])
        if self._keys is not None:
            self.shortcuts = ShortcutsPage(self._keys, self._place_names)
            self.pages["shortcuts"] = self.shortcuts
            app_pages.append("shortcuts")
        self._layout_groups: list[tuple[str, tuple[str, ...]]] = [(APP_GROUP[0], tuple(app_pages))]
        for group in self._groups:
            built = group.build()
            self.pages.update(built)
            self._layout_groups.append((group.LABEL, tuple(page_id for page_id, _p in built)))
        self.pages["about"] = self.about
        self.general.changed.connect(self._start_changed)
        self.general.language.currentIndexChanged.connect(self._language_changed)
        self.general.theme.currentIndexChanged.connect(self._theme_changed)

        self.stack = QStackedWidget()
        self._views: list[_PageArea] = []
        self._view_of: dict[str, int] = {}
        for page_id, page in self.pages.items():
            self._view_of[page_id] = len(self._views)
            self._add_view(page)
        self._results = Page(_("Search"), place="settings-find-a-setting")
        self._results_view = len(self._views)
        self._add_view(self._results)
        self._lent: list[tuple[QVBoxLayout, int, QWidget]] = []
        self._result_labels: list[QLabel] = []
        self._marks = search.SearchMarks(self._results)

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
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
        metrics = self.page_list.fontMetrics()
        names = [self.page_list.item(r).text() for r in range(self.page_list.count())]  # type: ignore[union-attr]
        longest = max(
            [metrics.horizontalAdvance(name) for name in names]
            + [
                metrics.horizontalAdvance("   " + title)
                for message in (
                    *self._labels(),
                    *self._tool_titles(),
                    "General",
                    "About",
                    "Keyboard shortcuts",
                )  # fmt: skip
                for title in i18n.in_every_language(message)
            ]
        )
        self.page_list.setFixedWidth(longest + 64)
        self._paint_labels()
        self.page_list.itemSelectionChanged.connect(self._row_picked)
        self.pinned_list = QListWidget()
        self.pinned_list.setObjectName("pageList")
        for page_id in PINNED:
            self.pinned_list.addItem("   " + self.pages[page_id].title)
        self.pinned_list.setFixedWidth(self.page_list.width())
        self.pinned_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._fit_pinned()
        self.pinned_list.itemSelectionChanged.connect(self._pinned_picked)

        content = QWidget()
        columns = QHBoxLayout()
        columns.setSpacing(GUTTER)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search settings"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(self.page_list.width())
        self.search.textChanged.connect(self._filter_pages)
        side = QVBoxLayout()
        side.addWidget(self.search)
        side.addWidget(self.page_list, 1)
        side.addWidget(self.pinned_list)
        self.help_button = help_links.HelpButton(self.help_place)
        side.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._page_id = "general"
        self._column = _SideColumn(self.page_list, self.pinned_list, self.help_button, self._entry)
        self.page_list.setCurrentRow(self.row_of("general"))
        columns.addLayout(side)
        divider = QFrame()
        divider.setObjectName("pagesDivider")
        divider.setFixedWidth(1)
        columns.addWidget(divider)
        columns.addWidget(self.stack, 1)
        inside = QVBoxLayout(content)
        inside.setContentsMargins(12, 12, 12, 12)
        inside.addLayout(columns, 1)
        self._layout.addWidget(content)
        self._content = content
        self._no_default_buttons()

    def _add_view(self, widget: QWidget) -> None:
        area = _scrolling(widget)
        self._views.append(area)
        self.stack.addWidget(area)

    def group[G: SettingsGroup](self, kind: type[G]) -> G:
        return next(g for g in self._groups if isinstance(g, kind))

    def credentials_changed(self) -> None:
        for group in self._groups:
            group.credentials_changed()

    def _labels(self) -> list[str]:
        return [label for label, _ids in self._layout_groups]

    def _tool_titles(self) -> list[str]:
        return [title for group in self._groups for title in group.TITLES]

    def _paint_labels(self) -> None:
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
        if self.general.updates_choice() != self._updates:
            self._updates = self.general.updates_choice()
            self.updates_picked.emit(self._updates)

    def show_updates(self, how: str) -> None:
        self._updates = how
        self.general.show_updates(how)

    def _theme_changed(self) -> None:
        QTimer.singleShot(0, self, lambda: self.theme_picked.emit(self.general.theme_id()))

    def _language_changed(self) -> None:
        code = self.general.language_choice()
        if code != i18n.language():
            self.language_picked.emit(code)
            QTimer.singleShot(0, self, self._rebuild)

    def _rebuild(self) -> None:
        page = self._shown_page()
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
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _row_picked(self) -> None:
        row = _picked_row(self.page_list)
        page_id = self._rows[row] if 0 <= row < len(self._rows) else None
        if page_id is None:
            return
        self._unpick(self.pinned_list)
        self._leave_search()
        self._show_view(page_id)

    def _pinned_picked(self) -> None:
        row = _picked_row(self.pinned_list)
        if 0 <= row < len(PINNED):
            self._unpick(self.page_list)
            self._leave_search()
            self._show_view(PINNED[row])

    def _show_view(self, page_id: str) -> None:
        self._page_id = page_id
        view = self._views[self._view_of[page_id]]
        self.stack.setCurrentWidget(view)
        view.verticalScrollBar().setValue(0)
        self._column.stop.settle()

    def _entry(self) -> QWidget:
        pinned = self._page_id in PINNED and self.stack.currentIndex() != self._results_view
        return self.pinned_list if pinned else self.page_list

    def _leave_search(self) -> None:
        if self._lent:
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._end_search()

    @staticmethod
    def _unpick(pages: QListWidget) -> None:
        pages.blockSignals(True)
        pages.clearSelection()
        pages.setCurrentRow(-1)
        pages.blockSignals(False)

    def _fit_pinned(self) -> None:
        rows = sum(self.pinned_list.sizeHintForRow(r) for r in range(self.pinned_list.count()))
        frame = 2 * self.pinned_list.frameWidth()
        self.pinned_list.setFixedHeight(rows + frame + 2)

    def _place_name(self, page_id: str) -> str:
        page = self.pages[page_id]
        if page_id in PINNED:
            return page.title
        group = next(label for label, ids in self._layout_groups if page_id in ids)
        return f"{_(group)} › {page.title}"

    def _filter_pages(self, text: str) -> None:
        page = self._shown_page()
        self._end_search()
        wanted = text.strip().casefold()
        if len(wanted) < SEARCH_FROM:
            self.show_page(page)
            return
        found: list[Section] = []
        matched: set[str] = set()
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
        for row, entry in enumerate(self._rows):
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
        while layout.count() > 0:
            layout.takeAt(0)
        for pages in (self.page_list, self.pinned_list):
            for row in range(pages.count()):
                pages.setRowHidden(row, False)

    def _shown_page(self) -> str:
        current = self.current_page()
        return current if current != "search" else getattr(self, "_before_search", "general")

    def show_page(self, page_id: str) -> None:
        if page_id in PINNED:
            self.pinned_list.setCurrentRow(PINNED.index(page_id))
        else:
            self.page_list.setCurrentRow(self.row_of(page_id))

    def help_place(self) -> str:
        page = self.current_page()
        shown = self._results if page == "search" else self.pages.get(page)
        return (shown.place if shown is not None else "") or "settings-and-files/"

    def row_of(self, page_id: str) -> int:
        return self._rows.index(page_id)

    def current_page(self) -> str:
        if self.stack.currentIndex() == self._results_view:
            return "search"
        return self._page_id

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "page_list"):
            self._paint_labels()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_pinned()
        self._make_room()
        themes.paint_title_bar(self)
        self._no_default_buttons()

    def _make_room(self) -> None:
        if self.own_size:
            return
        around = self.minimumSizeHint().width() - self.stack.minimumSizeHint().width()
        width = around + max(view.page_width() for view in self._views) + ROOM
        if self.width() < width:
            self.resize(width, self.height())


def _sections(page: Page) -> list[Section]:
    parts = (page.body.itemAt(i) for i in range(page.body.count()))
    return [w for part in parts if part is not None and isinstance(w := part.widget(), Section)]


class _PageArea(QScrollArea):
    def page_width(self) -> int:
        page = self.widget()
        bar = self.verticalScrollBar().sizeHint().width()
        return (page.minimumSizeHint().width() if page is not None else 0) + bar


def _picked_row(pages: QListWidget) -> int:
    picked = pages.selectionModel().selectedIndexes()
    return picked[0].row() if picked else -1


class _SideColumn(QObject):
    MOVES = frozenset({
        Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End,
        Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
    })  # fmt: skip
    OPENS = frozenset({Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space})

    def __init__(
        self,
        pages: QListWidget,
        pinned: QListWidget,
        help_button: QToolButton,
        entry: Callable[[], QWidget],
    ) -> None:
        super().__init__(pages)
        self._lists = (pages, pinned)
        self._help = help_button
        self.stop = keyboard.OneStop([pages, pinned, help_button], entry)
        for member in (pages, pinned, help_button):
            member.installEventFilter(self)

    def places(self) -> list[tuple[QWidget, int]]:
        found: list[tuple[QWidget, int]] = []
        for pages in self._lists:
            for row in range(pages.count()):
                item = pages.item(row)
                enabled = item is not None and item.flags() & Qt.ItemFlag.ItemIsEnabled
                if enabled and not pages.isRowHidden(row):
                    found.append((pages, row))
        return [*found, (self._help, -1)]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self, self._left)
            return False
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            return False
        key = Qt.Key(event.key())
        if key in self.MOVES and isinstance(watched, QWidget):
            self._move(watched, key)
            return True
        if key in self.OPENS and isinstance(watched, QListWidget) and watched.currentRow() >= 0:
            watched.setCurrentRow(watched.currentRow())
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and watched is self._help:
            self._help.click()
            return True
        return False

    def _move(self, watched: QWidget, key: Qt.Key) -> None:
        places = self.places()
        row = watched.currentRow() if isinstance(watched, QListWidget) else -1
        here = places.index((watched, row)) if (watched, row) in places else -1
        last = len(places) - 1
        to = {
            Qt.Key.Key_Up: max(here - 1, 0),
            Qt.Key.Key_Down: min(here + 1, last),
            Qt.Key.Key_Home: 0,
            Qt.Key.Key_PageUp: 0,
        }.get(key, last)
        widget, row = places[to]
        if isinstance(widget, QListWidget):
            _point_at(widget, row)
        widget.setFocus(Qt.FocusReason.OtherFocusReason)

    def _left(self) -> None:
        focus = QApplication.focusWidget()
        if focus in (*self._lists, self._help):
            return
        for pages in self._lists:
            _point_at(pages, _picked_row(pages))


def _point_at(pages: QListWidget, row: int) -> None:
    index = pages.model().index(row, 0)
    pages.selectionModel().setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)


def _scrolling(widget: QWidget) -> _PageArea:
    area = _PageArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    keyboard.tab_stop_while_it_scrolls(area)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, GUTTER, GUTTER)
    layout.addWidget(widget)
    area.setWidget(holder)
    return area
