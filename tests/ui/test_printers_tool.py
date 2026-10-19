from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QDialog, QGroupBox, QMenu

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.core.printers.printer import DOC360, PrinterInfo, info_of, with_info
from capypanel.ui import menus
from capypanel.ui.printers_tool import tool as tool_module
from capypanel.ui.printers_tool.dialog import PrinterDialog
from capypanel.ui.printers_tool.report import PrintersReport
from capypanel.ui.printers_tool.tool import PrintersTool, web_page


class FakeShell:
    """What a tool asks of the shell, without the window."""

    def __init__(self, paths: settings.Paths) -> None:
        self.paths = paths
        self.prefs: dict[str, Any] = {"schema": 1}
        self.messages: list[str] = []
        self.settings_pages: list[str | None] = []

    def tool_prefs(self, tool_id: str, *, inherit: bool = False) -> dict[str, Any]:
        return settings.tool_prefs(self.prefs, tool_id, inherit=inherit)

    def save_prefs(self) -> None:
        pass

    def open_settings(self, page: str | None = None) -> None:
        self.settings_pages.append(page)

    def show_message(self, text: str, timeout: int = 5000) -> None:
        self.messages.append(text)


@pytest.fixture
def shell(tmp_path: Path) -> FakeShell:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return FakeShell(settings.resolve_paths(tmp_path))


def _printer(
    hl: HostList, name: str, group: str, address: str = "", tags: str = "", **info: str
) -> HostList:
    hl, host = hl.add_host(name, group, address=address, tags=[t for t in tags.split(",") if t])
    return hl.update_host(with_info(host, PrinterInfo(**info)))  # type: ignore[arg-type]


@pytest.fixture
def office(tmp_path: Path) -> Path:
    hl, floor = HostList().add_group("Second floor")
    hl = _printer(hl, "2F-LABELS", floor.id, "192.0.2.25", "labels", brand="ZEBRA",
                  model="ZD421", serial="SAMPLE0025")  # fmt: skip
    hl = _printer(hl, "2F-OFFICE-01", floor.id, "192.0.2.21", "mono", brand="BROTHER",
                  model="HL-L6402", serial="SAMPLE0021", asset_tag="INV-1021")  # fmt: skip
    hl = _printer(hl, "LOOSE", NO_GROUP, "198.51.100.31")
    path = tmp_path / "office printers.json"
    listfile.save(path, hl, expected=None)
    return path


@pytest.fixture
def printers(qapp: QApplication, shell: FakeShell, office: Path) -> Iterator[PrintersTool]:
    tool = PrintersTool(shell)
    assert tool.open_list(office)
    yield tool
    tool.close()
    tool.deleteLater()


def _names(tool: PrintersTool) -> list[str]:
    rows = (tool.table.topLevelItem(i) for i in range(tool.table.topLevelItemCount()))
    return [row.text(0) for row in rows if row is not None]


def _select(tool: PrintersTool, *names: str) -> None:
    tool.table.clearSelection()
    for i in range(tool.table.topLevelItemCount()):
        row = tool.table.topLevelItem(i)
        if row is not None and row.text(0) in names:
            row.setSelected(True)


def test_the_table_shows_name_brand_model_address_and_tags(printers: PrintersTool) -> None:
    table = printers.table
    header = table.headerItem()
    shown = [header.text(i) for i in range(table.columnCount()) if not table.isColumnHidden(i)]
    assert shown == ["Name", "Brand", "Model", "Address", "Tags"]  # serial and asset tag hidden
    assert _names(printers) == ["2F-LABELS", "2F-OFFICE-01", "LOOSE"]
    first = table.topLevelItem(0)
    assert first is not None
    assert [first.text(i) for i in range(5)] == ["2F-LABELS", "ZEBRA", "ZD421", "192.0.2.25",
                                                 "labels"]  # fmt: skip
    assert printers.nav.everything.topLevelItem(0).text(0).startswith("All printers")  # type: ignore[union-attr]


def test_columns_shown_by_the_user_are_kept(shell: FakeShell, printers: PrintersTool) -> None:
    printers.table._show_column(printers.table.SERIAL, True)
    assert printers.prefs["hidden_columns"] == ["asset_tag"]
    printers.table.set_hidden_columns(printers.prefs["hidden_columns"])
    assert not printers.table.isColumnHidden(printers.table.SERIAL)


def test_search_covers_the_columns_shown_and_the_notes(printers: PrintersTool) -> None:
    assert printers.search.placeholderText() == "Search name, address, brand, model, tags, notes"
    printers.search.setText("zebra")
    printers._show_items()
    assert _names(printers) == ["2F-LABELS"]
    printers.search.setText("SAMPLE0021")  # the serial number's column is hidden: not searched
    printers._show_items()
    assert _names(printers) == []
    printers.table._show_column(printers.table.SERIAL, True)
    assert "serial number" in printers.search.placeholderText()
    printers.search.setText("sample0021")
    printers._show_items()
    assert _names(printers) == ["2F-OFFICE-01"]


def test_details_show_the_printer_in_sections(printers: PrintersTool) -> None:
    _select(printers, "2F-OFFICE-01")
    details = printers.details
    assert details.shown_value("name") == "2F-OFFICE-01"
    assert details.shown_value("address") == "192.0.2.21"
    assert details.shown_value("group") == "Second floor"
    assert details.shown_value("brand") == "BROTHER"
    assert details.shown_value("serial") == "SAMPLE0021"
    assert details.shown_value("asset_tag") == "INV-1021"
    assert details.shown_value("counter_source") == "SNMP"
    assert details.shown_value("tags") == "mono"


def test_with_none_picked_details_count_the_printers_shown(printers: PrintersTool) -> None:
    printers.table.clearSelection()
    assert printers.details._hint.text().startswith("3 printers shown")
    _select(printers, "2F-LABELS", "LOOSE")
    assert printers.details._hint.text() == "2 printers selected"


def test_adding_a_printer_saves_its_details(
    printers: PrintersTool, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, PrinterDialog)
        dialog.name.setText("RECEPTION-01")
        dialog.address.setText("192.0.2.11")
        dialog.brand.setCurrentText("samsung")
        dialog.model.setText("M4070")
        dialog.serial.setText("sample0011")
        dialog.source.setCurrentIndex(dialog.source.findData(DOC360))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", fill)
    printers.add_item()
    saved = {h.name: h for h in listfile.load(office).hosts.hosts}
    assert set(saved) == {"2F-LABELS", "2F-OFFICE-01", "LOOSE", "RECEPTION-01"}
    info = info_of(saved["RECEPTION-01"])
    assert (info.brand, info.model, info.serial, info.counter_source) == (
        "SAMSUNG", "M4070", "SAMPLE0011", DOC360,
    )  # fmt: skip
    assert printers.table.selected_ids() == [saved["RECEPTION-01"].id]


def test_adding_to_a_list_without_groups_keeps_its_printers(
    shell: FakeShell, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication
) -> None:
    hl = _printer(HostList(), "LOOSE-01", NO_GROUP)
    path = tmp_path / "loose.json"
    listfile.save(path, hl, expected=None)
    tool = PrintersTool(shell)
    tool.open_list(path)

    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, PrinterDialog)
        dialog.name.setText("LOOSE-02")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", fill)
    tool.add_item()
    assert {h.name for h in listfile.load(path).hosts.hosts} == {"LOOSE-01", "LOOSE-02"}
    tool.deleteLater()


def test_editing_keeps_values_this_version_cant_read(
    printers: PrintersTool, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = printers.document
    assert doc is not None
    loose = next(h for h in doc.hosts.hosts if h.name == "LOOSE")
    odd = replace(loose, extra={"printer": {"brand": 42, "toner": "low"}})
    printers._commit(doc.hosts.update_host(odd))

    def rename(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, PrinterDialog)
        dialog.model.setText("M4080")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", rename)
    printers.edit_item(odd)
    saved = next(h for h in listfile.load(office).hosts.hosts if h.name == "LOOSE")
    assert saved.extra["printer"] == {"brand": 42, "toner": "low", "model": "M4080"}


def test_web_pages_open_on_the_address_at_most_ten(
    shell: FakeShell, printers: PrintersTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(
        tool_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True
    )
    _select(printers, "2F-LABELS", "LOOSE")
    printers.activate_selected()  # what a double-click and Enter do
    assert opened == ["http://192.0.2.25", "http://198.51.100.31"]
    assert shell.messages[-1] == "Opened 2 web pages."

    doc = printers.document
    assert doc is not None
    hl = doc.hosts
    for n in range(12):
        hl = _printer(hl, f"P{n:02}", NO_GROUP, address=f"192.0.2.{100 + n}")
    printers._commit(hl)
    printers.table.selectAll()
    opened.clear()
    printers.open_web_pages()
    assert len(opened) == 10
    assert shell.messages[-1] == "Opened 10 web pages. Only the first 10 open at once."


def test_a_web_page_is_built_from_the_address_or_the_name() -> None:
    def url(name: str, address: str = "") -> QUrl | None:
        return web_page(Host(id="h1", name=name, group=NO_GROUP, address=address))

    assert str(url("P1", "192.0.2.5").toString()) == "http://192.0.2.5"  # type: ignore[union-attr]
    assert str(url("PRN-01").toString()) == "http://prn-01"  # type: ignore[union-attr]
    assert url("P1", "2001:db8::5").toString() == "http://[2001:db8::5]"  # type: ignore[union-attr]
    assert url("Reception desk", "bad host") is None


def test_the_printer_menu_opens_the_web_page_first(
    printers: PrintersTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMenu] = []
    monkeypatch.setattr(menus, "popup", lambda menu, _where: shown.append(menu))
    monkeypatch.setattr("capypanel.ui.list_workspace.workspace.popup",
                        lambda menu, _where: shown.append(menu))  # fmt: skip
    _select(printers, "2F-LABELS")
    row = printers.table.topLevelItem(0)
    assert row is not None
    printers._item_menu(printers.table.visualItemRect(row).center())
    texts = [menus.label(a) for a in shown[-1].actions() if not a.isSeparator()]
    assert texts == ["Open &web page", "Co&py", "&Edit selected…", "&Move to", "&Remove selected"]
    assert shown[-1].defaultAction() is printers.commands.open_web_page
    copy = shown[-1].actions()[2].menu()
    assert isinstance(copy, QMenu)
    assert [menus.label(a) for a in copy.actions()] == [
        "Name",
        "Brand",
        "Model",
        "&Address",
        "Tags",
    ]


def test_toolbar_mirrors_hosts_with_refresh_greyed_out(printers: PrintersTool) -> None:
    bar = printers.toolbar
    buttons = (bar.web_button, bar.refresh_button, bar.inventory_button, bar.report_button)
    assert [b.text().strip() for b in buttons] == ["Open web page", "Refresh", "Inventory",
                                                   "Report"]  # fmt: skip
    assert not bar.refresh_button.isEnabled()
    _select(printers)
    assert not bar.web_button.isEnabled()
    _select(printers, "LOOSE")
    assert bar.web_button.isEnabled()
    assert [menus.label(a) for a in bar.inventory_menu.actions()] == [
        "Add &printer…", "Add &group…", "&Manage groups…",
    ]  # fmt: skip


def test_report_lists_the_printers_columns_with_last_check_greyed(
    shell: FakeShell, printers: PrintersTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[PrintersReport] = []

    def look(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, PrintersReport)
        seen.append(dialog)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(tool_module, "run_modal", look)
    printers.commands.export_printers.trigger()
    [report] = seen
    titles = [g.title() for g in report.findChildren(QGroupBox)]
    assert titles == ["Printer", "Details", "Last check"]
    assert report.source.currentText() == "All printers (3 printers)"
    assert report.preset.currentText() == "All details"
    assert not report.boxes["status"].isEnabled() and not report.boxes["toner"].isEnabled()
    assert not report.refresh_button.isEnabled()
    assert report.header()[:6] == ["Name", "Address", "Group", "Brand", "Model", "Serial number"]
    office = next(r for r in report.rows() if r[0] == "2F-OFFICE-01")
    assert office == ["2F-OFFICE-01", "192.0.2.21", "Second floor", "BROTHER", "HL-L6402",
                      "SAMPLE0021", "INV-1021", "SNMP", "mono", ""]  # fmt: skip
    report.boxes["notes"].setChecked(False)
    assert printers.prefs["export_columns"][-1] == "tags"  # in the Printers section
    assert "export_columns" not in shell.prefs  # Hosts' Report keeps its own choices
