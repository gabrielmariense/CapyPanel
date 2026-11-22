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

MOST_ROWS = 6
FEWEST_ROWS = 3
WIDEST = 480  # px: only a paragraph (a license notice) is cut, its whole text in the tooltip
_FITS = "fitWidths"
_MOST = "mostRows"
_STRETCH = "stretchColumn"


class _Refit(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            table = watched.parent() if not isinstance(watched, QTreeWidget) else watched
            if isinstance(table, QTreeWidget):
                _fit_width(table)
        return False


def grid_table(headers: list[str]) -> QTreeWidget:
    table = QTreeWidget()
    table.setObjectName("grid")
    table.setRootIsDecorated(False)
    table.setHeaderLabels(headers)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    header = table.header()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(False)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    refit = _Refit(table)
    table.viewport().installEventFilter(refit)
    fit_menu(table)
    return table


def fit_menu(table: QTreeWidget) -> None:
    def show(point: QPoint) -> None:
        menu = QMenu(table)
        menu.addAction(_("&Fit columns to content"), lambda: fit_columns(table))
        popup(menu, header.viewport().mapToGlobal(point))

    header = table.header()
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    header.customContextMenuRequested.connect(show)


def fit_columns(table: QTreeWidget) -> None:
    if table.property(_FITS) is not None:
        fit_rows(table)
        return
    for column in range(table.columnCount()):
        if not table.isColumnHidden(column):
            table.resizeColumnToContents(column)


def fit_rows(
    table: QTreeWidget,
    most: int = MOST_ROWS,
    *,
    stretch: int = -1,
    least: dict[int, int] | None = None,
) -> None:
    fits = []
    for column in range(table.columnCount()):
        table.resizeColumnToContents(column)
        width = min(table.columnWidth(column) + 12, WIDEST)
        fits.append(max(width, (least or {}).get(column, 0)))
    table.setProperty(_FITS, fits)
    table.setProperty(_MOST, most)
    table.setProperty(_STRETCH, stretch % table.columnCount())
    _fit_width(table)


def _fit_width(table: QTreeWidget) -> None:
    fits = table.property(_FITS)
    if not isinstance(fits, list) or len(fits) != table.columnCount():
        return
    stretch = table.property(_STRETCH)
    stretch = stretch if isinstance(stretch, int) else len(fits) - 1
    for column, width in enumerate(fits):
        if column != stretch:
            table.setColumnWidth(column, width)
    room = table.viewport().width() - sum(w for c, w in enumerate(fits) if c != stretch)
    table.setColumnWidth(stretch, max(fits[stretch], room))
    most = table.property(_MOST)
    if most == 0:
        return
    rows = min(
        max(table.topLevelItemCount(), FEWEST_ROWS), most if isinstance(most, int) else MOST_ROWS
    )
    first = table.topLevelItem(0)
    row = table.sizeHintForRow(0) if first is not None else -1
    if row <= 0:
        row = table.fontMetrics().height() + 16  # the stylesheet pads each row
    across = table.horizontalScrollBar().sizeHint().height() if room < fits[stretch] else 0
    height = table.header().sizeHint().height() + rows * row + 2 * table.frameWidth() + across
    if table.height() != height or table.minimumHeight() != height:
        table.setFixedHeight(height)


def row_menu(table: QTreeWidget, fill: Callable[[QMenu], None]) -> None:
    def show(point: QPoint) -> None:
        item = table.itemAt(point) or table.currentItem()
        if item is None:
            return
        table.setCurrentItem(item)
        menu = QMenu(table)
        fill(menu)
        at = table.visualItemRect(item).bottomLeft() if table.itemAt(point) is None else point
        popup(menu, table.viewport().mapToGlobal(at))

    table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table.customContextMenuRequested.connect(show)


def add_action(menu: QMenu, text: str, run: Callable[[], object], enabled: bool = True) -> None:
    action = menu.addAction(text)
    action.setEnabled(enabled)
    action.triggered.connect(lambda _c=False: run())


def with_buttons(table: QTreeWidget, buttons: list[QPushButton]) -> QWidget:
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
