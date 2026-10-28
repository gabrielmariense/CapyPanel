from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt, QUrl
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
    listfile.save(path, hl, expected=None, kind="printers")
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


def test_the_table_shows_name_address_status_toner_brand_model_and_tags(
    printers: PrintersTool,
) -> None:
    table = printers.table
    header = table.headerItem()
    shown = [header.text(i) for i in range(table.columnCount()) if not table.isColumnHidden(i)]
    # Serial number and asset tag are hidden at first.
    assert shown == ["Name", "Address", "Status", "Toner", "Brand", "Model", "Tags"]
    assert not table.header().sectionsMovable()  # one fixed order: titles can't be dragged
    assert _names(printers) == ["2F-LABELS", "2F-OFFICE-01", "LOOSE"]
    first = table.topLevelItem(0)
    assert first is not None
    texts = [first.text(i) for i in (0, 1, table.BRAND, table.MODEL, table.TAGS)]
    assert texts == ["2F-LABELS", "192.0.2.25", "ZEBRA", "ZD421", "labels"]
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
    saved = {h.name: h for h in listfile.load(office, "printers").hosts.hosts}
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
    listfile.save(path, hl, expected=None, kind="printers")
    tool = PrintersTool(shell)
    tool.open_list(path)

    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, PrinterDialog)
        dialog.name.setText("LOOSE-02")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", fill)
    tool.add_item()
    assert {h.name for h in listfile.load(path, "printers").hosts.hosts} == {"LOOSE-01", "LOOSE-02"}
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
    saved = next(h for h in listfile.load(office, "printers").hosts.hosts if h.name == "LOOSE")
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


def test_an_address_starting_with_https_opens_with_https() -> None:
    def url(address: str) -> str:
        page = web_page(Host(id="h1", name="P1", group=NO_GROUP, address=address))
        return page.toString() if page else ""

    assert url("https://192.0.2.5") == "https://192.0.2.5"
    assert url("HTTPS://prn-01.example.com:8443") == "https://prn-01.example.com:8443"
    assert url("https://2001:db8::5") == "https://[2001:db8::5]"
    assert url("http://192.0.2.5") == "http://192.0.2.5"  # typed http stays http
    assert url("https://") == ""


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
    assert texts == ["Open &web page", "&Refresh", "Co&py", "&Edit selected…", "&Move to",
                     "&Remove selected"]  # fmt: skip
    assert shown[-1].defaultAction() is printers.commands.open_web_page
    copy = shown[-1].actions()[4].menu()
    assert isinstance(copy, QMenu)
    assert [menus.label(a) for a in copy.actions()] == [
        "Name",
        "&Address",
        "Status",
        "Toner",
        "Brand",
        "Model",
        "Tags",
    ]


def test_toolbar_mirrors_hosts_with_a_plain_refresh(printers: PrintersTool) -> None:
    bar = printers.toolbar
    buttons = (bar.web_button, bar.refresh_button, bar.inventory_button, bar.report_button)
    assert [b.text().strip() for b in buttons] == ["Open web page", "Refresh", "Inventory",
                                                   "Report"]  # fmt: skip
    assert bar.refresh_button.isEnabled() and bar.refresh_button.menu() is None  # one check
    assert printers.commands.refresh_shown.shortcut().toString() == "F5"
    _select(printers)
    assert not bar.web_button.isEnabled()
    _select(printers, "LOOSE")
    assert bar.web_button.isEnabled()
    assert [menus.label(a) for a in bar.inventory_menu.actions()] == [
        "Add &printer…", "Add &group…", "&Manage groups…",
    ]  # fmt: skip


def test_report_lists_the_printers_columns_and_last_check(
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
    assert report.boxes["status"].isEnabled() and report.boxes["toner"].isEnabled()
    assert report.header()[:6] == ["Name", "Address", "Group", "Brand", "Model", "Serial number"]
    office = next(r for r in report.rows() if r[0] == "2F-OFFICE-01")
    assert office[:10] == ["2F-OFFICE-01", "192.0.2.21", "Second floor", "BROTHER", "HL-L6402",
                           "SAMPLE0021", "INV-1021", "SNMP", "mono", ""]  # fmt: skip
    report.boxes["notes"].setChecked(False)
    assert printers.prefs["export_columns"][-1] == "tags"  # in the Printers section
    assert "export_columns" not in shell.prefs  # Hosts' Report keeps its own choices


def test_counts_agree_with_printer_in_portuguese(printers: PrintersTool) -> None:
    from capypanel.core import i18n

    i18n.set_language("pt_BR")
    try:
        assert printers.selected_text(1) == "1 selecionada"  # impressora is feminine
        assert printers.items_text(2) == "2 impressoras"
    finally:
        i18n.set_language(i18n.DEFAULT_LANGUAGE)


def _pick_tags(tool: PrintersTool, *tags: str) -> None:
    tool.nav.clear_tags()
    for i in range(tool.nav.tags.topLevelItemCount()):
        item = tool.nav.tags.topLevelItem(i)
        if item is not None and item.text(0).split(" (")[0] in tags:
            item.setSelected(True)  # a click toggles it, as in MultiSelection


def test_several_tags_narrow_the_group_picked(
    printers: PrintersTool, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = printers.document
    assert doc is not None
    labels = next(h for h in doc.hosts.hosts if h.name == "2F-LABELS")
    printers._commit(doc.hosts.update_host(replace(labels, tags=("labels", "mono"))))
    _pick_tags(printers, "mono")
    assert _names(printers) == ["2F-LABELS", "2F-OFFICE-01"]
    _pick_tags(printers, "mono", "labels")  # every picked tag, not any
    assert _names(printers) == ["2F-LABELS"]
    assert printers.nav._tags_title.text() == "Tags (2)"
    assert printers.nav.clear_tags_button.isEnabled()
    assert not printers.tag_strip.isHidden()
    assert printers.tag_strip._text.text() == (
        "Only printers with all of: <b>labels, mono</b> · 1 of 3 shown"
    )
    assert "Tags: labels, mono" in printers.status_label.text()
    sources, start = printers.report_sources(doc.hosts)
    assert sources[start].label == "Picked tags: labels, mono (1 printer)"

    printers.nav.select_group(NO_GROUP)  # the tags stay picked in another group
    printers._show_items()
    assert _names(printers) == [] and printers.nav.picked_tags() == ["labels", "mono"]
    assert printers.table._empty_text.text() == (
        "No printers in this group have all the picked tags."
    )
    assert not printers.table._empty.isHidden()
    printers.table.clear_tags_button.click()
    assert printers.nav.picked_tags() == [] and _names(printers) == ["LOOSE"]
    assert printers.tag_strip.isHidden() and printers.table._empty.isHidden()
    assert printers.nav._tags_title.text() == "Tags"


def test_a_search_keeps_the_picked_tags(printers: PrintersTool) -> None:
    _pick_tags(printers, "mono")
    printers.search.setText("2F")
    printers._show_items()
    assert _names(printers) == ["2F-OFFICE-01"]  # 2F-LABELS has no "mono"
    assert printers.nav.picked_tags() == ["mono"]


def test_a_tag_view_saved_by_0_19_opens_with_that_tag_picked(printers: PrintersTool) -> None:
    printers.nav.show_view("tag", "labels")
    printers._show_items()
    assert printers.nav.current_filter().kind == "all"
    assert printers.nav.picked_tags() == ["labels"]
    assert _names(printers) == ["2F-LABELS"]


def test_columns_sort_naturally_and_ties_go_by_name(printers: PrintersTool) -> None:
    doc = printers.document
    assert doc is not None
    hl = doc.hosts
    for name, model in (("P10", "m2"), ("p9", "M10"), ("P2", "M2")):
        hl = _printer(hl, name, NO_GROUP, brand="HP", model=model)
    printers._commit(hl)
    printers.nav.select_group(NO_GROUP)
    printers._show_items()
    assert _names(printers) == ["LOOSE", "P2", "p9", "P10"]  # natural, case ignored
    printers.table.sortByColumn(printers.table.MODEL, Qt.SortOrder.AscendingOrder)
    assert _names(printers) == ["P2", "P10", "p9", "LOOSE"]  # m2 = M2: ties by name; empty last
    printers.table.sortByColumn(printers.table.MODEL, Qt.SortOrder.DescendingOrder)
    assert _names(printers) == ["LOOSE", "p9", "P2", "P10"]  # Z–A, ties still by name A–Z
