"""The one table design for lists in windows like Settings: lines between rows and columns as
in the host table, a header, a few rows before it scrolls, the full width of the page, its main
actions in a row of buttons under it, and every action of a row on its right-click."""

from collections.abc import Callable

from PySide6.QtCore import QPoint, Qt
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

from capypanel.ui.menus import popup

MOST_ROWS = 6  # taller lists scroll
FEWEST_ROWS = 3  # a short list still looks like a list
WIDEST = 260  # a column fits its text up to this; the last one takes what's left


def grid_table(headers: list[str]) -> QTreeWidget:
    """A table in the app's one style: grid lines, resizable columns, one row picked at a time."""
    table = QTreeWidget()
    table.setObjectName("grid")  # the stylesheet draws the lines
    table.setRootIsDecorated(False)
    table.setHeaderLabels(headers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    header = table.header()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # drag to resize
    header.setStretchLastSection(True)
    # No sideways scrolling: long text is cut with "…", its whole text in the tooltip.
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return table


def fit_rows(table: QTreeWidget) -> None:
    """As tall as its rows, between FEWEST_ROWS and MOST_ROWS: no empty space under a short
    list, a scroll bar on a long one. Each column but the last fits its text, up to WIDEST.
    Call it after filling the table."""
    for column in range(table.columnCount() - 1):
        table.resizeColumnToContents(column)
        table.setColumnWidth(column, min(table.columnWidth(column) + 12, WIDEST))
    rows = min(max(table.topLevelItemCount(), FEWEST_ROWS), MOST_ROWS)
    first = table.topLevelItem(0)
    row = table.sizeHintForRow(0) if first is not None else -1
    if row <= 0:
        row = table.fontMetrics().height() + 16  # the stylesheet pads each row
    # The header, exactly `rows` rows (a 7th never peeks in), and the frame.
    table.setFixedHeight(table.header().sizeHint().height() + rows * row + 2 * table.frameWidth())


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
