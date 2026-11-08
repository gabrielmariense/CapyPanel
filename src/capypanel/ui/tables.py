"""The one table design for lists in windows like Settings: lines between rows and columns as
in the host table, a header, a few rows before it scrolls, the full width of the page, its main
actions in a row of buttons under it, and every action of a row on its right-click."""

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.menus import popup

MOST_ROWS = 6  # taller lists scroll
FEWEST_ROWS = 3  # a short list still looks like a list
WIDEST = 480  # px: only a paragraph (a license notice) is cut, its whole text in the tooltip
_FITS = "fitWidths"  # property: each column's width for its text, set by fit_rows


class _Refit(QObject):
    """Fits the columns again when the table changes width: the last one takes the room left."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            table = watched.parent() if not isinstance(watched, QTreeWidget) else watched
            if isinstance(table, QTreeWidget):
                _fit_width(table)
        return False


def grid_table(headers: list[str]) -> QTreeWidget:
    """A table in the app's one style: grid lines, resizable columns, one row picked at a time.
    Every column shows its whole text; when they can't all fit, the table scrolls sideways."""
    table = QTreeWidget()
    table.setObjectName("grid")  # the stylesheet draws the lines
    table.setRootIsDecorated(False)
    table.setHeaderLabels(headers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    header = table.header()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # drag to resize
    header.setStretchLastSection(False)  # _fit_width gives the last column what's left
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    refit = _Refit(table)
    table.viewport().installEventFilter(refit)
    fit_menu(table)
    return table


def fit_menu(table: QTreeWidget) -> None:
    """Right-click on the column titles > Fit columns to content, as in the host and printer
    tables: every column back to its full text."""

    def show(point: QPoint) -> None:
        menu = QMenu(table)
        menu.addAction(_("&Fit columns to content"), lambda: fit_columns(table))
        popup(menu, header.viewport().mapToGlobal(point))

    header = table.header()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.customContextMenuRequested.connect(show)


def fit_columns(table: QTreeWidget) -> None:
    if table.property(_FITS) is not None:  # a grid_table: fitted and stretched as at first
        fit_rows(table)
        return
    for column in range(table.columnCount()):
        if not table.isColumnHidden(column):
            table.resizeColumnToContents(column)


def fit_rows(table: QTreeWidget) -> None:
    """As tall as its rows, between FEWEST_ROWS and MOST_ROWS: no empty space under a short
    list, a scroll bar on a long one. Each column fits its text (up to WIDEST), the last one
    stretching into the room left. Call it after filling the table."""
    fits = []
    for column in range(table.columnCount()):
        table.resizeColumnToContents(column)
        fits.append(min(table.columnWidth(column) + 12, WIDEST))
    table.setProperty(_FITS, fits)
    _fit_width(table)


def _fit_width(table: QTreeWidget) -> None:
    fits = table.property(_FITS)
    if not isinstance(fits, list) or len(fits) != table.columnCount():
        return
    for column, width in enumerate(fits[:-1]):
        table.setColumnWidth(column, width)
    room = table.viewport().width() - sum(fits[:-1])
    table.setColumnWidth(len(fits) - 1, max(fits[-1], room))
    rows = min(max(table.topLevelItemCount(), FEWEST_ROWS), MOST_ROWS)
    first = table.topLevelItem(0)
    row = table.sizeHintForRow(0) if first is not None else -1
    if row <= 0:
        row = table.fontMetrics().height() + 16  # the stylesheet pads each row
    # The header, exactly `rows` rows (a 7th never peeks in), the frame, and the sideways
    # scroll bar when the columns are wider than the table.
    across = table.horizontalScrollBar().sizeHint().height() if room < fits[-1] else 0
    height = table.header().sizeHint().height() + rows * row + 2 * table.frameWidth() + across
    if table.height() != height or table.minimumHeight() != height:
        table.setFixedHeight(height)


def row_menu(table: QTreeWidget, fill: Callable[[QMenu], None]) -> None:
    """A right-click on a row picks it and opens its menu, which `fill` builds. The menu key
    opens it for the row picked."""

    def show(point: QPoint) -> None:
        item = table.itemAt(point) or table.currentItem()
        if item is None:
            return
        table.setCurrentItem(item)
        menu = QMenu(table)
        fill(menu)
        at = table.visualItemRect(item).bottomLeft() if table.itemAt(point) is None else point
        popup(menu, table.viewport().mapToGlobal(at))  # freed once closed

    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show)


def add_action(menu: QMenu, text: str, run: Callable[[], object], enabled: bool = True) -> None:
    action = menu.addAction(text)
    action.setEnabled(enabled)
    action.triggered.connect(lambda _c=False: run())


def with_buttons(table: QTreeWidget, buttons: list[QPushButton]) -> QWidget:
    """The table at full width, its buttons in a row under it, from the left."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    for button in buttons:
        button.setAutoDefault(False)  # Enter never runs one by surprise
        row.addWidget(button)
    row.addStretch(1)
    box = QWidget()
    column = QVBoxLayout(box)
    column.setContentsMargins(0, 0, 0, 0)
    column.addWidget(table)
    column.addLayout(row)
    return box
