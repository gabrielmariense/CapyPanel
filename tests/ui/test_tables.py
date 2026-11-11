"""The one table design for lists in windows: whole text, a sideways scroll only when needed,
and Fit columns to content on the column titles' right-click."""

from typing import Any

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from capypanel.ui import tables
from capypanel.ui.tables import fit_menu, fit_rows, grid_table


def _table(width: int, *rows: list[str]) -> QTreeWidget:
    table = grid_table(["Account", "Used for", "Kept in"])
    for row in rows:
        table.addTopLevelItem(QTreeWidgetItem(row))
    table.resize(width, 200)
    table.show()
    fit_rows(table)
    QApplication.processEvents()
    return table


def test_every_column_shows_its_whole_text_and_the_last_fills_the_room(qapp: QApplication) -> None:
    table = _table(700, ["EXAMPLE\\admin", "Every PC", "Credential Manager"])
    for column in range(3):
        assert table.columnWidth(column) >= table.sizeHintForColumn(column)
    used = sum(table.columnWidth(c) for c in range(3))
    assert used == table.viewport().width()  # no gap after the last column
    assert not table.horizontalScrollBar().isVisible()


def test_a_table_too_narrow_scrolls_sideways_instead_of_cutting(qapp: QApplication) -> None:
    long = "Gerenciador de Credenciais"  # under WIDEST, which only cuts a paragraph
    table = _table(260, ["EXAMPLE\\helpdesk.admin", "IT SUPPORT DESK (198.51.100.20)", long])
    assert table.columnWidth(2) >= table.sizeHintForColumn(2)  # whole, not "…"
    assert table.horizontalScrollBar().maximum() > 0
    rows = table.header().sizeHint().height() + 3 * table.sizeHintForRow(0)
    assert table.height() > rows + table.horizontalScrollBar().sizeHint().height() - 1


def _menu(monkeypatch: pytest.MonkeyPatch, table: QTreeWidget) -> list[Any]:
    """The column titles' right-click menu, its actions."""
    shown: list[Any] = []
    monkeypatch.setattr(tables, "popup", lambda menu, _at: shown.extend(menu.actions()))
    table.header().customContextMenuRequested.emit(QPoint(5, 5))
    return shown


def test_fit_columns_to_content_is_on_every_tables_titles(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _table(700, ["EXAMPLE\\admin", "Every PC", "Credential Manager"])
    table.setColumnWidth(0, 20)  # dragged too narrow
    [fit] = _menu(monkeypatch, table)
    assert fit.text() == "&Fit columns to content"
    fit.trigger()
    assert table.columnWidth(0) >= table.sizeHintForColumn(0)

    plain = QTreeWidget()  # a table built by hand, like the import preview
    plain.setHeaderLabels(["Name", "Version"])
    plain.addTopLevelItem(QTreeWidgetItem(["A long program name here", "1.0"]))
    fit_menu(plain)
    plain.setColumnWidth(0, 10)
    [fit] = _menu(monkeypatch, plain)
    fit.trigger()
    assert plain.columnWidth(0) >= plain.sizeHintForColumn(0)
