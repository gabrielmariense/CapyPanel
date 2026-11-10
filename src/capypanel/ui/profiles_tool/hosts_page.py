"""The User profiles tool's pinned Hosts tab: the hosts of the group picked on the left, what each
scan found so far, and on the right the progress across every host's tab, with the host picked
in its own box under it. It never scans by itself: a double-click, Enter or Scan opens a host."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext, pgettext
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import SearchBox, natural_key
from capypanel.ui.profiles_tool.host_page import HostPage
from capypanel.ui.profiles_tool.panels import TabBox, hint
from capypanel.ui.tables import grid_table

NAME, ADDRESS, STATUS, PROFILES, DELETABLE, SCAN = range(6)  # the table's columns
ID_ROLE = Qt.ItemDataRole.UserRole  # the row's host
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
HOST_BOX_HEIGHT = 196  # px: the picked host's box; Andamento keeps the rest
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


@dataclass(frozen=True)
class HostFacts:
    """The picked host's own box."""

    name: str
    dot: str  # its status colour; "" for none
    status: str  # "Offline · checked by Hosts at 10:30"
    address: str
    group: str
    scanned: str  # "10:41", or "—"
    account: str  # who signs in, or "—"


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
    scan_typed = Signal(str)  # "Scan 192.0.2.50" in the empty table

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 6)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setStretchLastSection(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(NAME, Qt.SortOrder.AscendingOrder)
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemDoubleClicked.connect(lambda *_a: self._open(True))
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
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
        header = self.tree.headerItem()
        header.setToolTip(PROFILES, _("Profiles found by the last scan"))
        header.setToolTip(DELETABLE, _("Profiles the last scan found that can be deleted"))
        header.setToolTip(SCAN, _("When the host was scanned, or where its scan is"))
        self._empty_hint.setText(_("Opens the host in a new tab. Typing alone never scans."))
        self.show_typed(self._typed)

    def show_hosts(self, hosts: Sequence[Host], facts: Callable[[Host], RowFacts]) -> None:
        kept = set(self.selected_ids())
        self.tree.setSortingEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        for host in hosts:
            item = _Row()
            item.setData(NAME, ID_ROLE, host.id)
            item.setText(NAME, host.name)
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


class _Name(QWidget):
    """A host's name in Andamento: it takes the room the line leaves and ends in "…" when it
    can't fit, its whole name in the tooltip, so where the host is always shows beside it."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance("…") * 3, metrics.height())

    def shown_text(self) -> str:
        return self.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.setToolTip(self._text if self.shown_text() != self._text else "")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.rect(), align, self.shown_text())
        painter.end()


class _Line(QWidget):
    """One host in Andamento: its mark, its name, and where it is on the right. A click goes to
    its tab."""

    clicked = Signal(str)

    def __init__(self, key: str, icon: QLabel | None, name: str, where: str, color: str) -> None:
        super().__init__()
        self._key = key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(6)
        if icon is not None:
            row.addWidget(icon)
        self.name = _Name(name)
        self.where = QLabel(where)
        self.where.setObjectName("" if color else "hint")
        if color:
            self.where.setStyleSheet(f"color: {color};")
        row.addWidget(self.name, 1)
        row.addWidget(self.where)  # never cut: the name gives way

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)


class ProgressCard(QFrame):
    """Andamento: how far the hosts in tabs are, the busy ones each on a line, the waiting ones
    by name, and the ones done with how they ended. A section shows only when it has a host."""

    go_to = Signal(str)  # a host's key: its tab comes to the front

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.title = QLabel()
        font = QFont(self.title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        self.title.setFont(font)
        self.summary = DetailsPanel.muted("")
        self.bar = QProgressBar()
        self.bar.setObjectName("thin")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self._lines = QWidget()
        self._lines_box = QVBoxLayout(self._lines)
        self._lines_box.setContentsMargins(0, 0, 0, 0)
        self._lines_box.setSpacing(2)
        scroll = QScrollArea()
        scroll.setWidget(self._lines)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        self._lines.setAutoFillBackground(False)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(3)
        column.addWidget(self.title)
        column.addWidget(self.summary)
        column.addSpacing(6)
        column.addWidget(self.bar)
        column.addWidget(scroll, 1)

    def show_pages(self, pages: Sequence[HostPage]) -> None:
        self.title.setText(_("Progress"))
        busy = [p for p in pages if p.mark().busy]
        waiting = [p for p in pages if not p.mark().busy and p.busy()]
        done = [p for p in pages if not p.busy()]
        total = len(pages)
        if total:
            self.summary.setText(
                ngettext("{n} host in tabs", "{n} hosts in tabs", total).format(n=total)
                + " · "
                + ngettext("{n} done", "{n} done", len(done)).format(n=len(done))
            )
        else:
            self.summary.setText(_("Open a host to scan it: double-click it, or pick it and "
                                   "click Scan."))  # fmt: skip
        self.bar.setVisible(bool(total))
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(len(done))
        while (item := self._lines_box.takeAt(0)) is not None:
            if (widget := item.widget()) is not None:
                widget.hide()  # or it's drawn where it was until Qt deletes it
                widget.deleteLater()
        if busy:
            self._section(_("In progress ({n})").format(n=len(busy)))
            for page in busy:
                self._line(page, page.mark().short, "")
        if waiting:
            self._section(_("Waiting ({n})").format(n=len(waiting)))
            names = DetailsPanel.muted(", ".join(p.target.name for p in waiting))
            self._lines_box.addWidget(names)
        if done:
            self._section(_("Done ({n})").format(n=len(done)))
            for page in done:
                mark = page.mark()
                self._line(page, mark.short, mark.color if mark.bad else "")
        self._lines_box.addStretch(1)

    def _section(self, text: str) -> None:
        rule = QFrame()
        rule.setObjectName("detailsRule")
        self._lines_box.addSpacing(10)
        self._lines_box.addWidget(rule)
        self._lines_box.addSpacing(6)
        heading = QLabel(text)
        heading.setObjectName("detailsSection")
        self._lines_box.addWidget(heading)

    def _line(self, page: HostPage, where: str, color: str) -> None:
        mark = page.mark()
        icon = QLabel()
        if mark.icon:
            icon.setPixmap(tabler_icon(mark.icon, QColor(mark.color), 14).pixmap(14, 14))
        icon.setFixedWidth(14)
        line = _Line(page.target.key, icon, page.target.name, where, color)
        line.setToolTip(mark.tip)
        line.clicked.connect(self.go_to)
        self._lines_box.addWidget(line)


class HostCard(QFrame):
    """The host picked on the Hosts tab, in its own box under Andamento."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.setFixedHeight(HOST_BOX_HEIGHT)
        self.heading = QLabel()
        small = QFont(self.heading.font())
        small.setBold(True)
        small.setPointSizeF(small.pointSizeF() * 0.85)
        self.heading.setFont(small)
        self.dot = QLabel()
        self.name = QLabel()
        self.name.setWordWrap(True)  # a long host name goes on two lines, never cut
        big = QFont(self.name.font())
        big.setBold(True)
        big.setPointSizeF(big.pointSizeF() * 1.25)
        self.name.setFont(big)
        self.status = DetailsPanel.muted("")
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.dot)
        top.addWidget(self.name, 1)
        self._labels = [QLabel() for _n in range(4)]
        self._values = [QLabel() for _n in range(4)]
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 92)
        for index, (label, value) in enumerate(zip(self._labels, self._values, strict=True)):
            label.setObjectName("hint")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(label, index, 0)
            grid.addWidget(value, index, 1)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 10, 14, 10)
        column.setSpacing(3)
        column.addWidget(self.heading)
        column.addLayout(top)
        column.addWidget(self.status)
        column.addSpacing(6)
        column.addLayout(grid)
        column.addStretch(1)

    def show_host(self, facts: HostFacts) -> None:
        self.heading.setText(_("SELECTED HOST"))
        self.name.setText(facts.name)
        self.dot.setVisible(bool(facts.dot))
        if facts.dot:
            self.dot.setPixmap(dot_icon(facts.dot, 12).pixmap(12, 12))
        self.status.setText(facts.status)
        pairs = (
            (_("Address"), facts.address),
            (_("Group"), facts.group),
            (_("Scanned at"), facts.scanned),
            (_("As"), facts.account),
        )
        for (label, value), name, shown in zip(pairs, self._labels, self._values, strict=True):
            name.setText(label)
            shown.setText(value)


class HostsPage(QObject):
    """The pinned Hosts tab: `box` in the middle, `side` on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.search = SearchBox()
        self.table = HostsTable()
        self.box = TabBox(self.search, self.table)
        self.progress = ProgressCard()
        self.host_card = HostCard()
        self.host_card.hide()
        self.side = QWidget()
        column = QVBoxLayout(self.side)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self.progress, 1)
        column.addWidget(self.host_card)
        self.search.to_results.connect(self._to_results)
        self.retranslate()

    def retranslate(self) -> None:
        self.search.setPlaceholderText(_("Search name, address"))
        self.search.setToolTip(_("Looks through every host of the list, whatever the group"))
        self.table.retranslate()

    def show_title(self, name: str, about: str) -> None:
        self.box.show_title(name, about)

    def show_host(self, facts: HostFacts | None) -> None:
        """The picked host's box: only with one host picked."""
        self.host_card.setVisible(facts is not None)
        if facts is not None:
            self.host_card.show_host(facts)

    def _to_results(self) -> None:
        tree = self.table.tree
        first = tree.topLevelItem(0)
        if first is not None:
            tree.setCurrentItem(first)
            tree.setFocus(Qt.FocusReason.TabFocusReason)
