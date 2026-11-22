from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLineEdit, QMessageBox

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.ssh.host import SshInfo, info_of
from capypanel.ui import import_hosts
from capypanel.ui.import_hosts import (
    NAME,
    NOTES,
    WARNING,
    FormatsDialog,
    HostsFormats,
    HostsImportDialog,
    ImportDialog,
    read_text,
)
from capypanel.ui.ssh_tool.tool import SshTool
from capypanel.ui.themes import engine as themes

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
def window(qapp: QApplication, tmp_path: Path, office: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(office)
    yield win
    win.close()


def _dialog(window: CapyWindow) -> ImportDialog:
    doc = window.hosts.document
    assert doc is not None
    dialog = ImportDialog(None, doc.hosts, doc.hosts.groups[0].id)
    dialog.set_text(PASTED)
    return dialog


def _add_button(dialog: ImportDialog) -> str:
    ok = dialog.box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None
    return ok.text() if ok.isEnabled() else ""


def test_the_preview_says_what_each_row_will_do(window: CapyWindow) -> None:
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
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = window.hosts.document
    assert doc is not None
    before = doc.hosts

    def cancel(dialog: ImportDialog) -> int:
        dialog.set_text(PASTED)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ImportDialog, "exec", cancel)
    window.hosts.commands.import_hosts.trigger()
    doc = window.hosts.document
    assert doc is not None and doc.hosts == before

    def add(dialog: ImportDialog) -> int:
        dialog.set_text(PASTED)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ImportDialog, "exec", add)
    window.hosts.commands.import_hosts.trigger()
    doc = window.hosts.document
    assert doc is not None
    assert {h.name for h in doc.hosts.hosts} == {"HQ-01", "Reception 01", "Finance 01"}
    assert listfile.load(doc.path).hosts == doc.hosts
    assert window.statusBar().currentMessage() == "Added 2 hosts."


SERVERS = (
    "name,address,ssh port,ssh login\nnas-01,192.0.2.41,2222,root\nweb-01,198.51.100.42,,deploy\n"
)


def _adds_servers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[type, list[str]]]:
    opened: list[tuple[type, list[str]]] = []

    def add(dialog: ImportDialog) -> int:
        dialog.set_text(SERVERS)
        header = dialog.table.headerItem()
        opened.append((type(dialog), [header.text(i) for i in range(dialog.table.columnCount())]))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ImportDialog, "exec", add)
    return opened


def test_servers_imported_in_hosts_come_with_their_ssh_port_and_login(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = _adds_servers(monkeypatch)
    window.hosts.commands.import_hosts.trigger()
    assert opened[0][0] is HostsImportDialog
    assert opened[0][1][-3:] == ["Notes", "SSH port", "SSH login"]
    doc = window.hosts.document
    assert doc is not None
    saved = {h.name: info_of(h) for h in listfile.load(doc.path).hosts.hosts}
    assert saved["nas-01"] == SshInfo(port=2222, login="root")
    assert saved["web-01"] == SshInfo(login="deploy")
    assert saved["HQ-01"] == SshInfo()


def test_ssh_s_inventory_imports_hosts_too(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, office: Path
) -> None:
    ssh = window.tools["ssh"]
    assert isinstance(ssh, SshTool) and ssh.open_list(office)
    assert ssh.commands.import_hosts in ssh.toolbar.inventory_menu.actions()
    assert ssh.import_action() is ssh.commands.import_hosts
    opened = _adds_servers(monkeypatch)
    ssh.commands.import_hosts.trigger()
    assert opened and opened[0][0] is HostsImportDialog
    saved = {h.name: info_of(h) for h in listfile.load(office).hosts.hosts}
    assert saved["nas-01"] == SshInfo(port=2222, login="root")
    assert window.statusBar().currentMessage() == "Added 2 hosts."


def test_formats_shows_hosts_the_ssh_columns(qapp: QApplication) -> None:
    hosts, base = HostsFormats(None), FormatsDialog(None)
    titles = [b.text() for b in hosts.buttons.buttons()]
    assert titles == ["Hostnames", "Name and address", "CSV with headers", "SSH servers"]
    assert len(base.buttons.buttons()) == 3


def test_a_port_ssh_exe_can_t_take_is_said_in_the_row(qapp: QApplication) -> None:
    dialog = HostsImportDialog(None, HostList(), NO_GROUP)
    dialog.set_text("name,address,ssh port\nnas-01,192.0.2.41,99999\n")
    row = dialog.table.topLevelItem(0)
    assert row is not None
    assert row.text(dialog.col["warning"]) == "Not an SSH port: type a number from 1 to 65535"
    assert row.text(dialog.col["ssh_port"]) == "99999"
    assert dialog.imported_list() is None


def test_editing_the_table_asks_once_then_rewrites_the_list(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
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
    for x in range(5, 200, 20):
        QTest.mouseMove(dialog.table.viewport(), QPoint(x, row.y()))
    qapp.processEvents()
    assert asked == []
    QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton, pos=row)
    assert len(asked) == 1
    assert dialog.table._may_edit()
    assert len(asked) == 1
    duplicate = dialog.table.topLevelItem(2)
    assert duplicate is not None
    duplicate.setText(NAME, "Finance 02")
    qapp.processEvents()
    assert "Finance 02,PC-0201" in dialog.text.toPlainText()
    assert dialog.text.toPlainText().startswith("name,address,group,tags,notes")
    assert _add_button(dialog) == "&Add 2 hosts"


def test_a_cell_being_edited_shows_its_whole_text(window: CapyWindow) -> None:
    try:
        for theme in ("capypanel-dark", "paper", "windows-dark"):
            window.set_theme(theme)
            dialog = _dialog(window)
            dialog.show()
            QTest.qWaitForWindowExposed(dialog)
            dialog.table.unlocked = True
            item = dialog.table.topLevelItem(0)
            assert item is not None
            dialog.table.editItem(item, NAME)
            editor = dialog.table.findChild(QLineEdit)
            assert editor is not None
            assert editor.height() >= editor.minimumSizeHint().height(), theme
            assert editor.height() >= dialog.table.visualItemRect(item).height() - 2, theme
            dialog.close()
    finally:
        themes.apply(themes.DEFAULT_THEME)


def test_rows_can_be_left_out_or_added_below(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
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
    assert new is not None and new.text(NAME) == ""
    assert new.text(WARNING) == "No name"


def test_a_list_it_cant_read_is_explained_and_adds_nothing(window: CapyWindow) -> None:
    dialog = _dialog(window)
    dialog.set_text("PC-1,10.0.0.1,Lab,kiosk")
    assert "<b>name, address, group, tags, notes</b>" in dialog.problem.text()
    assert not dialog.problem.isHidden()
    assert _add_button(dialog) == ""
    dialog.set_text("PC-1,10.0.0.1", from_file=True)
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
