"""Settings › Printers › Warnings and supplies, its Warnings section: one row per reason a printer
can be warned about, A to Z, with a tick for In CapyPanel (the red count on the Printers icon and
the strip above the table) and one for the Windows notification."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.notes import notes
from capypanel.ui.printers_tool.status import DEFAULT_REASONS, Reason
from capypanel.ui.tables import grid_table, with_buttons

HERE, NOTIFY = 1, 2  # the tick columns
_REASON = Qt.ItemDataRole.UserRole


def _tips() -> dict[Reason, str]:
    return {
        Reason.STOPPED: _("Stopped without saying why."),
        Reason.OFFLINE: _("Didn't answer the Refresh."),
        Reason.LOW: _("At or below the Low supply level, under Supplies."),
    }


class CentredTick(QStyledItemDelegate):
    """The theme's own tick box in the middle of its cell; a click anywhere on the cell, or
    Space on it, ticks or unticks it."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget  # type: ignore[attr-defined]
        style = widget.style() if widget else QApplication.style()
        box = style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, widget)
        opt.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator  # type: ignore[attr-defined]
        opt.text = ""  # type: ignore[attr-defined]
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        tick = QStyleOptionViewItem(opt)
        tick.rect = QRect(QPoint(0, 0), box.size() if box.width() > 0 else QSize(16, 16))  # type: ignore[attr-defined]
        tick.rect.moveCenter(option.rect.center())  # type: ignore[attr-defined]
        on = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, 2)
        flags = tick.state & ~(QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off)  # type: ignore[attr-defined]
        tick.state = flags | (QStyle.StateFlag.State_On if on else QStyle.StateFlag.State_Off)  # type: ignore[attr-defined]
        style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck, tick, painter,
                            widget)  # fmt: skip

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        clicked = (
            isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and option.rect.contains(event.position().toPoint())  # type: ignore[attr-defined]
        )
        pressed = isinstance(event, QKeyEvent) and event.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Select,
        )
        if not (clicked or pressed):
            # The press and double-click a click brings stay here, so they never tick twice.
            return isinstance(event, QMouseEvent) and event.type() in (
                QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick
            )  # fmt: skip
        on = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, 2)
        state = Qt.CheckState.Unchecked if on else Qt.CheckState.Checked
        return model.setData(index, state, Qt.ItemDataRole.CheckStateRole)


class WarningsTable(QWidget):
    """The note, the table shown whole (fixed choices: the page scrolls, not the table) and
    Restore default, greyed while the default ticks are what's ticked."""

    changed = Signal()

    def __init__(self, here: frozenset[Reason], notify: frozenset[Reason]) -> None:
        super().__init__()
        self.table = table = grid_table([_("Reason"), _("In CapyPanel"), _("Windows notification")])
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )  # Space ticks a cell
        head = table.headerItem()
        delegate = CentredTick(table)
        for column in (HERE, NOTIFY):  # no tips on the titles (Gabriel, 2026-11-13)
            head.setTextAlignment(column, Qt.AlignmentFlag.AlignCenter)
            table.setItemDelegateForColumn(column, delegate)
        words = {reason: reason.words() for reason in Reason}
        for reason in sorted(Reason, key=lambda r: words[r].casefold()):
            row = QTreeWidgetItem([words[reason], "", ""])
            row.setData(0, _REASON, reason.value)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setToolTip(0, _tips().get(reason, ""))
            table.addTopLevelItem(row)
        self.restore = QPushButton(_("&Restore default"))
        self._tick(here, notify, say=False)
        header = table.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Both tick columns as wide as the wider title, so the ticks sit in two even columns.
        widest = max(header.fontMetrics().horizontalAdvance(head.text(c)) for c in (HERE, NOTIFY))
        for column in (HERE, NOTIFY):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(column, widest + 48)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_h = table.sizeHintForRow(0)
        if row_h <= 0:
            row_h = table.fontMetrics().height() + 16  # the stylesheet pads each row
        table.setFixedHeight(
            header.sizeHint().height() + table.topLevelItemCount() * row_h
            + 2 * table.frameWidth()
        )  # fmt: skip
        self.restore.clicked.connect(lambda: self._tick(DEFAULT_REASONS, DEFAULT_REASONS))
        table.itemChanged.connect(self._ticked)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(
            notes(_("Which reasons count as a warning. The table's Status always shows every one."))
        )
        column.addWidget(with_buttons(table, [self.restore]))

    def _rows(self) -> list[tuple[Reason, QTreeWidgetItem]]:
        items = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [(Reason(item.data(0, _REASON)), item) for item in items if item is not None]

    def _ticked_in(self, column: int) -> frozenset[Reason]:
        return frozenset(
            r for r, item in self._rows() if item.checkState(column) == Qt.CheckState.Checked
        )

    def here(self) -> frozenset[Reason]:
        return self._ticked_in(HERE)

    def notify(self) -> frozenset[Reason]:
        return self._ticked_in(NOTIFY)

    def _tick(self, here: frozenset[Reason], notify: frozenset[Reason], say: bool = True) -> None:
        """Sets every tick, then says it changed once (`say`)."""
        self.table.blockSignals(True)
        for reason, item in self._rows():
            for column, chosen in ((HERE, here), (NOTIFY, notify)):
                state = Qt.CheckState.Checked if reason in chosen else Qt.CheckState.Unchecked
                item.setCheckState(column, state)
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update()
        if say:
            self.changed.emit()

    def _ticked(self, *_args: object) -> None:
        if self.table.signalsBlocked():
            return
        self._update()
        self.changed.emit()

    def _update(self) -> None:
        self.restore.setEnabled((self.here(), self.notify()) != (DEFAULT_REASONS, DEFAULT_REASONS))
