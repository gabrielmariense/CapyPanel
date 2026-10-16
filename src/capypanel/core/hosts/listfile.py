"""Reading and writing host list files: JSON with a schema version."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capypanel.core import files
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostList
from capypanel.core.i18n import _

SCHEMA = 1


class HostListFileError(Exception):
    """Base for problems with a host list file. The message is shown to the user."""


class HostListFormatError(HostListFileError):
    """The file isn't a valid host list."""


class HostListTooNewError(HostListFileError):
    """Written by a newer CapyPanel: opening or saving it here could lose data."""


class HostListChangedError(HostListFileError):
    """The file changed on disk since it was opened, e.g. someone else saved a shared list."""


@dataclass(frozen=True)
class FileStamp:
    """Fingerprint of the file's content, to notice changes made by someone else."""

    digest: str


@dataclass(frozen=True)
class LoadedList:
    hosts: HostList
    stamp: FileStamp


def stamp_of(path: Path) -> FileStamp | None:
    try:
        return FileStamp(hashlib.sha256(path.read_bytes()).hexdigest())
    except FileNotFoundError:
        return None


def load(path: Path) -> LoadedList:
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8-sig"))  # -sig: accept files saved by Notepad with a BOM
    except (UnicodeDecodeError, ValueError) as e:
        message = _("This isn't a valid host list file ({error}).").format(error=e)
        raise HostListFormatError(message) from e
    return LoadedList(from_data(data), FileStamp(hashlib.sha256(raw).hexdigest()))


def save(path: Path, host_list: HostList, *, expected: FileStamp | None) -> FileStamp:
    """Save atomically, only if the file is still what was loaded (`expected`; None = new file).

    The check never silently overwrites someone else's changes. What to do instead is
    the caller's choice, e.g. offer to save a copy.
    """
    if stamp_of(path) != expected:
        raise HostListChangedError(_("Someone else has changed the file since you opened it."))
    raw = (json.dumps(to_data(host_list), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    files.write_atomic(path, raw)
    return FileStamp(hashlib.sha256(raw).hexdigest())


def can_write(path: Path) -> bool:
    """Whether saving would work: the folder takes new files (saves swap one in), not read-only."""
    if not path.parent.is_dir() or not files.can_create_files(path.parent):
        return False
    try:
        if path.exists():
            with path.open("r+b"):
                pass
    except OSError:
        return False
    return True


# ---- JSON <-> records ----

_LIST_KEYS = ("schema", "groups", "hosts")
_GROUP_KEYS = ("id", "name", "parent", "profile")
_HOST_KEYS = ("id", "name", "address", "group", "tags", "notes", "profile")


def to_data(host_list: HostList) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "groups": [
            {"id": g.id, "name": g.name, "parent": g.parent, **_profile(g.profile), **g.extra}
            for g in host_list.groups
        ],
        "hosts": [
            {
                "id": h.id,
                "name": h.name,
                "address": h.address,
                "group": h.group,
                "tags": list(h.tags),
                "notes": h.notes,
                **_profile(h.profile),
                **h.extra,
            }
            for h in host_list.hosts
        ],
        **host_list.extra,
    }


def _profile(profile: str) -> dict[str, str]:
    # Written only when set: lists without profiles stay exactly as older versions wrote them.
    return {"profile": profile} if profile else {}


def from_data(data: object) -> HostList:
    if not isinstance(data, dict):
        raise HostListFormatError(_("The file doesn't contain a host list."))
    schema = data.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise HostListFormatError(_("The file has no valid schema version."))
    if schema > SCHEMA:
        raise HostListTooNewError(
            _("This list was saved by a newer version of CapyPanel. Update the app to open it.")
        )
    data = _migrate(data)
    host_list = HostList(
        groups=tuple(_group(item) for item in _items(data, "groups")),
        hosts=tuple(_host(item) for item in _items(data, "hosts")),
        extra=_extra(data, _LIST_KEYS),
    )
    validate(host_list)
    return host_list


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    # No older formats exist yet. Each future schema bump adds one upgrade step here (1 -> 2, ...).
    return data


def validate(host_list: HostList) -> None:
    """The structural rules: unique IDs, references that exist, no group inside itself."""
    ids = [g.id for g in host_list.groups] + [h.id for h in host_list.hosts]
    if len(ids) != len(set(ids)):
        raise HostListFormatError(_("The file has two items with the same ID."))
    group_ids = {g.id for g in host_list.groups}
    for group in host_list.groups:
        if group.parent is not None and group.parent not in group_ids:
            raise HostListFormatError(
                _("Group “{name}” is inside a group that doesn't exist.").format(name=group.name)
            )
    parents = {g.id: g.parent for g in host_list.groups}
    for group in host_list.groups:
        seen, current = set(), group.id
        while current is not None:
            if current in seen:
                raise HostListFormatError(
                    _("Group “{name}” is nested inside itself.").format(name=group.name)
                )
            seen.add(current)
            current = parents[current]
    for host in host_list.hosts:
        if host.group != NO_GROUP and host.group not in group_ids:
            raise HostListFormatError(
                _("Host “{name}” is in a group that doesn't exist.").format(name=host.name)
            )


def _items(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise HostListFormatError(_("“{key}” must be a list.").format(key=key))
    return value


def _extra(item: Mapping[str, Any], known: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if k not in known}


def _text(item: Mapping[str, Any], key: str, *, required: bool = False) -> str:
    value = item.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value):
        raise HostListFormatError(
            _("An item is missing the “{key}” field or has an invalid value for it.").format(
                key=key
            )
        )
    return value


def _group(item: object) -> Group:
    if not isinstance(item, dict):
        raise HostListFormatError(_("A group entry isn't an object."))
    parent = item.get("parent")
    if parent is not None and not isinstance(parent, str):
        raise HostListFormatError(
            _("An item is missing the “{key}” field or has an invalid value for it.").format(
                key="parent"
            )
        )
    return Group(
        id=_text(item, "id", required=True),
        name=_text(item, "name"),
        parent=parent,
        profile=_text(item, "profile"),
        extra=_extra(item, _GROUP_KEYS),
    )


def _host(item: object) -> Host:
    if not isinstance(item, dict):
        raise HostListFormatError(_("A host entry isn't an object."))
    tags = item.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise HostListFormatError(
            _("An item is missing the “{key}” field or has an invalid value for it.").format(
                key="tags"
            )
        )
    return Host(
        id=_text(item, "id", required=True),
        name=_text(item, "name"),
        group=_text(item, "group"),  # "" or missing: no group
        address=_text(item, "address"),
        tags=tuple(tags),
        notes=_text(item, "notes"),
        profile=_text(item, "profile"),
        extra=_extra(item, _HOST_KEYS),
    )
