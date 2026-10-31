"""Many hosts at once: reading a pasted list or a CSV file, planning what an import would do
(nothing changes until it's applied), and writing hosts out as CSV.

A list is either a header row naming its columns (name, address, group, tags, notes, in any order,
in English or Portuguese; other columns are ignored), or lines of "name, address" without one,
where the address may be left out when the name is the computer's name on the network. A CSV file
must have the header row. Columns are split by a tab (as Excel copies), a semicolon (Excel's CSV
in pt-BR) or a comma; a pasted table whose columns are lined up with spaces works too, with its
header row. A group is a path, its levels joined by "/"; tags are joined by ";" (or ","
in a ";" list)."""

import csv
import ctypes
import io
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from capypanel.core.hosts.model import NO_GROUP, Host, HostList, HostListRuleError, is_hostname
from capypanel.core.i18n import _

PATH = "/"  # between a group path's levels
LOCALE_SLIST = 0x0C  # GetLocaleInfoEx: the list separator
_HEADERS = {
    "name": {"name", "nome", "host", "hostname", "computer", "computador"},
    "address": {"address", "endereco", "ip", "ip address", "endereco ip", "dns"},
    "group": {"group", "grupo", "group path", "group name", "nome do grupo"},
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
    reason: str  # empty for ADD; for SKIP it names the host or row it repeats
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
        return _read((_split(line, delimiter) for line in lines[1:]), columns, delimiter)
    aligned = _aligned(lines)
    if aligned is not None:
        return aligned
    if file:
        return Parsed((), needs_header=True)
    delimiter = _delimiter(lines[0])
    if any(len(_split(line, delimiter)) > 2 for line in lines):
        # Without a header, a third column could be anything: say so rather than guess.
        return Parsed((), needs_header=True)
    return _read((_split(line, delimiter) for line in lines), ["name", "address"], delimiter)


def _fold(text: str) -> str:
    """For matching headers: lower case, no accents, no spaces, "_" or "-" ("Endereço IP" =
    "enderecoip", "GroupName" = "Group_name" = "groupname")."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in plain if not unicodedata.combining(c) and c not in " \t_-")


def _columns(cells: Sequence[str]) -> list[str]:
    """Each header cell's meaning: a known column's key, or the cell as typed."""
    known = {key: {_fold(name) for name in names} for key, names in _HEADERS.items()}
    return [
        next((key for key, names in known.items() if _fold(cell) in names), cell) for cell in cells
    ]


def _header(line: str) -> tuple[str, list[str]] | None:
    """The delimiter and each column's meaning, when the first line names a "name" column."""
    for delimiter in ("\t", ";", ","):
        columns = _columns(_split(line, delimiter))
        if "name" in columns:
            return delimiter, columns
    return None


def _delimiter(line: str) -> str:
    return next((d for d in ("\t", ";", ",") if d in line), ",")


def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), [])


# A cell in a table lined up with spaces: words with one space between them; columns have more.
_ALIGNED_CELL = re.compile(r"\S+(?: \S+)*")


def _aligned(lines: Sequence[str]) -> Parsed | None:
    """A table whose columns are lined up with spaces, as some programs copy one: the header
    row's titles mark where each column starts. None when the first line isn't such a header."""
    titles = list(_ALIGNED_CELL.finditer(lines[0]))
    columns = _columns([t.group() for t in titles])
    if len(titles) < 2 or "name" not in columns:
        return None
    starts = [t.start() for t in titles]

    def cells(line: str) -> list[str]:
        found = _ALIGNED_CELL.findall(line)
        if len(found) == len(starts):
            return found
        # An empty cell, or one that runs into the next: cut where the titles start.
        return [line[a:b] for a, b in zip(starts, [*starts[1:], None], strict=True)]

    return _read((cells(line) for line in lines[1:]), columns, " ")


def _read(rows: Iterable[Sequence[str]], columns: list[str], delimiter: str) -> Parsed:
    known = set(_HEADERS)
    ignored = tuple(c for c in columns if c not in known and c.strip())
    tag_split = "," if delimiter == ";" else ";"
    parsed = []
    for row in rows:
        cells = dict(zip(columns, (_unguarded(c.strip()) for c in row), strict=False))
        tags = (t.strip() for t in cells.get("tags", "").split(tag_split))
        parsed.append(
            ImportRow(
                name=cells.get("name", ""),
                address=cells.get("address", ""),
                group=cells.get("group", "").strip(PATH + " "),
                tags=tuple(t for t in tags if t),
                notes=cells.get("notes", ""),
            )
        )
    return Parsed(tuple(parsed), ignored)


def _unguarded(cell: str) -> str:
    """A cell as it was before a Report wrote it spreadsheet-safe."""
    guarded = cell.startswith(GUARD) and cell[len(GUARD) :].startswith(FORMULA_START)
    return cell[len(GUARD) :] if guarded else cell


# ---- planning ----


def plan(host_list: HostList, rows: Iterable[ImportRow], default_group: str) -> Plan:
    # default_group: where rows without a group go; NO_GROUP leaves them out of every group.
    """What the import would do, row by row, and the list it would make. Nothing is changed:
    the caller saves `result` only when the user confirms."""
    result, items, new_groups = host_list, [], []
    names: dict[str, Host] = {}
    targets: dict[str, Host] = {}
    for host in host_list.hosts:
        names.setdefault(host.name.casefold(), host)
        targets.setdefault(host.target.casefold(), host)
    seen_names: dict[str, int] = {}  # row numbers, from 1
    seen_targets: dict[str, int] = {}
    for number, row in enumerate(rows, 1):
        name, address = row.name.strip(), row.address.strip()
        target = (address or name).casefold()
        path = _path(result, row.group) or _names(host_list, default_group)
        problem = _problem(name, address)
        if problem:
            items.append(Planned(row, Verdict.BAD, problem, path))
            continue
        known = _in_list(host_list, names.get(name.casefold()), targets.get(target))
        repeated = _repeated(seen_names.get(name.casefold()), seen_targets.get(target))
        if known or repeated:
            items.append(Planned(row, Verdict.SKIP, known or repeated, path))
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
        seen_names[name.casefold()] = number
        seen_targets[target] = number
        items.append(Planned(row, Verdict.ADD, "", path))
    return Plan(tuple(items), tuple(new_groups), result)


def _in_list(host_list: HostList, same_name: Host | None, same_address: Host | None) -> str:
    """Which hosts already in the list a row matches, and where they are."""

    def where(host: Host) -> str:
        path = " › ".join(_names(host_list, host.group))
        return _("in “{group}”").format(group=path) if path else _("with no group")

    if same_name is not None and same_name is same_address:
        return _("Already in the list, {place}").format(place=where(same_name))
    found = []
    if same_name is not None:
        found.append(
            _("A host with this name is already in the list, {place}").format(
                place=where(same_name)
            )
        )
    if same_address is not None:
        found.append(
            _("“{name}” has this address, {place}").format(
                name=same_address.name, place=where(same_address)
            )
        )
    return "; ".join(found)


def _repeated(same_name: int | None, same_address: int | None) -> str:
    """The earlier rows of this import a row repeats."""
    if same_name is not None and same_name == same_address:
        return _("Same as row {n}").format(n=same_name)
    found = []
    if same_name is not None:
        found.append(_("Same name as row {n}").format(n=same_name))
    if same_address is not None:
        found.append(_("Same address as row {n}").format(n=same_address))
    return "; ".join(found)


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


# A spreadsheet runs a cell that starts with one of these as a formula.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
GUARD = "'"  # put before such a cell, so it's shown as text; the import takes it off again


def spreadsheet_safe(cell: str) -> str:
    """The cell as plain text in Excel: a name like "=HYPERLINK(...)" is never run."""
    return GUARD + cell if cell.startswith(FORMULA_START) else cell


def write_csv(
    header: Sequence[str],
    rows: Iterable[Sequence[str]],
    delimiter: str = ",",
    *,
    guard: bool = True,
) -> str:
    """guard: cells a spreadsheet would run as formulas are written as text (spreadsheet_safe).
    Off only for text that never reaches a spreadsheet."""
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    writer.writerow([spreadsheet_safe(c) for c in header] if guard else header)
    writer.writerows([spreadsheet_safe(c) for c in row] if guard else row for row in rows)
    return out.getvalue()


def to_csv(rows: Iterable[ImportRow], delimiter: str = ",") -> str:
    """Rows as CSV with a header row: what the import window shows once its table is edited.
    With ";" between columns, tags are joined by "," (the import reads both ways)."""
    between_tags = "," if delimiter == ";" else ";"
    return write_csv(
        ["name", "address", "group", "tags", "notes"],
        ([r.name, r.address, r.group, between_tags.join(r.tags), r.notes] for r in rows),
        delimiter,
        guard=False,  # read back by the import window itself
    )


def host_fields(host_list: HostList, host: Host, between_tags: str = ";") -> dict[str, str]:
    """A host's columns as Import hosts reads them back: its group as a path, tags joined."""
    return {
        "name": host.name,
        "address": host.address,
        "group": PATH.join(_names(host_list, host.group)),
        "tags": between_tags.join(host.tags),
        "notes": host.notes,
    }


def export(host_list: HostList, hosts: Iterable[Host], delimiter: str = ",") -> str:
    """Hosts as CSV that imports back: name, address, group path, tags and notes."""
    between_tags = "," if delimiter == ";" else ";"
    fields = [host_fields(host_list, h, between_tags) for h in hosts]
    keys = ["name", "address", "group", "tags", "notes"]
    return write_csv(keys, ([f[k] for k in keys] for f in fields), delimiter)


def list_separator() -> str:
    """Windows' list separator (Region settings): what Excel splits a CSV file on when it's
    opened, e.g. "," in English and ";" in Portuguese. "," when it can't be read."""
    try:
        text = ctypes.create_unicode_buffer(8)
        found = ctypes.windll.kernel32.GetLocaleInfoEx(None, LOCALE_SLIST, text, len(text))
        if found and text.value in (",", ";", "\t"):
            return text.value
    except (AttributeError, OSError):  # not Windows
        pass
    return ","
