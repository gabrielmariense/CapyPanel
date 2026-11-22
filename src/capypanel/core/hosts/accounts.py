import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Scope(StrEnum):
    PC = "pc"
    GROUP = "group"
    TAG = "tag"
    ALL = "all"


MAX_TEXT = 256
_ORDER = (Scope.PC, Scope.GROUP, Scope.TAG, Scope.ALL)


WINDOWS = ""  # the Windows account CapyPanel runs as


@dataclass(frozen=True)
class Link:
    user: str
    scope: Scope
    value: str = ""
    list: str = ""
    name: str = ""

    def same_place(self, other: "Link") -> bool:
        return (self.scope, _fold(self.value), _same_file(self.list)) == (
            other.scope, _fold(other.value), _same_file(other.list))  # fmt: skip


@dataclass(frozen=True)
class Place:
    address: str
    list: str = ""
    groups: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _fold(text: str) -> str:
    return text.strip().casefold()


def _same_file(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def same_file(a: str, b: str) -> bool:
    return bool(a) and _same_file(a) == _same_file(b)


def matches(link: Link, place: Place) -> bool:
    if link.scope is Scope.ALL:
        return True
    if link.scope is Scope.PC:
        return bool(place.address) and _fold(link.value) == _fold(place.address)
    if not place.list or _same_file(link.list) != _same_file(place.list):
        return False
    if link.scope is Scope.GROUP:
        return link.value in place.groups
    return _fold(link.value) in {_fold(t) for t in place.tags}


def pick(links: Iterable[Link], place: Place) -> Link | None:
    found = [link for link in links if matches(link, place)]

    def rank(link: Link) -> tuple[int, int]:
        depth = place.groups.index(link.value) if link.scope is Scope.GROUP else 0
        return _ORDER.index(link.scope), depth

    return min(found, key=rank) if found else None


def with_link(links: Sequence[Link], new: Link) -> list[Link]:
    return [*(link for link in links if not link.same_place(new)), new]


def users(links: Iterable[Link]) -> list[str]:
    seen: dict[str, str] = {}
    for link in links:
        if link.user != WINDOWS:
            seen.setdefault(_fold(link.user), link.user)
    return list(seen.values())


def uses(links: Iterable[Link], user: str) -> list[Link]:
    return [link for link in links if _fold(link.user) == _fold(user)]


def credential_name(user: str) -> str:
    return "account/" + _fold(user)


def load(saved: Any) -> list[Link]:
    links = []
    for entry in saved if isinstance(saved, list) else []:
        if not isinstance(entry, Mapping):
            continue
        texts = {k: entry.get(k, "") for k in ("user", "scope", "value", "list", "name")}
        if not all(isinstance(v, str) and len(v) <= 4096 for v in texts.values()):
            continue
        try:
            scope = Scope(texts["scope"])
        except ValueError:
            continue
        user = texts["user"].strip()
        if scope is not Scope.ALL and not texts["value"].strip():
            continue
        if scope in (Scope.GROUP, Scope.TAG) and not texts["list"]:
            continue
        links.append(Link(user, scope, texts["value"].strip(), texts["list"], texts["name"]))
    return links


def dump(links: Iterable[Link]) -> list[dict[str, str]]:
    return [
        {k: v for k, v in (("user", link.user), ("scope", str(link.scope)),
                           ("value", link.value), ("list", link.list), ("name", link.name)) if v}
        for link in links
    ]  # fmt: skip
