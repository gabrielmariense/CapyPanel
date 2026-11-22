import csv
import ctypes
import io
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from capypanel.core.hosts.model import NO_GROUP, Host, HostList, HostListRuleError, is_hostname
from capypanel.core.i18n import _

PATH = "/"
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
    group: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    more: tuple[tuple[str, str], ...] = ()


More = Mapping[str, Iterable[str]]


@dataclass(frozen=True)
class Parsed:
    rows: tuple[ImportRow, ...]
    ignored: tuple[str, ...] = ()
    needs_header: bool = False


class Verdict(StrEnum):
    ADD = "add"
    SKIP = "skip"
    BAD = "bad"


@dataclass(frozen=True)
class Planned:
    row: ImportRow
    verdict: Verdict
    reason: str
    group: tuple[str, ...]


@dataclass(frozen=True)
class Plan:
    items: tuple[Planned, ...]
    new_groups: tuple[tuple[str, ...], ...]
    result: HostList

    @property
    def adding(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.ADD)


def parse(text: str, *, file: bool = False, more: More | None = None) -> Parsed:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return Parsed(())
    more = more or {}
    header = _header(lines[0], more)
    if header is not None:
        delimiter, columns = header
        return _read((_split(line, delimiter) for line in lines[1:]), columns, delimiter, more)
    aligned = _aligned(lines, more)
    if aligned is not None:
        return aligned
    if file:
        return Parsed((), needs_header=True)
    delimiter = _delimiter(lines[0])
    if any(len(_split(line, delimiter)) > 2 for line in lines):
        return Parsed((), needs_header=True)
    return _read((_split(line, delimiter) for line in lines), ["name", "address"], delimiter, more)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in plain if not unicodedata.combining(c) and c not in " \t_-")


def _columns(cells: Sequence[str], more: More) -> list[str]:
    named = {**_HEADERS, **more}
    known = {key: {_fold(name) for name in names} for key, names in named.items()}
    return [
        next((key for key, names in known.items() if _fold(cell) in names), cell) for cell in cells
    ]


def _header(line: str, more: More) -> tuple[str, list[str]] | None:
    for delimiter in ("\t", ";", ","):
        columns = _columns(_split(line, delimiter), more)
        if "name" in columns:
            return delimiter, columns
    return None


def _delimiter(line: str) -> str:
    return next((d for d in ("\t", ";", ",") if d in line), ",")


def _split(line: str, delimiter: str) -> list[str]:
    return next(csv.reader([line], delimiter=delimiter), [])


_ALIGNED_CELL = re.compile(r"\S+(?: \S+)*")


def _aligned(lines: Sequence[str], more: More) -> Parsed | None:
    titles = list(_ALIGNED_CELL.finditer(lines[0]))
    columns = _columns([t.group() for t in titles], more)
    if len(titles) < 2 or "name" not in columns:
        return None
    starts = [t.start() for t in titles]

    def cells(line: str) -> list[str]:
        found = _ALIGNED_CELL.findall(line)
        if len(found) == len(starts):
            return found
        return [line[a:b] for a, b in zip(starts, [*starts[1:], None], strict=True)]

    return _read((cells(line) for line in lines[1:]), columns, " ", more)


def _read(rows: Iterable[Sequence[str]], columns: list[str], delimiter: str, more: More) -> Parsed:
    known = set(_HEADERS) | set(more)
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
                more=tuple((key, cells[key]) for key in more if cells.get(key)),
            )
        )
    return Parsed(tuple(parsed), ignored)


def _unguarded(cell: str) -> str:
    guarded = cell.startswith(GUARD) and cell[len(GUARD) :].startswith(FORMULA_START)
    return cell[len(GUARD) :] if guarded else cell


def plan(
    host_list: HostList,
    rows: Iterable[ImportRow],
    default_group: str,
    *,
    problem: Callable[[ImportRow], str | None] | None = None,
) -> Plan:
    result, items, new_groups = host_list, [], []
    names: dict[str, Host] = {}
    targets: dict[str, Host] = {}
    for host in host_list.hosts:
        names.setdefault(host.name.casefold(), host)
        targets.setdefault(host.target.casefold(), host)
    seen_names: dict[str, int] = {}
    seen_targets: dict[str, int] = {}
    for number, row in enumerate(rows, 1):
        name, address = row.name.strip(), row.address.strip()
        target = (address or name).casefold()
        path = _path(result, row.group) or _names(host_list, default_group)
        said = problem(row) if problem is not None else None
        bad = _problem(name, address) if said is None else said
        if bad:
            items.append(Planned(row, Verdict.BAD, bad, path))
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


def place(host_list: HostList, host: Host) -> str:
    path = " › ".join(_names(host_list, host.group))
    return _("in “{group}”").format(group=path) if path else _("with no group")


def listed_at(host_list: HostList, host: Host, typed: str) -> str:
    if host.name.casefold() == typed.strip().casefold():
        return _("Already in the list, {place}").format(place=place(host_list, host))
    return _("“{name}” has this address, {place}").format(
        name=host.name, place=place(host_list, host)
    )


def _in_list(host_list: HostList, same_name: Host | None, same_address: Host | None) -> str:
    if same_name is not None and same_name is same_address:
        return _("Already in the list, {place}").format(place=place(host_list, same_name))
    found = []
    if same_name is not None:
        found.append(
            _("A host with this name is already in the list, {place}").format(
                place=place(host_list, same_name)
            )
        )
    if same_address is not None:
        found.append(
            _("“{name}” has this address, {place}").format(
                name=same_address.name, place=place(host_list, same_address)
            )
        )
    return "; ".join(found)


def _repeated(same_name: int | None, same_address: int | None) -> str:
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
        return _("No address: the name must then be the computer's name on the network")
    return ""


def _path(host_list: HostList, typed: str) -> tuple[str, ...]:
    """A name with "/" is matched whole first: an exported list imports into the same groups."""
    wanted = typed.strip().casefold()
    for group in host_list.groups:
        names = _names(host_list, group.id)
        if wanted and PATH.join(names).casefold() == wanted:
            return names
    return tuple(part.strip() for part in typed.split(PATH) if part.strip())


def _names(host_list: HostList, group_id: str) -> tuple[str, ...]:
    path: list[str] = []
    group = host_list.group(group_id)
    while group is not None:
        path.insert(0, group.name)
        group = host_list.group(group.parent) if group.parent else None
    return tuple(path)


def _group(
    host_list: HostList, path: tuple[str, ...]
) -> tuple[HostList, str, list[tuple[str, ...]]]:
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
    assert parent is not None
    return host_list, parent, made


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
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\n")
    writer.writerow([spreadsheet_safe(c) for c in header] if guard else header)
    writer.writerows([spreadsheet_safe(c) for c in row] if guard else row for row in rows)
    return out.getvalue()


def to_csv(rows: Iterable[ImportRow], delimiter: str = ",", more: Sequence[str] = ()) -> str:
    between_tags = "," if delimiter == ";" else ";"
    return write_csv(
        ["name", "address", "group", "tags", "notes", *more],
        (
            [r.name, r.address, r.group, between_tags.join(r.tags), r.notes]
            + [dict(r.more).get(key, "") for key in more]
            for r in rows
        ),
        delimiter,
        guard=False,
    )


def host_fields(host_list: HostList, host: Host, between_tags: str = ";") -> dict[str, str]:
    return {
        "name": host.name,
        "address": host.address,
        "group": PATH.join(_names(host_list, host.group)),
        "tags": between_tags.join(host.tags),
        "notes": host.notes,
    }


def export(host_list: HostList, hosts: Iterable[Host], delimiter: str = ",") -> str:
    between_tags = "," if delimiter == ";" else ";"
    fields = [host_fields(host_list, h, between_tags) for h in hosts]
    keys = ["name", "address", "group", "tags", "notes"]
    return write_csv(keys, ([f[k] for k in keys] for f in fields), delimiter)


def list_separator() -> str:
    """What Excel splits a CSV on: Windows' list separator ("," in English, ";" in Portuguese)."""
    try:
        text = ctypes.create_unicode_buffer(8)
        found = ctypes.windll.kernel32.GetLocaleInfoEx(None, LOCALE_SLIST, text, len(text))
        if found and text.value in (",", ";", "\t"):
            return text.value
    except (AttributeError, OSError):
        pass
    return ","
