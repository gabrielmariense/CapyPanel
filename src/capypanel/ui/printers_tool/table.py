"""The printer table: name, address, Status, Toner, brand, model and tags; serial number and
asset tag can be shown from the column titles' right-click menu. Status and Toner come from
Refresh; they're kept in memory, never in the list file."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QTreeWidgetItem

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.printers.printer import info_of
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.panels import ItemTable
from capypanel.ui.printers_tool.status import AMBER, Cell

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2  # a Status cell to show greyed
ROLE_WARN = Qt.ItemDataRole.UserRole + 3  # a Toner cell to show in amber


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
        super().__init__()

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
        row.setToolTip(self.STATUS, status.tip)
        row.setIcon(self.STATUS, dot_icon(status.color) if status.color else QIcon())
        row.setData(self.STATUS, ROLE_QUIET, status.quiet)
        row.setText(self.TONER, toner.text)
        row.setToolTip(self.TONER, toner.tip)
        row.setIcon(self.TONER, swatch(toner.color) if toner.color else QIcon())
        row.setData(self.TONER, ROLE_WARN, toner.warn)
        self._tint(row)

    def _tint(self, row: QTreeWidgetItem) -> None:
        """Offline and "not checked" read quieter than real results; a low toner in amber."""
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        quiet = bool(row.data(self.STATUS, ROLE_QUIET))
        row.setData(self.STATUS, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)
        warn = bool(row.data(self.TONER, ROLE_WARN))
        row.setData(self.TONER, Qt.ItemDataRole.ForegroundRole, QColor(AMBER) if warn else None)


_EMPTY = Cell("", "", "")


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
