"""The parts of a host's tab in the User profiles tool: its box (the host's name, the filters and
the profiles table, or a card saying what's happening or what went wrong), a profile's details
and the Delete window. The right panel's cards are in side.py."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QHelpEvent,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.user_profiles import Deleted, Kind, Outcome, Profile, State
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.hosts_tool.runner import escape
from capypanel.ui.icons import STATUS_COLORS, dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import natural_key
from capypanel.ui.menus import popup
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.rows import Filters, Result
from capypanel.ui.tables import fit_rows, grid_table

LEFT, RIGHT = 234, 284  # px: the narrowest the Groups panel opens at, and the right panel can be
DETAILS = 340  # px: the right panel's first width, as Hosts' Details
TICK, USER, USED, SIZE, KIND, STATE = range(6)  # the table's columns
SORT_ROLE = Qt.ItemDataRole.UserRole + 1  # what a cell sorts by
ARROW = 16  # px a column title needs for the sort arrow
IDENT_ROLE = Qt.ItemDataRole.UserRole  # the row's profile
CAREFUL_ROLE = Qt.ItemDataRole.UserRole + 2  # ticked: deleted on Delete…
COUNTING_ROLE = Qt.ItemDataRole.UserRole + 3  # its size is being counted now
AMBER = STATUS_COLORS["attention"]  # what deletes, everywhere in the app
INFO = 22  # px: the (i) at the end of the clicked row, which opens the profile's window
INFO_GAP = 4  # px between it and the row's right edge


def card() -> QFrame:
    """A box with the lists' background, as the other tools' panels."""
    frame = QFrame()
    frame.setObjectName("card")
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setBackgroundRole(QPalette.ColorRole.Base)
    frame.setAutoFillBackground(True)
    return frame


def hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def _fold(text: str) -> str:
    return text.strip().casefold()


# ---- a tab's box ----


def second_line_height() -> int:
    """The second line's height on every tab: the taller of a search box and a dropdown, so the
    table's top edge is at the same place whichever tab is in front."""
    return max(QLineEdit().sizeHint().height(), QComboBox().sizeHint().height())


class TabBox(QFrame):
    """A tab's one box: a bold name and a grey line about it on top, a second line under them
    (the search, or the filters), a thin rule, then `body` flush to the box's edges."""

    def __init__(self, second: QWidget, body: QWidget) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.icon = QLabel()
        self.icon.hide()
        self.name = QLabel()
        font = QFont(self.name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.name.setFont(font)
        self.about = hint()
        self.about.setWordWrap(False)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.icon)
        top.addWidget(self.name)
        top.addWidget(self.about, 1)
        self.second = second
        self.second.setFixedHeight(second_line_height())
        head = QVBoxLayout()
        head.setContentsMargins(12, 10, 10, 8)
        head.setSpacing(8)
        head.addLayout(top)
        head.addWidget(second)
        column = QVBoxLayout(self)
        column.setContentsMargins(1, 1, 1, 1)
        column.setSpacing(0)
        column.addLayout(head)
        column.addWidget(_divider())
        column.addWidget(body, 1)

    def show_title(self, name: str, about: str) -> None:
        self.name.setText(name)
        self.about.setText(about)


class Squeeze(QObject):
    """Keeps a table's columns inside its box. When their full widths don't fit, the columns in
    `order` give up width one after another, each down to its least (cut text ends in "…"),
    while the last column keeps the room `last_least` says it needs. Only when that isn't
    enough does the table scroll sideways. A width the admin drags becomes that column's full
    width. `narrowed` says the full widths stopped (or started) fitting."""

    narrowed = Signal(bool)

    def __init__(
        self,
        tree: QTreeWidget,
        order: Sequence[tuple[int, int]],
        last_least: Callable[[], int],
    ) -> None:
        super().__init__(tree)
        self._tree = tree
        self._order = order
        self._last_least = last_least
        self._full: dict[int, int] = {}  # every column but the last, at its full width
        self._narrow_widths: dict[int, int] = {}  # full widths that apply only while narrow
        self._narrow = False
        self._busy = False
        tree.viewport().installEventFilter(self)
        tree.header().sectionResized.connect(self._dragged)

    def set_full(self) -> None:
        """The widths the columns have now are their full ones."""
        last = self._tree.columnCount() - 1
        self._full = {c: self._tree.columnWidth(c) for c in range(last)}
        self._tree.header().setStretchLastSection(False)  # apply() sizes it from here on
        self.apply()

    def set_narrow_width(self, column: int, width: int) -> None:
        """While narrow, `column` is this wide at most (its title got shorter)."""
        self._narrow_widths[column] = width
        self.apply()

    def is_narrow(self) -> bool:
        return self._narrow

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.apply()
        return False

    def _dragged(self, column: int, _old: int, new: int) -> None:
        if not self._busy and column in self._full:
            self._full[column] = new

    def apply(self, room: int | None = None) -> None:
        """`room`: the width to fit in; the table's own when not given."""
        if not self._full:
            return
        tree = self._tree
        room = tree.viewport().width() if room is None else room
        need = self._last_least()
        widths = dict(self._full)
        narrow = sum(widths.values()) + need > room
        if narrow:
            for column, width in self._narrow_widths.items():
                widths[column] = min(widths[column], width)
        over = sum(widths.values()) + need - room
        for column, least in self._order:
            if over <= 0:
                break
            give = min(over, max(0, widths[column] - least))
            widths[column] -= give
            over -= give
        self._busy = True
        for column, width in widths.items():
            if tree.columnWidth(column) != width:
                tree.setColumnWidth(column, width)
        last = tree.columnCount() - 1
        tree.setColumnWidth(last, max(need, room - sum(widths.values())))
        self._busy = False
        if narrow != self._narrow:
            self._narrow = narrow
            self.narrowed.emit(narrow)


class Count(QWidget):
    """The right end of a host tab's second line: how many rows show, or, with rows ticked, a
    bin and "3 ticked · 12.4 GB" in bold amber. It never widens its row: short of room it ends
    in "…" on the right, with the whole text in its tooltip, and its start is never cut."""

    GAP = 5  # px between the bin and the words
    BIN = 14

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._short = ""
        self._least = ""
        self._ticked = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def show_count(self, text: str, ticked: bool, short: str = "", least: str = "") -> None:
        """What stands in for `text` when it can't all fit: `short` ("3 ticked", without the
        size), then `least` (just "3", beside the bin). A word is never cut; only a text
        with neither ends in "…"."""
        self._text, self._ticked, self._short, self._least = text, ticked, short, least
        font = QFont(self.font())
        font.setBold(ticked)
        self.setFont(font)
        self.updateGeometry()
        self._tip()
        self.update()

    def text(self) -> str:
        return self._text

    def has_bin(self) -> bool:
        return self._ticked

    def shown_text(self) -> str:
        """The words as drawn at this width."""
        room = max(0, self.width() - (self.BIN + self.GAP if self._ticked else 0))
        metrics = self.fontMetrics()
        for words in (self._text, self._short):
            if words and metrics.horizontalAdvance(words) <= room:
                return words
        if self._least:
            return self._least
        return metrics.elidedText(self._text, Qt.TextElideMode.ElideRight, room)

    def sizeHint(self) -> QSize:
        width = self.fontMetrics().horizontalAdvance(self._text) + 2
        return QSize(
            width + (self.BIN + self.GAP if self._ticked else 0), self.fontMetrics().height()
        )

    def minimumSizeHint(self) -> QSize:
        return QSize(self.fontMetrics().horizontalAdvance("…") + 2, self.fontMetrics().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._tip()

    def _tip(self) -> None:
        self.setToolTip(self._text if self.shown_text() != self._text else "")

    def paintEvent(self, event: QPaintEvent) -> None:
        shown = self.shown_text()
        painter = QPainter(self)
        color = (
            QColor(AMBER)
            if self._ticked
            else self.palette().color(QPalette.ColorRole.PlaceholderText)
        )
        width = self.fontMetrics().horizontalAdvance(shown)
        left = self.width() - width
        if self._ticked:
            icon = tabler_icon("trash", QColor(AMBER), self.BIN)
            left -= self.BIN + self.GAP
            top = (self.height() - self.BIN) // 2
            icon.paint(painter, left, top, self.BIN, self.BIN)
            left += self.BIN + self.GAP
        painter.setPen(color)
        painter.drawText(left, 0, width, self.height(), Qt.AlignmentFlag.AlignVCenter, shown)
        painter.end()


class FilterRow(QWidget):
    """A host tab's second line: which rows to show, and how many are shown."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.hide_own = QCheckBox()
        self.hide_own.setChecked(True)
        self.leftovers = QCheckBox()
        self.since_label = QLabel()
        self.since = QComboBox()
        self.shown = Count()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.hide_own)
        row.addWidget(self.leftovers)
        row.addSpacing(6)
        pair = QHBoxLayout()
        pair.setSpacing(6)
        pair.addWidget(self.since_label)
        pair.addWidget(self.since)
        row.addLayout(pair)
        row.addSpacing(10)
        row.addWidget(self.shown, 1)  # the room left, its words on the right
        self.retranslate()
        self.hide_own.toggled.connect(self.changed)
        self.leftovers.toggled.connect(self.changed)
        self.since.currentIndexChanged.connect(self.changed)

    def retranslate(self) -> None:
        self.hide_own.setText(_("Hide Windows' own"))
        self.hide_own.setToolTip(
            _("Public, Default, the built-in Administrator and the like: never deleted here")
        )
        self.leftovers.setText(_("Only leftovers"))
        self.leftovers.setToolTip(
            _("Only registry entries without a folder and folders without a registry entry")
        )
        self.since_label.setText(_("Unused for:"))
        tip = _(
            "By the last sign-in or sign-out Windows wrote down; a row that has none goes by "
            "its folder's date"
        )
        self.since.setToolTip(tip)
        picked = max(self.since.currentIndex(), 0)
        self.since.blockSignals(True)
        self.since.clear()
        self.since.addItems([rows.months_text(months) for months in rows.MONTHS])
        self.since.setCurrentIndex(picked)
        self.since.blockSignals(False)

    def show_count(self, shown: str, ticked: str = "", short: str = "", least: str = "",
                   shown_short: str = "") -> None:  # fmt: skip
        """How many rows show; with rows ticked, how many and their size instead, in bold
        amber with the bin, in the same place. Short of room, the ticked words lose the size
        (`short`), then all but the number (`least`); the plain count loses its last word
        (`shown_short`: "12 of 15"). A word is never cut."""
        if ticked:
            self.shown.show_count(ticked, True, short, least)
        else:
            self.shown.show_count(shown, False, shown_short)

    def chosen(self) -> Filters:
        return Filters(
            hide_own=self.hide_own.isChecked(),
            leftovers=self.leftovers.isChecked(),
            months=rows.MONTHS[max(self.since.currentIndex(), 0)],
        )


class HintCard(QFrame):
    """The middle of the page when there's no table to show: what to do, or what happened."""

    def __init__(
        self,
        icon: str,
        color: QColor,
        title: str,
        lines: Sequence[str],
        buttons: Sequence[tuple[str, Callable[[], None]]] = (),
    ) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        sign = QLabel()
        sign.setPixmap(tabler_icon(icon, color, 40).pixmap(40, 40))
        sign.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.heading = QLabel(title)
        font = QFont(self.heading.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.heading.setFont(font)
        self.heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.heading.setWordWrap(True)
        self.body = hint("\n".join(lines))
        self.body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body.setFixedWidth(500)
        self.body.setMinimumHeight(self.body.heightForWidth(500))
        self.buttons: list[QPushButton] = []
        row = QHBoxLayout()
        row.addStretch(1)
        for text, run in buttons:
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _c=False, r=run: r())
            self.buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        column = QVBoxLayout(self)
        column.addStretch(2)
        column.addWidget(sign)
        column.addSpacing(6)
        column.addWidget(self.heading)
        column.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(8)
        column.addLayout(row)
        column.addStretch(3)


# ---- the table ----


class _Row(QTreeWidgetItem):
    """Sorts by what a cell means (a date, a size), not by how it's written; rows that tie stay
    in name order."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else USER
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine == theirs:  # by name, A to Z, whichever way the column is sorted
            names = self.data(USER, SORT_ROLE), other.data(USER, SORT_ROLE)
            down = tree is not None and (
                tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return bool(names[1] < names[0]) if down else bool(names[0] < names[1])
        return bool(mine < theirs)


def info_rect(cell: QRect) -> QRect:
    """Where the (i) sits in a row's last cell."""
    return QRect(cell.right() - INFO - INFO_GAP + 1, cell.top() + (cell.height() - INFO) // 2,
                 INFO, INFO)  # fmt: skip


class _Careful(QStyledItemDelegate):
    """Draws a 2 px amber outline round a ticked row, inside it so no row grows, over the
    selection's colour; and, at the end of the clicked row, the (i) that opens the profile's
    window."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        model = index.model()
        rect: QRect = option.rect  # type: ignore[attr-defined]
        view = self.parent()
        if (
            index.column() == STATE
            and isinstance(view, QTreeWidget)
            and view.currentIndex().row() == index.row()
            and view.currentIndex().isValid()
        ):
            box = info_rect(rect)
            palette = view.palette()
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(palette.color(QPalette.ColorRole.Mid))
            painter.setBrush(palette.color(QPalette.ColorRole.Button))
            painter.drawRoundedRect(box, 4, 4)
            icon = tabler_icon("info-circle", palette.color(QPalette.ColorRole.ButtonText), 16)
            icon.paint(painter, box.adjusted(3, 3, -3, -3))
            painter.restore()
        if model is None or not model.index(index.row(), USER, index.parent()).data(CAREFUL_ROLE):
            return
        painter.save()
        painter.setPen(QPen(QColor(AMBER), 2))
        top, bottom = rect.top() + 1, rect.bottom() - 2  # above the grid's 2 px line
        painter.drawLine(rect.left(), top, rect.right(), top)
        painter.drawLine(rect.left(), bottom, rect.right(), bottom)
        if index.column() == TICK:
            painter.drawLine(rect.left() + 1, top, rect.left() + 1, bottom)
        if index.column() == STATE:
            painter.drawLine(rect.right(), top, rect.right(), bottom)
        painter.restore()

    def helpEvent(  # type: ignore[override]
        self,
        event: QHelpEvent,
        view: object,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Over the (i): what it does, in place of the State cell's own tip."""
        rect: QRect = option.rect  # type: ignore[attr-defined]
        if (
            isinstance(view, QTreeWidget)
            and index.column() == STATE
            and view.currentIndex().row() == index.row()
            and info_rect(rect).contains(event.pos())
        ):
            QToolTip.showText(event.globalPos(), _("Details (Enter)"), view)
            return True
        return super().helpEvent(event, view, option, index)  # type: ignore[arg-type]


class ProfilesTable(QWidget):
    """One row per profile and leftover. Only a row that can be deleted has a tick box; the
    others are greyed, with their state saying why. A ticked row looks like something to be
    careful with: amber text (normal text in a light theme, where amber can't be read), "Will
    be deleted" with the bin, and an amber outline. A row that was in a delete run shows how it
    ended instead. A click on a column's title sorts by it, except the ticks' column. A row's
    details open from the (i) at the end of the clicked row, Enter, or its right-click."""

    picked = Signal()  # another row has the selection
    ticked_changed = Signal()
    details_requested = Signal(str)  # a row's ident

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 6)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)  # flush to its box's edges
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        # At a narrow width User gives up room first, then Kind; the ticks and State stay.
        self.squeeze = Squeeze(self.tree, ((USER, 110), (KIND, 70)), self._state_least)
        self.tree.setSortingEnabled(True)
        # Newest first, as people scan the list for who still uses the PC; a click on Last used
        # turns it round, the oldest on top.
        self.tree.sortByColumn(USED, Qt.SortOrder.DescendingOrder)
        self._sorted = (USED, Qt.SortOrder.DescendingOrder)
        self.tree.header().sortIndicatorChanged.connect(self._sort_picked)
        self.tree.setItemDelegate(_Careful(self.tree))
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemChanged.connect(self._changed)
        # Going down the list with the keyboard: Space ticks the row the arrows are on, and so
        # does a double-click anywhere on a row.
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self._info_pressed = ""  # the row whose (i) the mouse went down on
        self._profiles: dict[str, Profile] = {}
        self._ticked: set[str] = set()
        self._results: dict[str, Result] = {}
        self._locked = False  # during a delete run no tick changes
        self._fitted = False
        self._root = ""  # the host's Users folder
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.retranslate()

    def retranslate(self) -> None:
        """The titles, and the bin over the ticks in the theme's muted colour."""
        self.tree.setHeaderLabels(["", _("User"), _("Last used"), _("Size"), _("Kind"), _("State")])
        header = self.tree.headerItem()
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        header.setIcon(TICK, tabler_icon("trash", muted, 14))
        header.setToolTip(TICK, _("Tick to delete: the box, Space, or a double-click on the row"))

    def _sort_picked(self, column: int, order: Qt.SortOrder) -> None:
        """A click on the ticks' title does nothing: no sort, no tick-all."""
        if column == TICK:
            header = self.tree.header()
            header.blockSignals(True)
            self.tree.sortByColumn(*self._sorted)
            header.blockSignals(False)
        else:
            self._sorted = (column, order)

    def show_profiles(
        self,
        profiles: Sequence[Profile],
        sizes: dict[str, int | None],
        results: dict[str, Result] | None = None,
        root: str = "",
    ) -> None:
        """`sizes`: bytes for the rows counted; None for one being counted now. `results`: how
        the rows of a delete run stand. `root`: the host's Users folder, for the State tips. A
        tick on a row no longer shown is dropped: what's ticked is always in sight."""
        self._root = root
        kept = self.selected()
        self._profiles = {p.ident: p for p in profiles}
        self._results = dict(results or {})
        before = set(self._ticked)
        self._ticked = {i for i in self._ticked if self._tickable(i)}
        self.tree.setSortingEnabled(False)  # or each cell set would move its row
        self.tree.blockSignals(True)
        self.tree.clear()
        for profile in profiles:
            item = _Row()
            item.setData(USER, IDENT_ROLE, profile.ident)
            self.tree.addTopLevelItem(item)
            self._fill(item, profile, sizes)
            if kept is not None and profile.ident == kept.ident:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        if not self._fitted and profiles:  # once: widths the admin drags afterwards stay
            self.fit()
        self.picked.emit()
        if before != self._ticked:
            self.ticked_changed.emit()

    def show_size(self, ident: str, sizes: dict[str, int | None], so_far: int = 0) -> None:
        """One row's size changed: counted, or being counted (`so_far`: the bytes counted up
        to now, shown as "1.2 GB…" so the count is seen moving)."""
        item = self._item(ident)
        if item is not None:
            self._fill_size(item, ident, sizes, so_far)

    def show_result(self, ident: str, result: Result | None) -> None:
        """One row moved on in a delete run; None takes it out of the run again."""
        if result is None:
            self._results.pop(ident, None)
        else:
            self._results[ident] = result
            if result in rows.ENDED:
                self._ticked.discard(ident)
        item = self._item(ident)
        if item is not None:
            self.tree.blockSignals(True)
            self._fill_state(item, self._profiles[ident])
            self.tree.blockSignals(False)

    def lock(self, locked: bool) -> None:
        """While profiles are deleted, the ticks can't change."""
        self._locked = locked
        self.tree.blockSignals(True)
        for ident in self._profiles:
            item = self._item(ident)
            if item is not None:
                self._fill_state(item, self._profiles[ident])
        self.tree.blockSignals(False)

    def fit(self) -> None:
        """Each column as wide as its text, and no wider: State, the last one, must stay in
        sight when the progress panel takes room on the right."""
        header = self.tree.header()
        header.setSortIndicatorShown(False)  # or every title is sized for an arrow it lacks
        for column in range(USER, STATE):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, self.tree.columnWidth(column) + 6)
        header.setSortIndicatorShown(True)
        sorted_by = header.sortIndicatorSection()
        if USER <= sorted_by < STATE:  # the one title that does have the arrow
            self.tree.setColumnWidth(sorted_by, self.tree.columnWidth(sorted_by) + ARROW)
        self.tree.setColumnWidth(TICK, 34)
        # Size starts empty: room for "counting…" and a size, so neither is ever cut.
        widest = max(
            self.tree.fontMetrics().horizontalAdvance(text)
            for text in (_("counting…"), rows.size_text(888 * rows.GB))
        )
        self.tree.setColumnWidth(SIZE, max(self.tree.columnWidth(SIZE), widest + 20))
        self._fitted = True
        self.squeeze.set_full()

    def _state_least(self) -> int:
        """State's width for its longest word with its icon, so it's never cut."""
        words = [rows.state_name(state) for state in rows.STATE_ORDER]
        words += [_(name) for name in rows.RESULT_NAMES.values()]
        words += [_("Will be deleted"), _("State")]
        metrics = self.tree.fontMetrics()
        widest = max(metrics.horizontalAdvance(word) for word in words)
        return widest + 16 + 26 + INFO + INFO_GAP  # its icon, the padding, the (i)

    def selected(self) -> Profile | None:
        items = self.tree.selectedItems()
        return self._profiles.get(items[0].data(USER, IDENT_ROLE)) if items else None

    def shown(self) -> list[Profile]:
        """The rows, in the order on screen."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [self._profiles[item.data(USER, IDENT_ROLE)] for item in found if item]

    def ticked(self) -> list[Profile]:
        """The rows ticked, in the order on screen."""
        return [p for p in self.shown() if p.ident in self._ticked]

    def tick(self, ident: str, on: bool = True) -> None:
        """Ticks a row as a click on its box does; a row without a box stays as it is."""
        item = self._item(ident)
        if item is not None and self._tickable(ident) and not self._locked:
            item.setCheckState(TICK, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def toggle(self, ident: str) -> None:
        """Ticks a row, or unticks it; a row without a box stays as it is."""
        self.tick(ident, ident not in self._ticked)

    def profile(self, ident: str) -> Profile | None:
        return self._profiles.get(ident)

    def is_ticked(self, ident: str) -> bool:
        return ident in self._ticked

    def can_tick(self, ident: str) -> bool:
        """The row has a tick box, and it may change now."""
        return self._tickable(ident) and not self._locked

    def select(self, ident: str) -> None:
        """The row gets the selection and comes into view."""
        item = self._item(ident)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def info_at(self, point: QPoint) -> str:
        """The row whose (i) is at `point` of the table's inside: only the clicked row has one."""
        item = self.tree.itemAt(point)
        if item is None or item is not self.tree.currentItem():
            return ""
        cell = self.tree.visualItemRect(item)
        left = self.tree.columnViewportPosition(STATE)
        cell = QRect(left, cell.top(), self.tree.columnWidth(STATE), cell.height())
        return item.data(USER, IDENT_ROLE) if info_rect(cell).contains(point) else ""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.tree and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            current = self.tree.currentItem()
            if event.key() == Qt.Key.Key_Space:
                if current is not None:
                    self.toggle(current.data(USER, IDENT_ROLE))
                return True  # or Qt ticks it a second time when the box's own cell is current
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and current is not None:
                self.details_requested.emit(current.data(USER, IDENT_ROLE))
                return True
        if (
            watched is self.tree.viewport()
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):  # the (i): down and up on it, on the row that was already the clicked one
            if event.type() == QEvent.Type.MouseButtonPress:
                self._info_pressed = self.info_at(event.position().toPoint())
            elif event.type() == QEvent.Type.MouseButtonRelease:
                pressed, self._info_pressed = self._info_pressed, ""
                if pressed and pressed == self.info_at(event.position().toPoint()):
                    # After the table has had its release, or it would think the button is
                    # still down once the window closes.
                    QTimer.singleShot(0, self, lambda: self.details_requested.emit(pressed))
        return super().eventFilter(watched, event)

    def _menu(self, point: QPoint) -> None:
        item = self.tree.itemAt(point)
        if item is None:
            return
        ident = item.data(USER, IDENT_ROLE)
        menu = QMenu(self)
        menu.addAction(_("&Details…"), lambda: self.details_requested.emit(ident))
        popup(menu, self.tree.viewport().mapToGlobal(point))

    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != TICK:  # on the box itself, the two clicks already ticked and unticked
            self.toggle(item.data(USER, IDENT_ROLE))

    def texts(self) -> list[list[str]]:
        """Every row's cells, in the order on screen (for tests); the tick's cell has no text."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [[item.text(c) for c in range(STATE + 1)] for item in found if item]

    def _item(self, ident: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(USER, IDENT_ROLE) == ident:
                return item
        return None

    def _tickable(self, ident: str) -> bool:
        """Ready, and not already through a delete run."""
        profile = self._profiles.get(ident)
        return profile is not None and profile.ready and self._results.get(ident) not in rows.ENDED

    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != TICK:
            return
        ident = item.data(USER, IDENT_ROLE)
        on = item.checkState(TICK) == Qt.CheckState.Checked
        if on == (ident in self._ticked) or not self._tickable(ident):
            return
        (self._ticked.add if on else self._ticked.discard)(ident)
        self.tree.blockSignals(True)
        self._fill_state(item, self._profiles[ident])  # its careful look on, or off
        self.tree.blockSignals(False)
        self.ticked_changed.emit()

    def _fill(self, item: QTreeWidgetItem, profile: Profile, sizes: dict[str, int | None]) -> None:
        item.setText(USER, rows.user_text(profile))
        item.setToolTip(USER, rows.user_text(profile))  # whole, when the column is narrow
        item.setData(USER, SORT_ROLE, natural_key(profile.user))
        item.setText(USED, rows.date_text(profile.last_used) or "—")
        used = profile.last_used.timestamp() if profile.last_used else float("-inf")
        item.setData(USED, SORT_ROLE, used)
        item.setText(KIND, _(rows.KIND_NAMES[profile.kind]))
        item.setData(KIND, SORT_ROLE, list(Kind).index(profile.kind))
        item.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._fill_state(item, profile)
        self._fill_size(item, profile.ident, sizes)

    def _fill_state(self, item: QTreeWidgetItem, profile: Profile) -> None:
        """The tick box, the State cell and the row's colour: its state, or where it stands in
        a delete run."""
        ident, result = profile.ident, self._results.get(profile.ident)
        careful = result is None and ident in self._ticked and self._tickable(ident)
        item.setData(USER, CAREFUL_ROLE, careful)
        if careful:
            item.setText(STATE, _("Will be deleted"))
            item.setIcon(STATE, tabler_icon("trash", QColor(AMBER), 16))
            item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
            item.setToolTip(STATE, _("Ticked: it's deleted once you click Delete and confirm"))
        elif result is None:
            item.setText(STATE, rows.state_name(profile.state))
            ready = profile.state is State.READY  # plain words: no colour says "fine" here
            item.setIcon(
                STATE, QIcon() if ready else dot_icon(rows.STATE_COLORS[profile.state], 10)
            )
            item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
            item.setToolTip(STATE, rows.state_why(profile, self._root))
        else:
            icon, color = rows.RESULT_ICONS[result]
            item.setText(STATE, _(rows.RESULT_NAMES[result]))
            item.setIcon(STATE, tabler_icon(icon, QColor(color), 16))
            item.setData(STATE, SORT_ROLE, 10 + list(Result).index(result))
            item.setToolTip(STATE, "")
        flags = item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
        if self._tickable(ident):
            if not self._locked:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            on = ident in self._ticked
            item.setCheckState(TICK, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setData(TICK, SORT_ROLE, 0 if on else 1)
        else:
            item.setData(TICK, Qt.ItemDataRole.CheckStateRole, None)  # no box at all
            item.setData(TICK, SORT_ROLE, 2)
        item.setFlags(flags)
        greyed = not profile.ready or result in (Result.DELETED, Result.QUEUED)
        role = QPalette.ColorRole.PlaceholderText if greyed else QPalette.ColorRole.Text
        brush = QBrush(self.palette().color(role))
        if careful and not self._light():
            brush = QBrush(QColor(AMBER))
        for column in (USER, USED, KIND):
            item.setForeground(column, brush)
        item.setForeground(STATE, QBrush(QColor(AMBER)) if careful else brush)
        if not item.data(SIZE, COUNTING_ROLE):
            item.setForeground(SIZE, brush)

    def _light(self) -> bool:
        """A light theme: amber is too faint as text there, so rows keep their text colour."""
        return self.palette().color(QPalette.ColorRole.Base).lightness() > 128

    def _fill_size(
        self, item: QTreeWidgetItem, ident: str, sizes: dict[str, int | None], so_far: int = 0
    ) -> None:
        profile = self._profiles[ident]
        muted = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
        normal = QBrush(self.palette().color(QPalette.ColorRole.Text))
        item.setData(SIZE, COUNTING_ROLE, ident in sizes and sizes[ident] is None)
        if ident not in sizes:
            item.setText(SIZE, "")
            item.setData(SIZE, SORT_ROLE, -1)
            return
        size = sizes[ident]
        if size is None:
            item.setText(SIZE, rows.size_text(so_far) + "…" if so_far else _("counting…"))
            item.setForeground(SIZE, muted)
            item.setData(SIZE, SORT_ROLE, -1)
        else:
            greyed = not profile.ready or self._results.get(ident) is Result.DELETED
            careful = bool(item.data(USER, CAREFUL_ROLE)) and not self._light()
            item.setText(SIZE, rows.size_text(size))
            item.setForeground(
                SIZE, QBrush(QColor(AMBER)) if careful else muted if greyed else normal
            )
            item.setData(SIZE, SORT_ROLE, size)


# ---- a profile's details ----


@dataclass(frozen=True)
class Shown:
    """What Details shows of one row."""

    profile: Profile
    root: str  # the PC's Users folder
    size: int | None  # bytes, once counted
    counting: bool = False
    result: Result | None = None  # where it stands in a delete run
    done: Deleted | None = None  # how its delete ended


class ProfileDetails(DetailsPanel):
    def __init__(self) -> None:
        self._hint_text = ""
        super().__init__()

    def pick_hint(self) -> str:
        return self._hint_text or _("Select a profile to see its details.")

    def selected_text(self, selected: int) -> str:
        return _("{n} profiles selected").format(n=selected)

    def item_id(self, shown: object) -> str:
        return shown.profile.ident if isinstance(shown, Shown) else ""

    def show_hint(self, text: str) -> None:
        """Nothing picked: `text` in the middle of the panel."""
        self._hint_text = text
        self.show_item(None, 0)

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, Shown)
        profile, result = shown.profile, shown.result
        name = self.value("name", profile.user)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        color = rows.RESULT_ICONS[result][1] if result else rows.STATE_COLORS[profile.state]
        dot = QLabel()
        dot.setPixmap(dot_icon(color, 12).pixmap(12, 12))
        top = QHBoxLayout()
        top.setSpacing(4)
        if result is not None or profile.state is not State.READY:
            top.addWidget(dot)
        else:  # no dot, as the table: the name starts where the line under it does
            # Its padding and the label's own edge would start it 4 px further in.
            name.setStyleSheet("QLabel#copyValue { padding-left: 0px; margin-left: -4px; }")
        top.addWidget(name, 1)
        layout.addLayout(top)
        state = _(rows.RESULT_NAMES[result]) if result else rows.state_name(profile.state)
        layout.addWidget(self.muted(f"{state} · {_(rows.KIND_NAMES[profile.kind])}"))

        if result is not None:
            self.section(layout, _("Result"))
            if shown.done is not None:
                layout.addWidget(self.muted(rows.result_why(shown.done)))
                if shown.done.detail and shown.done.outcome is not Outcome.DELETED:
                    layout.addSpacing(4)
                    layout.addWidget(self.muted(_("Windows answered:")))
                    layout.addWidget(self.value("windows", shown.done.detail))
            else:
                layout.addWidget(self.muted(_(rows.RESULT_NAMES[result])))
        else:
            self.section(layout, _("State"))
            layout.addWidget(self.muted(rows.state_why(profile, shown.root)))

        self.section(layout, _("Account"))
        account = self.value("account", profile.user) if profile.known else self.muted(_("Unknown"))
        sid = self.value("sid", profile.sid) if profile.sid else self.muted("—")
        self._pairs(layout, ((_("Account"), account), (_("SID"), sid)))
        if not profile.known and profile.sid:
            layout.addWidget(
                self.muted(_("Windows no longer knows this account; it was probably deleted."))
            )

        self.section(layout, _("Folder"))
        used, changed = rows.date_text(profile.last_used), rows.date_text(profile.modified)
        if shown.counting:
            size: QLabel = self.muted(_("counting…"))
        elif shown.size is None:
            size = self.muted(_("Not counted"))
        else:
            size = self.value("size", rows.size_text(shown.size))
        self._pairs(
            layout,
            (
                (_("Path"), self.value("path", profile.path) if profile.path else self.muted("—")),
                (_("Last used"), self.value("used", used) if used else self.muted("—")),
                (_("Folder changed"), self.value("changed", changed) if changed
                 else self.muted("—")),
                (_("Size"), size),
            ),
        )  # fmt: skip

        if result is None:
            self.section(layout, _("Kind"))
            layout.addWidget(self.muted(_(rows.KIND_WHY[profile.kind])))

    def _pairs(self, layout: QVBoxLayout, pairs: Sequence[tuple[str, QLabel]]) -> None:
        """A label on the left, its value on the same line, every value at the same x."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 92)
        for index, (label, value) in enumerate(pairs):
            name = QLabel(label)
            name.setObjectName("hint")
            name.setContentsMargins(0, 2, 0, 2)
            if value.objectName() == "hint":
                value.setContentsMargins(7, 2, 4, 2)  # as a copyable value's padding
            grid.addWidget(name, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, index, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(grid)


# ---- deleting ----


class DeleteDialog(Question):
    """The question before profiles are deleted: which ones, that it's final, and a word to
    type. Cancel is the default until the word is there; then the amber button lights, takes
    the keyboard and becomes the default, so the Enter that follows deletes."""

    def __init__(
        self, parent: QWidget | None, host: str, profiles: Sequence[Profile], sizes: dict[str, int]
    ) -> None:
        n = len(profiles)
        super().__init__(
            parent,
            _("Delete profiles from {host}").format(host=host),
            ngettext(
                "Delete {n} profile from {host}?", "Delete {n} profiles from {host}?", n
            ).format(n=n, host=host),
            _(
                "This is <b>final</b>. With local profiles, each person's desktop and documents "
                "go too: there's no recycle bin and no copy."
            ),
            ngettext("Delete {n} profile", "Delete {n} profiles", n).format(n=n),
        )
        self.table = grid_table([_("User"), _("Last used"), _("Size")])
        for profile in profiles:
            size = sizes.get(profile.ident)
            self.table.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        rows.user_text(profile),
                        rows.date_text(profile.last_used) or "—",
                        rows.size_text(size) if size is not None else "",
                    ]
                )
            )
        total = ngettext("{n} profile", "{n} profiles", n).format(n=n)
        counted = [sizes[p.ident] for p in profiles if p.ident in sizes]
        if counted and len(counted) == n:
            total += " · " + rows.size_text(sum(counted))
        elif counted:
            total += " · " + _("{size} in the {n} counted").format(
                size=rows.size_text(sum(counted)), n=len(counted)
            )
        self.total = hint(total)
        note = hint(
            _(
                "The host is checked again before each delete: anyone who signed in since the "
                "scan is skipped. Every delete goes in the history."
            )
        )
        self.word = QLineEdit()
        ask = QLabel(_("To confirm, type <b>{word}</b>:").format(word=escape(rows.confirm_word())))
        self.body.addSpacing(4)
        for widget in (self.table, self.total, note):
            self.body.addWidget(widget)
        self.body.addSpacing(6)
        self.body.addWidget(ask)
        self.body.addWidget(self.word)
        self.action.setEnabled(False)
        self.word.textChanged.connect(self._word_changed)
        self.resize(540, 10)
        fit_rows(self.table)
        self.word.setFocus()

    def _word_changed(self, text: str) -> None:
        typed = rows.confirms(text)
        self.action.setEnabled(typed)
        self.action.setDefault(typed)
        self.cancel.setDefault(not typed)
        if typed:  # it looks in focus once lit: it really is, so Enter isn't Cancel
            self.action.setFocus()

    def accept(self) -> None:
        if rows.confirms(self.word.text()):  # never by a stray Enter on a greyed button
            super().accept()
