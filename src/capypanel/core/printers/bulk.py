import csv
import io
import re
from collections.abc import Iterable, Mapping

from capypanel.core.hosts import bulk
from capypanel.core.hosts.bulk import ImportRow, Parsed, Plan, Verdict
from capypanel.core.hosts.model import HostList, is_hostname
from capypanel.core.i18n import _, ngettext
from capypanel.core.printers.printer import COUNTER_SOURCES, DOC360, SNMP, PrinterInfo, with_info
from capypanel.core.printers.reading import snmp_host

MORE: Mapping[str, frozenset[str]] = {
    "brand": frozenset({"brand", "marca", "manufacturer", "fabricante"}),
    "model": frozenset({"model", "modelo"}),
    "serial": frozenset({"serial number", "serial", "nº de série", "número de série", "série"}),
    "asset_tag": frozenset({"asset tag", "asset", "patrimônio", "nº de patrimônio"}),
    "counter_source": frozenset({"counter source", "page counters", "contadores de páginas"}),
}
PORT = "port"

_WINDOWS_TYPE = "#TYPE"
_WINDOWS_COLUMNS = {"Name", "PortName", "DriverName"}
_WINDOWS_USED = ("Name", "PortName", "Location", "Comment")
_IP_PORT = re.compile(r"^IP_", re.IGNORECASE)
_NUMBERED_IP = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})_\d+$")
_LOCAL_PORT = re.compile(r"^(?:WSD-.*|USB\d+|TS\d+|.*:)$", re.IGNORECASE)


def parse(text: str, *, file: bool = False) -> Parsed:
    windows = read_windows_export(text)
    if windows is not None:
        return windows
    return bulk.parse(text, file=file, more=MORE)


def read_windows_export(text: str) -> Parsed | None:
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and lines[0].lstrip("﻿").startswith(_WINDOWS_TYPE):
        lines = lines[1:]
    if not lines:
        return None
    # Export-Csv writes commas; with -UseCulture, Windows' list separator (";" in pt-BR).
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    columns = [c.strip() for c in reader.fieldnames or ()]
    if not _WINDOWS_COLUMNS.issubset(columns):
        return None
    rows = []
    for record in reader:
        cells = {k.strip(): (v or "").strip() for k, v in record.items() if k}
        port = cells.get("PortName", "")
        address = _port_address(port)
        notes = " · ".join(n for n in (cells.get("Location", ""), cells.get("Comment", "")) if n)
        more = () if address or not port else ((PORT, port),)
        rows.append(ImportRow(cells.get("Name", ""), address, notes=notes, more=more))
    ignored = sum(1 for c in columns if c not in _WINDOWS_USED)
    other = ngettext(
        "the other column Windows exports", "the other {n} columns Windows exports", ignored
    )
    said = (other.format(n=ignored),) if ignored else ()
    return Parsed(tuple(rows), said)


def _port_address(port: str) -> str:
    """The address a Windows port names ("IP_192.0.2.10_1" is 192.0.2.10); "" for a
    port that isn't one: WSD-…, USB001, TS001 and names ending in ":" such as LPT1: or nul:."""
    address = _IP_PORT.sub("", port.strip())
    numbered = _NUMBERED_IP.match(address)
    if numbered:
        address = numbered.group(1)
    if not address or _LOCAL_PORT.match(address) or not is_hostname(address):
        return ""
    return address


def problem(row: ImportRow) -> str | None:
    port = dict(row.more).get(PORT, "")
    name, address = row.name.strip(), row.address.strip()
    if not name:
        return None
    if not address and port:
        return _("No address: type the printer's address. Its Windows port, {port}, isn't one.") \
            .format(port=port)  # fmt: skip
    if not address and not is_hostname(name):
        return _("No address: the name must then be the printer's name on the network")
    if address and not is_hostname(snmp_host(address)):
        return _("Not a printer name or IP address")
    return ""


def plan(host_list: HostList, rows: Iterable[ImportRow], default_group: str) -> Plan:
    rows = tuple(rows)
    planned = bulk.plan(host_list, rows, default_group, problem=problem)
    known = {h.id for h in host_list.hosts}
    added = [h for h in planned.result.hosts if h.id not in known]
    adds = [i.row for i in planned.items if i.verdict is Verdict.ADD]
    result = planned.result
    for host, row in zip(added, adds, strict=True):
        result = result.update_host(with_info(host, info_of_row(row)))
    return Plan(planned.items, planned.new_groups, result)


def info_of_row(row: ImportRow) -> PrinterInfo:
    cells = dict(row.more)
    return PrinterInfo(
        brand=cells.get("brand", "").strip().upper(),
        model=cells.get("model", "").strip(),
        serial=cells.get("serial", "").strip().upper(),
        asset_tag=cells.get("asset_tag", "").strip(),
        counter_source=counter_source(cells.get("counter_source", "")),
    )


def counter_source(text: str) -> str:
    plain = "".join(text.casefold().split())
    if not plain:
        return SNMP
    for source in COUNTER_SOURCES:
        if plain.startswith(source):
            return source
    if plain.startswith("doc360"):
        return DOC360
    inner = re.search(r"\((.+)\)\s*$", text)
    return inner.group(1).strip() if inner else text.strip()
