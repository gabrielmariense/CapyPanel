"""Many printers at once: what Import hosts reads, plus the printers' own columns (brand, model,
serial number, asset tag, page counters), and Windows' own printer export.

A Printers Report saved with the "All details" or "For Import" columns reads back as it was
written, in English or Portuguese. Windows' export is what `Get-Printer | Export-Csv` writes in
Windows PowerShell 5.1: a "#TYPE …" line, then 40 quoted columns. Of those, Name is the name,
PortName the address (its "IP_" prefix dropped), and Location and Comment go into the notes. A
port that isn't an address (WSD-…, USB001, TS001, PORTPROMPT:, nul:) comes in with no address,
marked so in the preview, to be typed there. Nothing here contacts a printer: the first Refresh
does."""

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

# The printers' own columns, by the names a Report writes them under (en and pt-BR) and a few
# a person might type. Matched as Import hosts matches its own: no case, accents or spaces.
MORE: Mapping[str, frozenset[str]] = {
    "brand": frozenset({"brand", "marca", "manufacturer", "fabricante"}),
    "model": frozenset({"model", "modelo"}),
    "serial": frozenset({"serial number", "serial", "nº de série", "número de série", "série"}),
    "asset_tag": frozenset({"asset tag", "asset", "patrimônio", "nº de patrimônio"}),
    "counter_source": frozenset({"counter source", "page counters", "contadores de páginas"}),
}  # each key is among its own names (folded, "asset_tag" is "asset tag"): to_csv reads back
PORT = "port"  # a Windows export row's port, when it isn't an address

_WINDOWS_TYPE = "#TYPE"
_WINDOWS_COLUMNS = {"Name", "PortName", "DriverName"}  # enough to know Windows wrote it
_WINDOWS_USED = ("Name", "PortName", "Location", "Comment")
_IP_PORT = re.compile(r"^IP_", re.IGNORECASE)
_NUMBERED_IP = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})_\d+$")
_LOCAL_PORT = re.compile(r"^(?:WSD-.*|USB\d+|TS\d+|.*:)$", re.IGNORECASE)


def parse(text: str, *, file: bool = False) -> Parsed:
    """Windows' printer export, or anything Import hosts reads, with the printers' columns."""
    windows = read_windows_export(text)
    if windows is not None:
        return windows
    return bulk.parse(text, file=file, more=MORE)


# ---- Windows' export ----


def read_windows_export(text: str) -> Parsed | None:
    """The rows of `Get-Printer | Export-Csv`; None when the text isn't one."""
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
    """The address a Windows printer port names. "IP_192.0.2.10", "192.0.2.10" and
    "IP_192.0.2.10_1" (Windows' second port to the same printer) are 192.0.2.10; a port named
    after the printer's network name is that name. WSD-…, USB001, TS001, LPT1:, COM1:, FILE:,
    PORTPROMPT:, nul: and other names ending in ":" are no address."""
    address = _IP_PORT.sub("", port.strip())
    numbered = _NUMBERED_IP.match(address)
    if numbered:
        address = numbered.group(1)
    if not address or _LOCAL_PORT.match(address) or not is_hostname(address):
        return ""
    return address


# ---- planning ----


def problem(row: ImportRow) -> str | None:
    """A printer row's own check, run by bulk.plan in place of the hosts' one: an address may
    start with https:// (for the printer's web page), and a Windows port that isn't an address
    is said as such. None: the hosts' own check applies."""
    port = dict(row.more).get(PORT, "")
    name, address = row.name.strip(), row.address.strip()
    if not name:
        return None
    if not address and port:
        # The action first: a long WSD port name runs past the column's edge (Satya).
        return _("No address: type the printer's address. Its Windows port, {port}, isn't one.") \
            .format(port=port)  # fmt: skip
    if not address and not is_hostname(name):
        return _("No address: the name must then be the printer's name on the network")
    if address and not is_hostname(snmp_host(address)):
        return _("Not a printer name or IP address")
    return ""


def plan(host_list: HostList, rows: Iterable[ImportRow], default_group: str) -> Plan:
    """What the import would do. The printers it adds carry their brand, model, serial number,
    asset tag and page counters. Nothing changes until the caller saves `result`."""
    rows = tuple(rows)
    planned = bulk.plan(host_list, rows, default_group, problem=problem)
    known = {h.id for h in host_list.hosts}
    added = [h for h in planned.result.hosts if h.id not in known]  # in the rows' order
    adds = [i.row for i in planned.items if i.verdict is Verdict.ADD]
    result = planned.result
    for host, row in zip(added, adds, strict=True):
        result = result.update_host(with_info(host, info_of_row(row)))
    return Plan(planned.items, planned.new_groups, result)


def info_of_row(row: ImportRow) -> PrinterInfo:
    """A row's printer columns, as Add printer would save them."""
    cells = dict(row.more)
    return PrinterInfo(
        brand=cells.get("brand", "").strip().upper(),
        model=cells.get("model", "").strip(),
        serial=cells.get("serial", "").strip().upper(),
        asset_tag=cells.get("asset_tag", "").strip(),
        counter_source=counter_source(cells.get("counter_source", "")),
    )


def counter_source(text: str) -> str:
    """The page counters' source from a Report cell: "SNMP", "Doc360 MPS", or "Unknown (x)" as
    the Report writes a source this version doesn't know (kept as x). Empty is SNMP."""
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
