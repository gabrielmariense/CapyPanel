from typing import ClassVar

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from capypanel.ui.list_workspace.splitter import PaneSplitter
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.tab_strip import PINNED, TabStrip

PANES_KEY = "pane_widths"


class TabbedListWorkspace(ListWorkspace):
    TABS_ICON: ClassVar[str] = ""
    tabs: TabStrip
    pages: QStackedWidget
    inner: PaneSplitter

    def _lay_out(self) -> None:
        self.inner = PaneSplitter()
        self.inner.addWidget(self.items_pane)
        self.inner.addWidget(self.details)
        self.inner.setStretchFactor(0, 1)
        self.inner.setChildrenCollapsible(False)
        self.tabs = TabStrip(self.TABS_ICON)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.inner)
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.tabs)
        column.addWidget(self.pages, 1)
        self.splitter.addWidget(self.nav)
        self.splitter.addWidget(area)
        self.splitter.setStretchFactor(1, 1)
        self.inner.edge_double_clicked.connect(lambda edge: self._fit_pane(edge, self.inner))
        self.tabs.picked.connect(self.switch)
        self.tabs.close_requested.connect(self.close_tab)
        self.tabs.menu_requested.connect(self.tab_menu)
        for keys, run in (
            ("Ctrl+Tab", lambda: self.step(1)),
            ("Ctrl+Shift+Tab", lambda: self.step(-1)),
            ("Ctrl+Shift+W", lambda: self.close_tab(self.tabs.current())),
        ):
            shortcut = QShortcut(QKeySequence(keys), self, run)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.fit_tabs()

    def _default_pane_sizes(self, total: int) -> None:
        groups, details = (round(w * self._scale()) for w in self.PANES_DEFAULT)
        details = max(details, self.details.minimum_width())
        self._set_pane_widths(groups, details, total)

    def _set_pane_widths(self, groups: int, details: int, total: int = 1100) -> None:
        self.splitter.setSizes([groups, max(total - groups, 1)])
        self.inner.setSizes([max(total - groups - details, 1), details])

    def _restore_panes(self) -> None:
        widths = self.prefs.get(PANES_KEY)
        if (
            isinstance(widths, list)
            and len(widths) == 2
            and all(isinstance(w, int) and not isinstance(w, bool) and w > 0 for w in widths)
        ):
            self._set_pane_widths(widths[0], widths[1])

    def _save_panes(self) -> None:
        outer, inner = self.splitter.sizes(), self.inner.sizes()
        if len(outer) == 2 and len(inner) == 2 and outer[0] and inner[1]:
            self.prefs[PANES_KEY] = [outer[0], inner[1]]

    def fit_tabs(self) -> None:
        self.tabs.set_height(self.nav.card_top())

    def restyle(self) -> None:
        super().restyle()
        self.tabs.restyle()
        self.fit_tabs()

    def add_page(self, key: str, page: QWidget, text: str) -> None:
        self.pages.addWidget(page)
        self.tabs.add(key, text)

    def remove_page(self, key: str, page: QWidget) -> None:
        keys = self.tabs.tab_keys()
        index = keys.index(key) if key in keys else 0
        was_current = self.tabs.current() == key
        self.tabs.remove(key)
        self.pages.removeWidget(page)
        if was_current:
            left = self.tabs.tab_keys()
            self.switch(left[index - 1] if index > 0 and left else PINNED)

    def switch(self, key: str) -> None:
        page = self.page_of(key) if key != PINNED else None
        self.tabs.set_current(key if page is not None else PINNED)
        self.pages.setCurrentWidget(page if page is not None else self.inner)

    def step(self, by: int) -> None:
        keys = [PINNED, *self.tabs.tab_keys()]
        index = keys.index(self.tabs.current()) if self.tabs.current() in keys else 0
        self.switch(keys[(index + by) % len(keys)])

    def list_to_front(self) -> None:
        if self.tabs.current() != PINNED:
            self.switch(PINNED)

    def page_of(self, key: str) -> QWidget | None:
        raise NotImplementedError

    def close_tab(self, key: str) -> bool:
        raise NotImplementedError

    def tab_menu(self, key: str, where: QPoint) -> None:
        pass
