import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.printers.printer import DOC360, info_of
from capypanel.ui import import_hosts
from capypanel.ui.import_hosts import ImportDialog
from capypanel.ui.printers_tool.import_printers import ImportPrintersDialog, PrinterFormats

REPORT = (
    "Name,Address,Group,Brand,Model,Serial number,Asset tag,Page counters,Tags,Notes\n"
    "Reception,192.0.2.10,Clinic A,hp,M404,sample01,PAT-1,Doc360 MPS,mono,Ground floor\n"
    "Lab,https://192.0.2.11,,RICOH,SP 3710,SAMPLE02,,SNMP,,\n"
)
WINDOWS = (
    "#TYPE Microsoft.Management.Infrastructure.CimInstance#ROOT/StandardCimv2/MSFT_Printer\n"
    '"Name","PortName","DriverName","Location","Comment"\n'
    '"Desk","USB001","SAMPLE PCL6","",""\n'
    '"Ward","IP_192.0.2.12","SAMPLE PCL6","Ward 2",""\n'
)


def _add_button(dialog: ImportDialog) -> str:
    ok = dialog.box.button(QDialogButtonBox.StandardButton.Ok)
    assert ok is not None
    return ok.text() if ok.isEnabled() else ""


def _row(dialog: ImportDialog, index: int) -> dict[str, str]:
    item = dialog.table.topLevelItem(index)
    assert item is not None
    return {key: item.text(column) for key, column in dialog.col.items()}


def test_a_report_comes_back_with_the_printers_columns(qapp: QApplication) -> None:
    dialog = ImportPrintersDialog(None, HostList(), NO_GROUP)
    dialog.set_text(REPORT)
    assert dialog.windowTitle() == "Import printers"
    header = dialog.table.headerItem()
    # Warning right after Address, as in Import hosts, so it's never off to the side (Dante).
    assert [header.text(i) for i in range(dialog.table.columnCount())] == [
        "", "Name", "Address", "Warning", "Brand", "Model", "Serial number", "Asset tag",
        "Page counters", "Group", "Tags", "Notes",
    ]  # fmt: skip
    assert _row(dialog, 0)["brand"] == "hp"  # as typed; saved in capitals, as Add printer does
    assert _add_button(dialog) == "&Add 2 printers"
    assert "2 printers will be added." in dialog.summary.text()
    new = dialog.imported_list()
    assert new is not None
    saved = {h.name: h for h in new.hosts}
    assert (info_of(saved["Reception"]).brand, info_of(saved["Reception"]).serial) == (
        "HP", "SAMPLE01",
    )  # fmt: skip
    assert info_of(saved["Reception"]).counter_source == DOC360
    assert saved["Lab"].address == "https://192.0.2.11"


def test_windows_printer_list_says_which_ports_need_an_address(qapp: QApplication) -> None:
    dialog = ImportPrintersDialog(None, HostList(), NO_GROUP)
    dialog.set_text(WINDOWS, from_file=True)
    assert [_row(dialog, i)["address"] for i in range(2)] == ["", "192.0.2.12"]
    assert "USB001" in _row(dialog, 0)["warning"]
    assert _row(dialog, 1)["notes"] == "Ward 2"
    assert _add_button(dialog) == "&Add 1 printer"
    assert "Ignored columns: the other column Windows exports." in dialog.summary.text()


def test_editing_a_printer_column_rewrites_the_list_with_it(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = ImportPrintersDialog(None, HostList(), NO_GROUP)
    dialog.set_text("name,address\nLab,192.0.2.11\n")
    dialog.table.unlocked = True  # the question was answered Yes
    item = dialog.table.topLevelItem(0)
    assert item is not None
    item.setText(dialog.col["brand"], "ricoh")
    assert dialog.text.toPlainText().splitlines() == [
        "name,address,group,tags,notes,brand,model,serial,asset_tag,counter_source",
        "Lab,192.0.2.11,,,,ricoh,,,,",
    ]
    QApplication.processEvents()  # the preview is planned again after the editor closes
    new = dialog.imported_list()
    assert new is not None and info_of(new.hosts[0]).brand == "RICOH"


def test_import_hosts_keeps_its_own_columns(qapp: QApplication) -> None:
    dialog = ImportDialog(None, HostList(), NO_GROUP)
    assert dialog.col == {
        "dot": import_hosts.DOT, "name": import_hosts.NAME, "address": import_hosts.ADDRESS,
        "group": import_hosts.GROUP, "tags": import_hosts.TAGS, "notes": import_hosts.NOTES,
        "warning": import_hosts.WARNING,
    }  # fmt: skip
    assert dialog.editable == import_hosts.EDITABLE
    assert dialog.windowTitle() == "Import hosts"


def test_formats_has_the_three_lists_it_reads(qapp: QApplication) -> None:
    dialog = PrinterFormats(None)
    titles = [b.text() for b in dialog.buttons.buttons()]
    assert titles == ["Name and address", "A Printers Report", "Windows' printer list"]
