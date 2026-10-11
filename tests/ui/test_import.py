from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui import import_hosts
from capypanel.ui.import_hosts import (
    NAME,
    NOTES,
    WARNING,
    FormatsDialog,
    ImportDialog,
    read_text,
)
from capypanel.ui.main_window.window import MainWindow

PASTED = (
    "name,address,group,tags,notes\n"
    "Reception 01,PC-0142,Headquarters/Front desk,kiosk,USB printer\n"
    "Finance 01,PC-0201,Headquarters/Finance,,\n"
    "Finance 01,PC-0201,Headquarters/Finance,,\n"
    "HQ-01,10.0.0.1,,,\n"
)


@pytest.fixture
def office(tmp_path: Path) -> Path:
    hl, hq = HostList().add_group("Headquarters")
    hl, _ = hl.add_group("Front desk", parent=hq.id)
    hl, _ = hl.add_host("HQ-01", hq.id, address="10.0.0.1")
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    return path


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, office: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.open_list(office)
    yield win
    win.close()


def _dialog(window: MainWindow) -> ImportDialog:
    doc = window.document
    assert doc is not None
    dialog = ImportDialog(None, doc.hosts, doc.hosts.groups[0].id)
    dialog.set_text(PASTED)
    return dialog


def _add_button(dialog: ImportDialog) -> str:
    ok = dialog.box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None
    return ok.text() if ok.isEnabled() else ""


def test_the_preview_says_what_each_row_will_do(window: MainWindow) -> None:
    dialog = _dialog(window)
    table = dialog.table
    warnings = [table.topLevelItem(i).text(WARNING) for i in range(4)]  # type: ignore[union-attr]
    assert warnings == ["", "", "Same as row 2", "Already in the list, in “Headquarters”"]
    assert [table.topLevelItem(i).text(0) for i in range(4)] == ["1", "2", "3", "4"]  # type: ignore[union-attr]
    assert _add_button(dialog) == "&Add 2 hosts"
    assert "New group: Headquarters › Finance." in dialog.summary.text()
    first = table.topLevelItem(0)
    assert first is not None and first.toolTip(NOTES) == "USB printer"


def test_nothing_changes_until_add_is_clicked(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = window.document
    assert doc is not None
    before = doc.hosts

    def cancel(dialog: ImportDialog) -> int:
        dialog.set_text(PASTED)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ImportDialog, "exec", cancel)
    window.commands.import_hosts.trigger()
    assert window.document is not None and window.document.hosts == before  # Cancel: untouched

    def add(dialog: ImportDialog) -> int:
        dialog.set_text(PASTED)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ImportDialog, "exec", add)
    window.commands.import_hosts.trigger()
    doc = window.document
    assert doc is not None
    assert {h.name for h in doc.hosts.hosts} == {"HQ-01", "Reception 01", "Finance 01"}
    assert listfile.load(doc.path).hosts == doc.hosts  # saved
    assert window.statusBar().currentMessage() == "Added 2 hosts."


def test_editing_the_table_asks_once_then_rewrites_the_list(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    asked: list[str] = []

    def yes(*args: object) -> QMessageBox.StandardButton:
        asked.append(str(args[1]))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(import_hosts.QMessageBox, "question", yes)
    dialog = _dialog(window)
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    row = dialog.table.visualItemRect(dialog.table.topLevelItem(0)).center()  # type: ignore[arg-type]
    for x in range(5, 200, 20):  # the pointer passing over doesn't ask
        QTest.mouseMove(dialog.table.viewport(), QPoint(x, row.y()))
    qapp.processEvents()
    assert asked == []
    QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton, pos=row)
    assert len(asked) == 1  # the first click asks
    assert dialog.table._may_edit()
    assert len(asked) == 1  # once per import
    duplicate = dialog.table.topLevelItem(2)
    assert duplicate is not None
    duplicate.setText(NAME, "Finance 02")  # what typing in the cell does
    qapp.processEvents()
    assert "Finance 02,PC-0201" in dialog.text.toPlainText()
    assert dialog.text.toPlainText().startswith("name,address,group,tags,notes")
    # Still the same address as Finance 01: skipped, now for being already in this import.
    assert _add_button(dialog) == "&Add 2 hosts"


def test_rows_can_be_left_out_or_added_below(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    monkeypatch.setattr(
        import_hosts.QMessageBox, "question", lambda *_a: QMessageBox.StandardButton.Yes
    )
    dialog = _dialog(window)
    dialog._leave_out([0])
    qapp.processEvents()
    assert "Reception 01" not in dialog.text.toPlainText()
    dialog._add_row(0)
    qapp.processEvents()
    new = dialog.table.topLevelItem(1)
    assert new is not None and new.text(NAME) == ""  # right under the clicked row
    assert new.text(WARNING) == "No name"


def test_a_list_it_cant_read_is_explained_and_adds_nothing(window: MainWindow) -> None:
    dialog = _dialog(window)
    dialog.set_text("PC-1,10.0.0.1,Lab,kiosk")
    assert "<b>name, address, group, tags, notes</b>" in dialog.problem.text()
    assert not dialog.problem.isHidden()
    assert _add_button(dialog) == ""  # greyed out
    dialog.set_text("PC-1,10.0.0.1", from_file=True)  # a CSV file needs its header
    assert "header" in dialog.problem.text()


def test_csv_files_from_excel_in_any_encoding_open(tmp_path: Path) -> None:
    ansi = tmp_path / "ansi.csv"
    ansi.write_bytes("nome;endereço\nRecepção;10.0.0.1\n".encode("cp1252"))
    assert read_text(ansi).startswith("nome;endereço")
    utf8 = tmp_path / "utf8.csv"
    utf8.write_bytes("﻿name\nPC-1\n".encode())  # Excel's "CSV UTF-8" starts with a BOM
    assert read_text(utf8) == "name\nPC-1\n"


def test_formats_shows_one_format_at_a_time(qapp: QApplication) -> None:
    dialog = FormatsDialog(None)
    second = dialog.buttons.button(1)
    assert second is not None
    second.click()
    assert dialog._pages.currentIndex() == 1
