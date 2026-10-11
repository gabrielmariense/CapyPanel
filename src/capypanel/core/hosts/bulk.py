"""Many hosts at once: reading a pasted list or a CSV file, planning what an import would do
(nothing changes until it's applied), and writing hosts out as CSV.

A list is either a header row naming its columns (name, address, group, tags, notes, in any order,
in English or Portuguese; other columns are ignored), or lines of "name, address" without one,
where the address may be left out when the name is the computer's name on the network. A CSV file
must have the header row. Columns are split by a tab (as Excel copies), a semicolon (Excel's CSV
in pt-BR) or a comma. A group is a path, its levels joined by "/"; tags are joined by ";" (or ","
in a ";" list)."""

import csv
import io
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from capypanel.core.hosts.model import NO_GROUP, Host, HostList, HostListRuleError, is_hostname
from capypanel.core.i18n import _

PATH = "/"  # between a group path's levels
_HEADERS = {
    "name": {"name", "nome", "host", "hostname", "computer", "computador"},
    "address": {"address", "endereco", "ip", "ip address", "endereco ip", "dns"},
    "group": {"group", "grupo", "group path"},
    "tags": {"tags", "tag", "etiquetas", "marcadores"},
    "notes": {"notes", "note", "notas", "nota", "observacoes", "observacao"},
}


@dataclass(frozen=True)
class ImportRow:
    name: str
    address: str = ""
    group: str = ""  # a path as typed; "" = the group picked for the import
    tags: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class Parsed:
    rows: tuple[ImportRow, ...]
    ignored: tuple[str, ...] = ()  # header columns CapyPanel doesn't use
    # Columns it can't name: more than a name and an address, or a file, with no header row.
    # Then there are no rows.
    needs_header: bool = False


class Verdict(StrEnum):
    ADD = "add"
    SKIP = "skip"  # a host that's already there: left alone, never overwritten
    BAD = "bad"  # can't be added as it is


@dataclass(frozen=True)
class Planned:
    row: ImportRow
    verdict: Verdict
    reason: str  # empty for ADD
    group: tuple[str, ...]  # where it goes, as group names from the top


@dataclass(frozen=True)
class Plan:
    items: tuple[Planned, ...]
    new_groups: tuple[tuple[str, ...], ...]  # paths the import creates
    result: HostList  # the list as it would be after the import

    @property
    def adding(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.ADD)


# ---- reading ----


def parse(text: str, *, file: bool = False) -> Parsed:
    """file: read from a CSV file, which must start with a header row. Pasted text may also be
    plain "name, address" lines."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return Parsed(())
    header = _header(lines[0])
    if header is not None:
        delimiter, columns = header
        return _read(lines[1:], delimiter, columns)
    if file:
        return Parsed((), needs_header=True)
    delimiter = _delimiter(lines[0])
    if any(len(_split(line, delimiter)) > 2 for line in lines):
        # Without a header, a third column could be anything: say so rather than guess.
        return Parsed((), needs_header=True)
    return _read(lines, delimiter, ["name", "address"])


def _fold(text: str) -> str:
    """For matching headers: lower case, no accents ("Endereço" = "endereco")."""
    plain = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(c for c in plain if not unicodedata.combining(c))


def _header(line: str) -> tuple[str, list[str]] | None:
    """The delimiter and each column's meaning, when the first line names a "name" column."""
    for delimiter in ("\t", ";", ","):
        cells = _split(line, delimiter)
        columns = [
            next((key for key, names in _HEADERS.items() if _fold(cell) in names), cell)
            for cell in cells
        ]
        if "name" in columns:
            return delimiter, columns
    return None


def _delimiter(line: str) -> str:
    return next((d for d in ("\t", ";", ",") if d in line), ",")


def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), [])


def _read(lines: Sequence[str], delimiter: str, columns: list[str]) -> Parsed:
    known = set(_HEADERS)
    ignored = tuple(c for c in columns if c not in known and c.strip())
    tag_split = "," if delimiter == ";" else ";"
    rows = []
    for line in lines:
        cells = dict(zip(columns, (c.strip() for c in _split(line, delimiter)), strict=False))
        tags = (t.strip() for t in cells.get("tags", "").split(tag_split))
        rows.append(
            ImportRow(
                name=cells.get("name", ""),
                address=cells.get("address", ""),
                group=cells.get("group", "").strip(PATH + " "),
                tags=tuple(t for t in tags if t),
                notes=cells.get("notes", ""),
            )
        )
    return Parsed(tuple(rows), ignored)


# ---- planning ----


def plan(host_list: HostList, rows: Iterable[ImportRow], default_group: str) -> Plan:
    # default_group: where rows without a group go; NO_GROUP leaves them out of every group.
    """What the import would do, row by row, and the list it would make. Nothing is changed:
    the caller saves `result` only when the user confirms."""
    result, items, new_groups = host_list, [], []
    names = {h.name.casefold() for h in host_list.hosts}
    targets = {h.target.casefold() for h in host_list.hosts}
    seen_names: set[str] = set()
    seen_targets: set[str] = set()
    for row in rows:
        name, address = row.name.strip(), row.address.strip()
        target = (address or name).casefold()
        path = _path(result, row.group) or _names(host_list, default_group)
        problem = _problem(name, address)
        if problem:
            items.append(Planned(row, Verdict.BAD, problem, path))
            continue
        if name.casefold() in names or target in targets:
            items.append(Planned(row, Verdict.SKIP, _("Already in the list"), path))
            continue
        if name.casefold() in seen_names or target in seen_targets:
            items.append(Planned(row, Verdict.SKIP, _("Repeated in this import"), path))
            continue
        result, group_id, made = _group(result, path) if path else (result, NO_GROUP, [])
        new_groups += [p for p in made if p not in new_groups]
        try:
            result, _host = result.add_host(
                name, group_id, address=address, tags=row.tags, notes=row.notes
            )
        except HostListRuleError as e:
            items.append(Planned(row, Verdict.BAD, str(e), path))
            continue
        seen_names.add(name.casefold())
        seen_targets.add(target)
        items.append(Planned(row, Verdict.ADD, "", path))
    return Plan(tuple(items), tuple(new_groups), result)


def _problem(name: str, address: str) -> str:
    if not name:
        return _("No name")
    if address and not is_hostname(address):
        return _("Not a computer name or IP address")
    if not address and not is_hostname(name):
        # With no address, CapyPanel connects by the name, so it must be the computer's own.
        return _("No address: the name must then be the computer's name on the network")
    return ""


def _path(host_list: HostList, typed: str) -> tuple[str, ...]:
    """The typed path's levels. A group whose own name has a "/" is found by its whole path
    first, so a list exported and imported back lands in the same groups."""
    wanted = typed.strip().casefold()
    for group in host_list.groups:
        names = _names(host_list, group.id)
        if wanted and PATH.join(names).casefold() == wanted:
            return names
    return tuple(part.strip() for part in typed.split(PATH) if part.strip())


def _names(host_list: HostList, group_id: str) -> tuple[str, ...]:
    """A group's path, as names from the top."""
    path: list[str] = []
    group = host_list.group(group_id)
    while group is not None:
        path.insert(0, group.name)
        group = host_list.group(group.parent) if group.parent else None
    return tuple(path)


def _group(
    host_list: HostList, path: tuple[str, ...]
) -> tuple[HostList, str, list[tuple[str, ...]]]:
    """The group at `path` (names matched without regard to case), making the missing levels.
    Returns the list, the group's id, and the paths it made."""
    made: list[tuple[str, ...]] = []
    parent: str | None = None
    for depth, name in enumerate(path):
        found = next(
            (g for g in host_list.children(parent) if g.name.casefold() == name.casefold()), None
        )
        if found is None:
            host_list, found = host_list.add_group(name, parent)
            made.append(path[: depth + 1])
        parent = found.id
    assert parent is not None  # a path always has a level
    return host_list, parent, made


# ---- writing ----


def to_csv(rows: Iterable[ImportRow]) -> str:
    """Rows as CSV with a header row: what the import window shows once its table is edited."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["name", "address", "group", "tags", "notes"])
    for row in rows:
        writer.writerow([row.name, row.address, row.group, ";".join(row.tags), row.notes])
    return out.getvalue()


def export(host_list: HostList, hosts: Iterable[Host]) -> str:
    """Hosts as CSV that imports back: name, address, group path, tags and notes."""
    return to_csv(
        ImportRow(h.name, h.address, PATH.join(_names(host_list, h.group)), h.tags, h.notes)
        for h in hosts
    )
