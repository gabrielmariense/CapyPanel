from capypanel.core.hosts.bulk import ImportRow, Verdict, write_csv
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.printers.bulk import (
    PORT,
    counter_source,
    parse,
    plan,
    read_windows_export,
)
from capypanel.core.printers.printer import DOC360, SNMP, PrinterInfo, info_of, with_info

# Windows PowerShell 5.1's `Get-Printer | Export-Csv` header: 40 columns (checked 14 Nov 2026 on a
# real export's header; the rows below are invented).
WINDOWS_COLUMNS = [
    "RenderingMode",
    "PrinterStatus",
    "Type",
    "DeviceType",
    "Caption",
    "Description",
    "ElementName",
    "InstanceID",
    "CommunicationStatus",
    "DetailedStatus",
    "HealthState",
    "InstallDate",
    "Name",
    "OperatingStatus",
    "OperationalStatus",
    "PrimaryStatus",
    "Status",
    "StatusDescriptions",
    "BranchOfficeOfflineLogSizeMB",
    "Comment",
    "ComputerName",
    "Datatype",
    "DefaultJobPriority",
    "DisableBranchOfficeLogging",
    "DriverName",
    "JobCount",
    "KeepPrintedJobs",
    "Location",
    "PermissionSDDL",
    "PortName",
    "PrintProcessor",
    "Priority",
    "Published",
    "SeparatorPageFile",
    "Shared",
    "ShareName",
    "StartTime",
    "UntilTime",
    "WorkflowPolicy",
    "PSComputerName",
]


def _windows(rows: list[dict[str, str]], delimiter: str = ",") -> str:
    lines = [
        "#TYPE Microsoft.Management.Infrastructure.CimInstance#ROOT/StandardCimv2/MSFT_Printer"
    ]
    lines.append(delimiter.join(f'"{c}"' for c in WINDOWS_COLUMNS))
    for row in rows:
        lines.append(delimiter.join(f'"{row.get(c, "")}"' for c in WINDOWS_COLUMNS))
    return "\n".join(lines) + "\n"


def test_windows_export_names_ports_and_notes() -> None:
    text = _windows([
        {"Name": "Reception laser", "PortName": "IP_192.0.2.10", "Location": "Ground floor",
         "Comment": "Toner in cabinet 3", "DriverName": "SAMPLE PCL6"},
        {"Name": "Lab", "PortName": "192.0.2.11_1", "DriverName": "SAMPLE PCL6"},
        {"Name": "PRN-WARD-2", "PortName": "PRN-WARD-2.example.net"},
        {"Name": "Ward printer", "PortName": "WSD-0a1b2c3d-0000-4000-8000-000000000001"},
        {"Name": "Desk", "PortName": "USB001"},
        {"Name": "Microsoft Print to PDF", "PortName": "PORTPROMPT:"},
    ])  # fmt: skip
    parsed = read_windows_export(text)
    assert parsed is not None
    assert [(r.name, r.address) for r in parsed.rows] == [
        ("Reception laser", "192.0.2.10"),  # the "IP_" Windows puts before it, dropped
        ("Lab", "192.0.2.11"),  # Windows' second port to the same printer
        ("PRN-WARD-2", "PRN-WARD-2.example.net"),  # a port named after the printer
        ("Ward printer", ""),
        ("Desk", ""),
        ("Microsoft Print to PDF", ""),
    ]
    assert parsed.rows[0].notes == "Ground floor · Toner in cabinet 3"
    assert dict(parsed.rows[3].more)[PORT].startswith("WSD-")  # said in the preview
    assert parsed.rows[0].more == ()
    assert parsed.ignored == ("the other 36 columns Windows exports",)  # one line, not 36 names


def test_windows_export_with_the_list_separator_and_a_bom() -> None:
    text = "﻿" + _windows([{"Name": "Lab", "PortName": "IP_192.0.2.11"}], ";")
    parsed = parse(text, file=True)
    assert [(r.name, r.address) for r in parsed.rows] == [("Lab", "192.0.2.11")]


def test_other_lists_are_not_windows_exports() -> None:
    assert read_windows_export("name,address\nLab,192.0.2.11\n") is None
    assert read_windows_export("") is None


def test_a_port_that_isnt_an_address_comes_in_marked_whatever_the_name() -> None:
    # "Desk" would be a fine network name; its port says it's on USB, so it needs an address.
    rows = parse(_windows([{"Name": "Desk", "PortName": "USB001"},
                           {"Name": "Lab", "PortName": "IP_192.0.2.11"}])).rows  # fmt: skip
    planned = plan(HostList(), rows, NO_GROUP)
    assert [i.verdict for i in planned.items] == [Verdict.BAD, Verdict.ADD]
    assert "USB001" in planned.items[0].reason
    assert [h.name for h in planned.result.hosts] == ["Lab"]


def test_the_report_reads_back_with_every_printer_column() -> None:
    printers, group = HostList().add_group("Clinic A")
    info = PrinterInfo(brand="SAMSUNG", model="M4070", serial="SAMPLE1", asset_tag="PAT-0001",
                       counter_source=DOC360)  # fmt: skip
    titles = ["Name", "Address", "Group", "Brand", "Model", "Serial number", "Asset tag",
              "Page counters", "Tags", "Notes"]  # fmt: skip
    cells = ["Reception", "https://192.0.2.10", "Clinic A", "SAMSUNG", "M4070", "SAMPLE1",
             "PAT-0001", "Doc360 MPS", "toner;front", "Ground floor"]  # fmt: skip
    rows = parse(write_csv(titles, [cells])).rows
    planned = plan(printers, rows, NO_GROUP)
    assert [i.verdict for i in planned.items] == [Verdict.ADD]  # https:// is a printer address
    [host] = planned.result.hosts
    assert (host.address, host.group, host.tags) == ("https://192.0.2.10", group.id,
                                                     ("toner", "front"))  # fmt: skip
    assert info_of(host) == info


def test_the_report_in_portuguese_reads_back_too() -> None:
    titles = ["Nome", "Endereço", "Marca", "Modelo", "Nº de série", "Patrimônio",
              "Contadores de páginas"]  # fmt: skip
    rows = parse(write_csv(titles, [["Lab", "192.0.2.11", "ricoh", "SP 3710", "sample2",
                                     "PAT-2", "SNMP"]], ";")).rows  # fmt: skip
    [host] = plan(HostList(), rows, NO_GROUP).result.hosts
    # As Add printer saves them: brand and serial in capitals.
    assert info_of(host) == PrinterInfo("RICOH", "SP 3710", "SAMPLE2", "PAT-2", SNMP)


def test_printers_already_in_the_list_are_left_alone() -> None:
    printers, old = HostList().add_host("Lab", NO_GROUP, address="192.0.2.11")
    printers = printers.update_host(with_info(old, PrinterInfo(brand="RICOH")))
    rows = (ImportRow("Lab", "192.0.2.11", more=(("brand", "SAMSUNG"),)),)
    planned = plan(printers, rows, NO_GROUP)
    assert [i.verdict for i in planned.items] == [Verdict.SKIP]
    assert planned.result is printers or planned.result == printers
    assert info_of(planned.result.hosts[0]).brand == "RICOH"  # never overwritten


def test_names_that_arent_network_names_need_an_address() -> None:
    planned = plan(HostList(), (ImportRow("Reception laser"), ImportRow("PRN-01")), NO_GROUP)
    assert [i.verdict for i in planned.items] == [Verdict.BAD, Verdict.ADD]
    assert "printer's name on the network" in planned.items[0].reason


def test_page_counters_as_the_report_writes_them() -> None:
    assert counter_source("") == SNMP
    assert counter_source("SNMP") == SNMP
    assert counter_source("Doc360 MPS") == DOC360
    assert counter_source("doc360") == DOC360
    assert counter_source("Unknown (sample-portal)") == "sample-portal"  # kept as the file had it
    assert counter_source("Desconhecido (sample-portal)") == "sample-portal"
