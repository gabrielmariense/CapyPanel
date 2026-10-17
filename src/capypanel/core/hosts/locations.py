"""Where host lists live (default, personal, shared) and the recent-lists menu."""

import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.hosts import listfile
from capypanel.core.i18n import _

log = logging.getLogger(__name__)

RECENT_KEY = "recent_lists"  # most recent first; the first is reopened at start
LISTS_KEY = "host_lists"  # the lists the user added, besides the default and personal ones
START_KEY = "start_list"  # "last", "default", "personal", or a list file's path
START_LAST, START_DEFAULT, START_PERSONAL = "last", "default", "personal"
RECENT_LIMIT = 10
VIEWS_KEY = "list_views"  # per list file: what it shows first, and where it was left
SHOW_ALL, SHOW_LAST, SHOW_GROUP = "all", "last", "group"


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


def found_lists(shared_dir: Path, user_dir: Path) -> list[Path]:
    """The lists saved in the shared and the user's lists folders, which show up with no adding.
    A shared one another standard user made is left out, as the default list would be."""
    found: list[Path] = []
    for folder, shared in ((shared_dir, True), (user_dir, False)):
        files = sorted(folder.glob("*.json"), key=lambda p: p.stem.casefold())
        for path in files if folder.is_dir() else []:
            if shared and not winsec.made_by_trusted(path):
                log.warning("Host list %s left out: made by another user", path)
                continue
            found.append(path)
    return found


def available_lists(
    prefs: dict[str, Any], *, default: Path, personal: Path, found: list[Path]
) -> list[Path]:
    """Every list this user can pick: the default and personal ones, those in the lists
    folders, then the ones added from elsewhere."""
    lists: list[Path] = []
    for path in (default, personal, *found, *added_lists(prefs)):
        if not any(same_path(path, p) for p in lists):
            lists.append(path)
    return lists


def list_names(paths: list[Path], *, default: Path, personal: Path) -> list[str]:
    """How lists are named everywhere: "Default list", "Personal list", any other by its file
    name. Two files with the same name get their folder's name too."""
    stems = [p.stem.casefold() for p in paths]
    names = []
    for path in paths:
        kind = list_kind(path, default=default, personal=personal)
        if kind is ListKind.DEFAULT:
            names.append(_("Default list"))
        elif kind is ListKind.PERSONAL:
            names.append(_("Personal list"))
        elif stems.count(path.stem.casefold()) > 1:
            names.append(f"{path.stem} ({path.parent.name})")
        else:
            names.append(path.stem)
    return names


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
    """The lists the user keeps. One taken out is forgotten from the recent ones too, or the
    last one used would reopen at the next start and come back."""
    unique: list[Path] = []
    for path in paths:
        if not any(same_path(path, p) for p in unique):
            unique.append(path)
    for gone in added_lists(prefs):
        if not any(same_path(gone, p) for p in unique):
            forget_list(prefs, gone)
    prefs[LISTS_KEY] = [str(p) for p in unique]


def forget_list(prefs: dict[str, Any], path: Path) -> None:
    prefs[RECENT_KEY] = [str(p) for p in recent_lists(prefs) if not same_path(p, path)]


@dataclass(frozen=True)
class ListView:
    """What a list shows when it's opened: All hosts, where it was left, or a chosen group."""

    show: str = SHOW_ALL
    group: str = ""  # with SHOW_GROUP: the group's id ("" = No group)
    last: tuple[str, str] = ("all", "")  # where it was left: the filter's kind and value


def list_view(prefs: dict[str, Any], path: Path) -> ListView:
    saved = prefs.get(VIEWS_KEY)
    entry = saved.get(_view_key(path)) if isinstance(saved, dict) else None
    if not isinstance(entry, dict):
        return ListView()
    show = entry.get("show")
    group, last = entry.get("group"), entry.get("last")
    return ListView(
        show if show in (SHOW_ALL, SHOW_LAST, SHOW_GROUP) else SHOW_ALL,
        group if isinstance(group, str) else "",
        (str(last[0]), str(last[1])) if isinstance(last, list) and len(last) == 2 else ("all", ""),
    )


def set_list_view(prefs: dict[str, Any], path: Path, view: ListView) -> None:
    saved = prefs.get(VIEWS_KEY)
    views = dict(saved) if isinstance(saved, dict) else {}
    views[_view_key(path)] = {"show": view.show, "group": view.group, "last": list(view.last)}
    prefs[VIEWS_KEY] = views


def _view_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def same_path(a: Path, b: Path) -> bool:
    """Whether two paths point to the same file (Windows paths ignore case)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
