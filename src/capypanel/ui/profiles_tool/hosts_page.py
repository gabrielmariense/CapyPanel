"""The User profiles tool's pinned Hosts tab: the hosts of the group picked on the left and what
each scan found so far; on the right, its card (side.HostCard): the host picked, or the hosts on
show. It never scans by itself: a double-click, Enter or Scan opens a host."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, pgettext
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.panels import SearchBox, natural_key
from capypanel.ui.profiles_tool.panels import Squeeze, TabBox, hint
from capypanel.ui.profiles_tool.side import GroupFacts, HostCard, HostFacts
from capypanel.ui.tables import grid_table

NAME, ADDRESS, STATUS, PROFILES, DELETABLE, SCAN = range(6)  # the table's columns
ID_ROLE = Qt.ItemDataRole.UserRole  # the row's host
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
RIGHT_ALIGNED = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


@dataclass(frozen=True)
class RowFacts:
    """What the Hosts tab shows of one host beside its name and address."""

    status: str  # "Online", or "Not checked"
    status_color: str  # its dot; "" for none
    status_tip: str  # when Hosts checked it
    profiles: int | None  # once scanned
    deletable: int | None
    scan: str  # "10:41", "scanning…", "didn't answer", or ""
    scan_time: float | None  # what the Scan column sorts by
    scan_color: str  # "" for the text's own colour


class _Row(QTreeWidgetItem):
    """Sorts by what a cell means. The Scan column goes by time, the hosts with no time after
    the others whichever way it's sorted; ties stay in name order."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else NAME
        down = tree is not None and (
            tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        )
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if column == SCAN and (mine is None) != (theirs is None):
            return (mine is None) == down  # no time: last, both ways
        if mine == theirs:
            names = self.data(NAME, SORT_ROLE), other.data(NAME, SORT_ROLE)
            return bool(names[1] < names[0]) if down else bool(names[0] < names[1])
        return bool(mine < theirs)


class HostsTable(QWidget):
    """The hosts of the group picked. No tick column: picking rows is enough. Double-click or
    Enter opens a host's tab and goes to it; a middle-click or Ctrl+Enter opens it behind."""

    open_requested = Signal(list, bool)  # host ids, and whether to go to the tab
    picked = Signal()
    menu_requested = Signal(QPoint)  # a right-click on a host: where (global)
    scan_typed = Signal(str)  # "Scan 192.0.2.50" in the empty table

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 6)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setStretchLastSection(True)
        # At a narrow width Name gives up room first; Scan, the last one, stays whole.
        self.squeeze = Squeeze(self.tree, ((NAME, 90), (ADDRESS, 80)), self._scan_least)
        self.squeeze.narrowed.connect(lambda _narrow: self._title_deletable())
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(NAME, Qt.SortOrder.AscendingOrder)
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemDoubleClicked.connect(lambda *_a: self._open(True))
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self._fitted = False
        # The empty table's note, when a search finds no host of the list.
        self._empty = QWidget(self.tree.viewport())
        self._empty_text = QLabel()
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.scan_button = QPushButton()
        self.scan_button.setAutoDefault(False)
        self.scan_button.clicked.connect(lambda: self.scan_typed.emit(self._typed))
        self._empty_hint = hint()
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        column = QVBoxLayout(self._empty)
        column.addWidget(self._empty_text)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.scan_button)
        row.addStretch(1)
        column.addLayout(row)
        column.addWidget(self._empty_hint)
        self._empty.hide()
        self._typed = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.retranslate()

    def retranslate(self) -> None:
        self.tree.setHeaderLabels(
            [
                _("Name"),
                _("Address"),
                _("Status"),
                _("Profiles"),
                _("Can be deleted"),
                pgettext("column", "Scan"),
            ]  # fmt: skip
        )
        self._title_deletable()
        header = self.tree.headerItem()
        header.setToolTip(PROFILES, _("Profiles found by the last scan"))
        header.setToolTip(DELETABLE, _("Profiles the last scan found that can be deleted"))
        header.setToolTip(SCAN, _("When the host was scanned, or where its scan is"))
        self._empty_hint.setText(_("Opens the host in a new tab. Typing alone never scans."))
        self.show_typed(self._typed)

    def _title_deletable(self) -> None:
        """ "Can be deleted", or one short word while the columns don't fit at full width;
        the tooltip has the whole phrase either way."""
        narrow = self.squeeze.is_narrow()
        self.tree.headerItem().setText(DELETABLE, _("Deletable") if narrow else _("Can be deleted"))

    def _scan_least(self) -> int:
        """Scan's width for its longest words, so where a host stands is never cut."""
        words = [
            _("deleting {n} of {total}").format(n=99, total=99),
            _("account refused"),
            _("didn't answer"),
            _("couldn't be read"),
            pgettext("column", "Scan"),
        ]
        metrics = self.tree.fontMetrics()
        return max(metrics.horizontalAdvance(word) for word in words) + 24

    def show_hosts(self, hosts: Sequence[Host], facts: Callable[[Host], RowFacts]) -> None:
        kept = set(self.selected_ids())
        self.tree.setSortingEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        for host in hosts:
            item = _Row()
            item.setData(NAME, ID_ROLE, host.id)
            item.setText(NAME, host.name)
            item.setToolTip(NAME, host.name)  # whole, when the column is narrow
            item.setData(NAME, SORT_ROLE, natural_key(host.name))
            item.setText(ADDRESS, host.address)
            item.setData(ADDRESS, SORT_ROLE, natural_key(host.address))
            self.tree.addTopLevelItem(item)
            self._fill(item, facts(host))
            item.setSelected(host.id in kept)
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        if not self._fitted and hosts:
            self._fit()
        self.picked.emit()

    def show_facts(self, host_id: str, facts: RowFacts) -> None:
        item = self._item(host_id)
        if item is not None:
            self._fill(item, facts)

    def show_typed(self, typed: str) -> None:
        """The empty table's note for a search that found nothing; "" hides it."""
        self._typed = typed
        if typed:
            self._empty_text.setText(_("No host of the list with “{text}”.").format(text=typed))
            self.scan_button.setText(_("Scan {host}").format(host=typed))
        self._empty.setVisible(bool(typed))
        self._place_empty()

    def selected_ids(self) -> list[str]:
        """The rows picked, in the order on screen."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [i.data(NAME, ID_ROLE) for i in found if i is not None and i.isSelected()]

    def select(self, host_id: str) -> None:
        item = self._item(host_id)
        if item is not None:
            self.tree.setCurrentItem(item)

    def texts(self) -> list[list[str]]:
        """Every row's cells, in the order on screen (for tests)."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [[item.text(c) for c in range(SCAN + 1)] for item in found if item]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and watched is self.tree.viewport():
            self._place_empty()
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and watched is self.tree.viewport()
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.MiddleButton
        ):
            item = self.tree.itemAt(event.position().toPoint())
            if item is not None:
                self.open_requested.emit([item.data(NAME, ID_ROLE)], False)
                return True
        if (
            event.type() == QEvent.Type.KeyPress
            and watched is self.tree
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            self._open(not ctrl)
            return True
        return super().eventFilter(watched, event)

    def _open(self, focus: bool) -> None:
        ids = self.selected_ids()
        if ids:
            self.open_requested.emit(ids, focus)

    def _menu(self, point: QPoint) -> None:
        if self.tree.itemAt(point) is not None:  # the click picked it already
            self.menu_requested.emit(self.tree.viewport().mapToGlobal(point))

    def _item(self, host_id: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(NAME, ID_ROLE) == host_id:
                return item
        return None

    def _fill(self, item: QTreeWidgetItem, facts: RowFacts) -> None:
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        text = self.palette().color(QPalette.ColorRole.Text)
        item.setText(STATUS, facts.status)
        item.setIcon(STATUS, dot_icon(facts.status_color, 10) if facts.status_color else QIcon())
        item.setToolTip(STATUS, facts.status_tip)
        item.setForeground(STATUS, text if facts.status_color else muted)
        item.setData(STATUS, SORT_ROLE, natural_key(facts.status))
        for column, value in ((PROFILES, facts.profiles), (DELETABLE, facts.deletable)):
            item.setText(column, "" if value is None else str(value))
            item.setData(column, SORT_ROLE, -1 if value is None else value)
            item.setTextAlignment(column, RIGHT_ALIGNED)
        item.setText(SCAN, facts.scan)
        item.setData(SCAN, SORT_ROLE, facts.scan_time)
        item.setForeground(SCAN, QColor(facts.scan_color) if facts.scan_color else text)

    def _fit(self) -> None:
        header = self.tree.header()
        header.setSortIndicatorShown(False)
        for column in range(SCAN):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, self.tree.columnWidth(column) + 14)
        header.setSortIndicatorShown(True)
        self._fitted = True
        self.squeeze.set_full()
        metrics = self.tree.header().fontMetrics()
        self.squeeze.set_narrow_width(DELETABLE, metrics.horizontalAdvance(_("Deletable")) + 30)

    def _place_empty(self) -> None:
        if not self._empty.isVisible():
            return
        area = self.tree.viewport().rect()
        size = self._empty.sizeHint().boundedTo(area.size())
        size = QSize(min(area.width(), max(size.width(), 360)), size.height())
        self._empty.setGeometry(
            area.x() + (area.width() - size.width()) // 2,
            area.y() + max(0, (area.height() - size.height()) // 3),
            size.width(),
            size.height(),
        )


class HostsPage(QObject):
    """The pinned Hosts tab: `box` in the middle, `side` on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.search = SearchBox()
        self.table = HostsTable()
        self.box = TabBox(self.search, self.table)
        self.host_card = HostCard()
        self.side = self.host_card  # the right panel's card for this tab
        self.search.to_results.connect(self._to_results)
        self.retranslate()

    def retranslate(self) -> None:
        self.search.setPlaceholderText(_("Search name, address"))
        self.search.setToolTip(_("Looks through every host of the list, whatever the group"))
        self.table.retranslate()

    def show_title(self, name: str, about: str) -> None:
        self.box.show_title(name, about)

    def show_host(self, facts: HostFacts | GroupFacts) -> None:
        """The card under Progress: the one host picked, or the hosts on show as a whole."""
        if isinstance(facts, HostFacts):
            self.host_card.show_host(facts)
        else:
            self.host_card.show_group(facts)

    def _to_results(self) -> None:
        tree = self.table.tree
        first = tree.topLevelItem(0)
        if first is not None:
            tree.setCurrentItem(first)
            tree.setFocus(Qt.FocusReason.TabFocusReason)
