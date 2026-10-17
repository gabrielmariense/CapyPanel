"""The one table design for lists in windows like Settings: lines between rows and columns as
in the host table, a header, a few rows before it scrolls, and its actions in a column of
buttons beside it."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

MOST_ROWS = 6  # taller lists scroll
FEWEST_ROWS = 3  # a short list still looks like a list
WIDEST = 230  # a column fits its text up to this; the last one takes what's left
BUTTONS_WIDTH = 150  # every table's button column: tables on a page line up


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
    # The header, the rows, and the table's frame and padding.
    frame = 2 * table.frameWidth() + 12
    table.setFixedHeight(table.header().sizeHint().height() + rows * (row + 2) + frame)


def with_buttons(table: QTreeWidget, buttons: list[QPushButton]) -> QWidget:
    """The table, its buttons in a column on its right, top-aligned."""
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    for button in buttons:
        button.setAutoDefault(False)  # Enter never runs one by surprise
        button.setMinimumWidth(BUTTONS_WIDTH)
        column.addWidget(button)
    column.addStretch(1)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(table, 1, Qt.AlignmentFlag.AlignTop)
    row.addLayout(column)
    return box
