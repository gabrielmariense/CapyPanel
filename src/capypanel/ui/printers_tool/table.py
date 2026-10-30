"""The printer table: name, address, Status, Toner, brand, model and tags; serial number and
asset tag can be shown from the column titles' right-click menu. Status and Toner come from
Refresh; they're kept in memory, never in the list file."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidgetItem,
)

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.printers.printer import info_of
from capypanel.core.printers.reading import Supply
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.panels import ItemTable
from capypanel.ui.printers_tool.meter import HEIGHT, draw_meter
from capypanel.ui.printers_tool.status import AMBER, DEFAULT_LOW, Cell, level_text, plain_tip

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2  # a Status cell to show greyed
ROLE_WARN = Qt.ItemDataRole.UserRole + 3  # a Toner cell to show in amber
ROLE_SUPPLY = Qt.ItemDataRole.UserRole + 4  # a Toner cell's supply, drawn as a bar
BAR_WIDTH = 64  # px: the Toner column's bar when fitted to content; it stretches with the column
MIN_BAR = 16  # px: narrower than this, the bar gives way and only the words show
GAP = 8  # px between the bar and its words


class PrinterTable(ItemTable):
    ADDRESS, STATUS, TONER, BRAND, MODEL, SERIAL, ASSET_TAG, TAGS = 1, 2, 3, 4, 5, 6, 7, 8
    COLUMNS = ("name", "address", "status", "toner", "brand", "model", "serial", "asset_tag",
               "tags")  # fmt: skip
    HIDDEN = ("serial", "asset_tag")  # until the user shows them
    # What a search marks and finds: every column but the ones Refresh fills.
    SEARCHED = frozenset({0, ADDRESS, BRAND, MODEL, SERIAL, ASSET_TAG, TAGS})
    EMPTY = {STATUS: 14, TONER: 16}  # empty until a Refresh: room for what it brings

    def __init__(self) -> None:
        self._cells: Callable[[str], tuple[Cell, Cell]] = lambda _id: (_EMPTY, _EMPTY)
        self.bars = False  # the Toner column as a bar (Settings › Printers), not text
        self.low = DEFAULT_LOW  # where the bar's tick goes
        super().__init__()
        self.setItemDelegateForColumn(self.TONER, TonerBar(self))

    def retranslate(self) -> None:
        self.setHeaderLabels(
            [
                _("Name"),
                _("Address"),
                _("Status"),
                _("Toner"),
                _("Brand"),
                _("Model"),
                _("Serial number"),
                _("Asset tag"),
                _("Tags"),
            ]
        )

    def row_texts(self, item: Host) -> list[str]:
        info = info_of(item)
        return [
            item.name,
            item.address,
            "",
            "",
            info.brand,
            info.model,
            info.serial,
            info.asset_tag,
            ", ".join(item.tags),
        ]

    def set_hidden_columns(self, keys: object) -> None:
        super().set_hidden_columns(keys if isinstance(keys, list) else list(self.HIDDEN))

    def set_cells(self, cells: Callable[[str], tuple[Cell, Cell]]) -> None:
        """Where each printer's Status and Toner come from, by printer id."""
        self._cells = cells

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        self._fill(row, *self._cells(item.id))

    def show_cells(self, printer_id: str) -> None:
        """New Refresh results for one printer, without rebuilding the table."""
        row = self._rows.get(printer_id)
        if row is not None:
            self._fill(row, *self._cells(printer_id))  # columns keep their widths

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:  # the quiet colour of the new theme
            for row in self._rows.values():
                self._tint(row)

    def _fill(self, row: QTreeWidgetItem, status: Cell, toner: Cell) -> None:
        row.setText(self.STATUS, status.text)
        row.setToolTip(self.STATUS, plain_tip(status.tip))
        row.setIcon(self.STATUS, dot_icon(status.color) if status.color else QIcon())
        row.setData(self.STATUS, ROLE_QUIET, status.quiet)
        row.setText(self.TONER, toner.text)  # kept with bars too: it's what Copy and sorting use
        row.setToolTip(self.TONER, plain_tip(toner.tip))
        bar = self.bars and toner.supply is not None
        row.setIcon(self.TONER, swatch(toner.color) if toner.color and not bar else QIcon())
        row.setData(self.TONER, ROLE_WARN, toner.warn)
        row.setData(self.TONER, ROLE_SUPPLY, toner.supply if bar else None)
        self._tint(row)

    def _tint(self, row: QTreeWidgetItem) -> None:
        """Offline and "not checked" read quieter than real results; a low toner in amber."""
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        quiet = bool(row.data(self.STATUS, ROLE_QUIET))
        row.setData(self.STATUS, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)
        warn = bool(row.data(self.TONER, ROLE_WARN))
        row.setData(self.TONER, Qt.ItemDataRole.ForegroundRole, QColor(AMBER) if warn else None)


_EMPTY = Cell("", "", "")


class TonerBar(QStyledItemDelegate):
    """A Toner cell as a bar filled to the lowest toner's level, its % beside it, drawn like
    Details' bars. A cell with no bar to draw (text chosen, nothing read) paints as usual."""

    def __init__(self, table: PrinterTable) -> None:
        super().__init__(table)
        self._table = table

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        supply = index.data(ROLE_SUPPLY)
        if not isinstance(supply, Supply):
            super().paint(painter, option, index)
            return
        text = option.palette.color(QPalette.ColorRole.Text)  # type: ignore[attr-defined]
        cell = QStyleOptionViewItem(option)  # its palette turns amber for a low one: not the bar
        self.initStyleOption(cell, index)
        cell.text = ""  # type: ignore[attr-defined]
        widget = cell.widget  # type: ignore[attr-defined]
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, cell, painter, widget)
        area = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, cell, widget)
        # The words always show in full; the bar takes what's left, so it grows and shrinks
        # with the column. Room for "100 %" on every row keeps the bars lined up.
        metrics = cell.fontMetrics  # type: ignore[attr-defined]
        said = level_text(supply)
        room = max(metrics.horizontalAdvance(said), metrics.horizontalAdvance(_widest()))
        width = area.width() - 2 - GAP - room
        words = area
        if width >= MIN_BAR:
            top = area.center().y() - HEIGHT / 2 + 1
            bar = QRectF(area.x() + 2, top, width, HEIGHT)
            back = option.palette.color(QPalette.ColorRole.Base)  # type: ignore[attr-defined]
            draw_meter(painter, bar, supply, self._table.low, text, back)
            words = area.adjusted(2 + width + GAP, 0, 0, 0)
        warn = bool(index.data(ROLE_WARN))
        painter.save()
        painter.setPen(QColor(AMBER) if warn else text)
        shown = metrics.elidedText(said, Qt.TextElideMode.ElideRight, words.width())
        painter.drawText(words, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, shown)
        painter.restore()

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Room for the bar and its words, so Fit columns to content shows both in full."""
        size = super().sizeHint(option, index)
        supply = index.data(ROLE_SUPPLY)
        if isinstance(supply, Supply):
            metrics = option.fontMetrics  # type: ignore[attr-defined]
            room = max(
                metrics.horizontalAdvance(level_text(supply)), metrics.horizontalAdvance(_widest())
            )
            size.setWidth(2 + BAR_WIDTH + GAP + room + 16)
        return size


def _widest() -> str:
    """The widest a level in % gets, in the language shown."""
    return _("{percent} %").format(percent=100)


def swatch(color: str, px: int = 10) -> QIcon:
    """A small rounded square in a toner's colour."""
    pixmap = QPixmap(px * 2, px * 2)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(QRectF(1, 1, px - 2, px - 2), 2, 2)
    painter.end()
    return QIcon(pixmap)
