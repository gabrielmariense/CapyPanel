"""Where host lists live (default, personal, shared) and the recent-lists menu."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.hosts import listfile

RECENT_KEY = "recent_lists"  # most recent first; the first is reopened at start
LISTS_KEY = "host_lists"  # the lists the user added, besides the default and personal ones
START_KEY = "start_list"  # "last", "default", "personal", or a list file's path
START_LAST, START_DEFAULT, START_PERSONAL = "last", "default", "personal"
RECENT_LIMIT = 10


class ListKind(StrEnum):
    DEFAULT = "default"  # shared by everyone on the PC; editable where Windows allows
    PERSONAL = "personal"  # the user's own, in their private CapyPanel folder
    SHARED = "shared"  # any other file the user picked, e.g. on a network share


class Access(StrEnum):
    MISSING = "missing"
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"
    UNTRUSTED = "untrusted"  # a shared file another standard user made: not used


def list_kind(path: Path, *, default: Path, personal: Path) -> ListKind:
    if same_path(path, default):
        return ListKind.DEFAULT
    if same_path(path, personal):
        return ListKind.PERSONAL
    return ListKind.SHARED


def list_access(path: Path, *, shared: bool = False) -> Access:
    """What the user can do with a list file. Windows permissions decide, for every kind of
    list. A `shared` one (the default list) must also be made by an administrator or this user."""
    if not path.is_file():
        return Access.MISSING
    if shared and not winsec.made_by_trusted(path):
        return Access.UNTRUSTED
    if not listfile.can_write(path):
        return Access.READ_ONLY
    return Access.READ_WRITE


def startup_order(prefs: dict[str, Any], *, default: Path, personal: Path) -> list[Path]:
    """Lists to try at start, best first. The personal list is last: it's created if missing."""
    choice = prefs.get(START_KEY, START_LAST)
    if choice == START_DEFAULT:
        first: Path | None = default
    elif choice == START_PERSONAL:
        first = personal
    elif isinstance(choice, str) and choice and choice != START_LAST:
        first = Path(choice)
    else:
        recent = recent_lists(prefs)
        first = recent[0] if recent else None
    order: list[Path] = []
    for path in (first, default, personal):
        if path is not None and not any(same_path(path, p) for p in order):
            order.append(path)
    return order


def recent_lists(prefs: dict[str, Any]) -> list[Path]:
    value = prefs.get(RECENT_KEY)
    if not isinstance(value, list):
        return []
    return [Path(p) for p in value if isinstance(p, str) and p]


def remember_list(prefs: dict[str, Any], path: Path) -> None:
    """Puts `path` first in the recent lists (the first one is reopened at start)."""
    others = [p for p in recent_lists(prefs) if not same_path(p, path)]
    prefs[RECENT_KEY] = [str(path), *map(str, others)][:RECENT_LIMIT]


def added_lists(prefs: dict[str, Any]) -> list[Path]:
    value = prefs.get(LISTS_KEY)
    if value is None:
        value = prefs.get(RECENT_KEY)  # before the Host lists window, the recent ones
    if not isinstance(value, list):
        return []
    return [Path(p) for p in value if isinstance(p, str) and p]


def set_added_lists(prefs: dict[str, Any], paths: list[Path]) -> None:
    unique: list[Path] = []
    for path in paths:
        if not any(same_path(path, p) for p in unique):
            unique.append(path)
    prefs[LISTS_KEY] = [str(p) for p in unique]


def forget_list(prefs: dict[str, Any], path: Path) -> None:
    prefs[RECENT_KEY] = [str(p) for p in recent_lists(prefs) if not same_path(p, path)]


def same_path(a: Path, b: Path) -> bool:
    """Whether two paths point to the same file (Windows paths ignore case)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
