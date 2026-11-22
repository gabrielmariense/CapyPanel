from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QItemSelectionModel,
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
    QAbstractItemView,
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
from capypanel.core.remote.user_profiles import Deleted, Outcome, Profile, State
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.hosts_tool.runner import escape
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import natural_key
from capypanel.ui.menus import popup
from capypanel.ui.notes import divider, hint
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.rows import Filters, Result
from capypanel.ui.tables import fit_rows, grid_table
from capypanel.ui.themes import engine as themes

LEFT, RIGHT = 234, 284
DETAILS = 340
TICK, USER, USED, SIZE, STATE = range(5)
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
ARROW = 16
IDENT_ROLE = Qt.ItemDataRole.UserRole
CAREFUL_ROLE = Qt.ItemDataRole.UserRole + 2  # ticked: deleted on Delete…
COUNTING_ROLE = Qt.ItemDataRole.UserRole + 3
INFO = 22
INFO_GAP = 4


def amber() -> str:
    return themes.status_color("attention")


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setBackgroundRole(QPalette.ColorRole.Base)
    frame.setAutoFillBackground(True)
    return frame


def _fold(text: str) -> str:
    return text.strip().casefold()


def second_line_height() -> int:
    return max(QLineEdit().sizeHint().height(), QComboBox().sizeHint().height())


class TabBox(QFrame):
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
        column.addWidget(divider())
        column.addWidget(body, 1)

    def show_title(self, name: str, about: str) -> None:
        self.name.setText(name)
        self.about.setText(about)


class Squeeze(QObject):
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
        self._full: dict[int, int] = {}
        self._narrow_widths: dict[int, int] = {}
        self._narrow = False
        self._busy = False
        tree.viewport().installEventFilter(self)
        tree.header().sectionResized.connect(self._dragged)

    def set_full(self) -> None:
        last = self._tree.columnCount() - 1
        self._full = {c: self._tree.columnWidth(c) for c in range(last)}
        self._tree.header().setStretchLastSection(False)
        self.apply()

    def set_narrow_width(self, column: int, width: int) -> None:
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
    GAP = 5
    BIN = 14

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._short = ""
        self._least = ""
        self._ticked = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def show_count(self, text: str, ticked: bool, short: str = "", least: str = "") -> None:
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
            QColor(amber())
            if self._ticked
            else self.palette().color(QPalette.ColorRole.PlaceholderText)
        )
        width = self.fontMetrics().horizontalAdvance(shown)
        left = self.width() - width
        if self._ticked:
            icon = tabler_icon("trash", QColor(amber()), self.BIN)
            left -= self.BIN + self.GAP
            top = (self.height() - self.BIN) // 2
            icon.paint(painter, left, top, self.BIN, self.BIN)
            left += self.BIN + self.GAP
        painter.setPen(color)
        painter.drawText(left, 0, width, self.height(), Qt.AlignmentFlag.AlignVCenter, shown)
        painter.end()


class FilterRow(QWidget):
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
        row.addWidget(self.shown, 1)
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


class _Row(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else USER
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine == theirs:
            names = self.data(USER, SORT_ROLE), other.data(USER, SORT_ROLE)
            down = tree is not None and (
                tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return bool(names[1] < names[0]) if down else bool(names[0] < names[1])
        return bool(mine < theirs)


def info_rect(cell: QRect) -> QRect:
    return QRect(cell.right() - INFO - INFO_GAP + 1, cell.top() + (cell.height() - INFO) // 2,
                 INFO, INFO)  # fmt: skip


class _Careful(QStyledItemDelegate):
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
            corner = themes.current().control
            painter.drawRoundedRect(box, corner, corner)
            icon = tabler_icon("info-circle", palette.color(QPalette.ColorRole.ButtonText), 16)
            icon.paint(painter, box.adjusted(3, 3, -3, -3))
            painter.restore()
        if model is None or not model.index(index.row(), USER, index.parent()).data(CAREFUL_ROLE):
            return
        painter.save()
        painter.setPen(QPen(QColor(amber()), 2))
        top, bottom = rect.top() + 1, rect.bottom() - 2  # above the grid's 2 px line
        painter.drawLine(rect.left(), top, rect.right(), top)
        painter.drawLine(rect.left(), bottom, rect.right(), bottom)
        if index.column() == TICK:
            painter.drawLine(rect.left() + 1, top, rect.left() + 1, bottom)
        if index.column() == STATE:
            painter.drawLine(rect.right(), top, rect.right(), bottom)
        painter.restore()

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            return False
        return super().editorEvent(event, model, option, index)

    def helpEvent(  # type: ignore[override]
        self,
        event: QHelpEvent,
        view: object,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
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
    picked = Signal()
    ticked_changed = Signal()
    details_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 5)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setFrameShape(QFrame.Shape.NoFrame)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.squeeze = Squeeze(self.tree, ((USER, 110),), self._state_least)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(USED, Qt.SortOrder.DescendingOrder)
        self._sorted = (USED, Qt.SortOrder.DescendingOrder)
        self.tree.header().sortIndicatorChanged.connect(self._sort_picked)
        self.tree.setItemDelegate(_Careful(self.tree))
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemChanged.connect(self._changed)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.installEventFilter(self)
        self.tree.viewport().installEventFilter(self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self._info_pressed = ""
        self._profiles: dict[str, Profile] = {}
        self._ticked: set[str] = set()
        self._results: dict[str, Result] = {}
        self._locked = False
        self._fitted = False
        self._root = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.retranslate()

    def retranslate(self) -> None:
        self.tree.setHeaderLabels(["", _("User"), _("Last used"), _("Size"), _("State")])
        header = self.tree.headerItem()
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        header.setIcon(TICK, tabler_icon("trash", muted, 14))
        header.setToolTip(
            TICK,
            _("Tick to delete: the box, a double-click on the row, or Space on the selected rows"),
        )

    def _sort_picked(self, column: int, order: Qt.SortOrder) -> None:
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
        self._root = root
        kept = {item.data(USER, IDENT_ROLE) for item in self.tree.selectedItems()}
        current = self.selected()
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
            item.setSelected(profile.ident in kept)
            if current is not None and profile.ident == current.ident:
                self.tree.setCurrentItem(item, TICK, QItemSelectionModel.SelectionFlag.NoUpdate)
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        if not self._fitted and profiles:
            self.fit()
        self.picked.emit()
        if before != self._ticked:
            self.ticked_changed.emit()

    def show_size(self, ident: str, sizes: dict[str, int | None], so_far: int = 0) -> None:
        item = self._item(ident)
        if item is not None:
            self._fill_size(item, ident, sizes, so_far)

    def show_result(self, ident: str, result: Result | None) -> None:
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
        self._locked = locked
        self.tree.blockSignals(True)
        for ident in self._profiles:
            item = self._item(ident)
            if item is not None:
                self._fill_state(item, self._profiles[ident])
        self.tree.blockSignals(False)

    def fit(self) -> None:
        header = self.tree.header()
        header.setSortIndicatorShown(False)
        for column in range(USER, STATE):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, self.tree.columnWidth(column) + 6)
        header.setSortIndicatorShown(True)
        sorted_by = header.sortIndicatorSection()
        if USER <= sorted_by < STATE:
            self.tree.setColumnWidth(sorted_by, self.tree.columnWidth(sorted_by) + ARROW)
        self.tree.setColumnWidth(TICK, 34)
        widest = max(
            self.tree.fontMetrics().horizontalAdvance(text)
            for text in (_("counting…"), rows.size_text(888 * rows.GB))
        )
        self.tree.setColumnWidth(SIZE, max(self.tree.columnWidth(SIZE), widest + 20))
        self._fitted = True
        self.squeeze.set_full()

    def _state_least(self) -> int:
        words = [rows.state_name(state) for state in rows.STATE_ORDER]
        words += [_(name) for name in rows.RESULT_NAMES.values()]
        words += [_("Will be deleted"), _("State")]
        metrics = self.tree.fontMetrics()
        widest = max(metrics.horizontalAdvance(word) for word in words)
        return widest + 16 + 26 + INFO + INFO_GAP

    def selected(self) -> Profile | None:
        item = self.tree.currentItem()
        return self._profiles.get(item.data(USER, IDENT_ROLE)) if item is not None else None

    def shown(self) -> list[Profile]:
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [self._profiles[item.data(USER, IDENT_ROLE)] for item in found if item]

    def ticked(self) -> list[Profile]:
        return [p for p in self.shown() if p.ident in self._ticked]

    def tick(self, ident: str, on: bool = True) -> None:
        self.tick_rows([ident], on)

    def tick_rows(self, idents: Sequence[str], on: bool) -> None:
        changed = False
        self.tree.blockSignals(True)
        for ident in idents:
            item = self._item(ident)
            if item is None or not self.can_tick(ident) or (ident in self._ticked) == on:
                continue
            (self._ticked.add if on else self._ticked.discard)(ident)
            self._fill_state(item, self._profiles[ident])
            changed = True
        self.tree.blockSignals(False)
        if changed:
            self.ticked_changed.emit()

    def toggle(self, ident: str) -> None:
        self.tick(ident, ident not in self._ticked)

    def profile(self, ident: str) -> Profile | None:
        return self._profiles.get(ident)

    def is_ticked(self, ident: str) -> bool:
        return ident in self._ticked

    def can_tick(self, ident: str) -> bool:
        return self._tickable(ident) and not self._locked

    def select(self, ident: str) -> None:
        item = self._item(ident)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def info_box(self, ident: str) -> QRect | None:
        item = self._item(ident)
        if item is None or item is not self.tree.currentItem():
            return None
        cell = self.tree.visualItemRect(item)
        left = self.tree.columnViewportPosition(STATE)
        return info_rect(QRect(left, cell.top(), self.tree.columnWidth(STATE), cell.height()))

    def info_at(self, point: QPoint) -> str:
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
            control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
            if event.key() == Qt.Key.Key_Space and not control:  # Ctrl+Space selects, as in Qt
                self._tick_picked()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and current is not None:
                self.details_requested.emit(current.data(USER, IDENT_ROLE))
                return True
        if (
            watched is self.tree.viewport()
            and isinstance(event, QMouseEvent)
            and event.button() == Qt.MouseButton.LeftButton
        ):
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

    def _tick_picked(self) -> None:
        items = self.tree.selectedItems() or [self.tree.currentItem()]
        idents = [item.data(USER, IDENT_ROLE) for item in items if item is not None]
        idents = [ident for ident in idents if self.can_tick(ident)]
        if idents:
            self.tick_rows(idents, not all(ident in self._ticked for ident in idents))

    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != TICK:
            self.toggle(item.data(USER, IDENT_ROLE))

    def texts(self) -> list[list[str]]:
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [[item.text(c) for c in range(STATE + 1)] for item in found if item]

    def _item(self, ident: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(USER, IDENT_ROLE) == ident:
                return item
        return None

    def _tickable(self, ident: str) -> bool:
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
        self._fill_state(item, self._profiles[ident])
        self.tree.blockSignals(False)
        self.ticked_changed.emit()

    def _fill(self, item: QTreeWidgetItem, profile: Profile, sizes: dict[str, int | None]) -> None:
        item.setText(USER, rows.user_text(profile))
        item.setToolTip(USER, rows.user_text(profile))
        item.setData(USER, SORT_ROLE, natural_key(profile.user))
        item.setText(USED, rows.date_text(profile.last_used) or "—")
        used = profile.last_used.timestamp() if profile.last_used else float("-inf")
        item.setData(USED, SORT_ROLE, used)
        item.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._fill_state(item, profile)
        self._fill_size(item, profile.ident, sizes)

    def _fill_state(self, item: QTreeWidgetItem, profile: Profile) -> None:
        ident, result = profile.ident, self._results.get(profile.ident)
        careful = result is None and ident in self._ticked and self._tickable(ident)
        item.setData(USER, CAREFUL_ROLE, careful)
        if careful:
            item.setText(STATE, _("Will be deleted"))
            item.setIcon(STATE, tabler_icon("trash", QColor(amber()), 16))
            item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
            item.setToolTip(STATE, _("Ticked: it's deleted once you click Delete and confirm"))
        elif result is None:
            item.setText(STATE, rows.state_name(profile.state))
            ready = profile.state is State.READY
            item.setIcon(STATE, QIcon() if ready else dot_icon(rows.state_color(profile.state), 10))
            item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
            item.setToolTip(STATE, rows.state_why(profile, self._root))
        else:
            icon, color = rows.result_icon(result)
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
            item.setData(TICK, Qt.ItemDataRole.CheckStateRole, None)
            item.setData(TICK, SORT_ROLE, 2)
        item.setFlags(flags)
        greyed = not profile.ready or result in (Result.DELETED, Result.QUEUED)
        role = QPalette.ColorRole.PlaceholderText if greyed else QPalette.ColorRole.Text
        brush = QBrush(self.palette().color(role))
        if careful:
            brush = QBrush(QColor(amber()))
        for column in (USER, USED):
            item.setForeground(column, brush)
        item.setForeground(STATE, brush)
        if not item.data(SIZE, COUNTING_ROLE):
            item.setForeground(SIZE, brush)

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
            careful = bool(item.data(USER, CAREFUL_ROLE))
            item.setText(SIZE, rows.size_text(size))
            item.setForeground(
                SIZE, QBrush(QColor(amber())) if careful else muted if greyed else normal
            )
            item.setData(SIZE, SORT_ROLE, size)


@dataclass(frozen=True)
class Shown:
    profile: Profile
    root: str
    size: int | None
    counting: bool = False
    result: Result | None = None
    done: Deleted | None = None


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

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, Shown)
        profile, result = shown.profile, shown.result
        name = self.value("name", profile.user)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        color = rows.result_icon(result)[1] if result else rows.state_color(profile.state)
        dot = QLabel()
        dot.setPixmap(dot_icon(color, 12).pixmap(12, 12))
        top = QHBoxLayout()
        top.setSpacing(4)
        if result is not None or profile.state is not State.READY:
            top.addWidget(dot)
        else:
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
                value.setContentsMargins(7, 2, 4, 2)
            grid.addWidget(name, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, index, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(grid)


class DeleteDialog(Question):
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
            place="profiles-delete-profiles",
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
        if typed:
            self.action.setFocus()

    def accept(self) -> None:
        if rows.confirms(self.word.text()):  # never by a stray Enter on a greyed button
            super().accept()
