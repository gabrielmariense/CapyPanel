"""Hosts, groups and the list that holds them. Records are immutable: edits return a new list."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.i18n import _


class HostListRuleError(ValueError):
    """An edit that would break a rule of the list (e.g. a host in a group that doesn't exist)."""


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    parent: str | None = None  # None = top level
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys this version doesn't know


@dataclass(frozen=True)
class Host:
    id: str
    name: str
    group: str
    address: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> str:
        """What to connect to: the address, or the name when no address was typed."""
        return self.address or self.name


def clean_tags(tags: Iterable[str]) -> tuple[str, ...]:
    """Trimmed, no blanks, no duplicates, typed order kept."""
    seen: dict[str, None] = {}
    for tag in tags:
        tag = tag.strip()
        if tag:
            seen.setdefault(tag, None)
    return tuple(seen)


@dataclass(frozen=True)
class HostList:
    groups: tuple[Group, ...] = ()
    hosts: tuple[Host, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    # ---- lookups ----

    def group(self, group_id: str) -> Group | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def host(self, host_id: str) -> Host | None:
        return next((h for h in self.hosts if h.id == host_id), None)

    def children(self, group_id: str | None) -> tuple[Group, ...]:
        return tuple(g for g in self.groups if g.parent == group_id)

    def subtree(self, group_id: str) -> set[str]:
        """The group and every group nested under it, at any depth."""
        found = {group_id}
        frontier = [group_id]
        while frontier:
            for child in self.children(frontier.pop()):
                if child.id not in found:
                    found.add(child.id)
                    frontier.append(child.id)
        return found

    def hosts_in(self, group_id: str, *, nested: bool = True) -> tuple[Host, ...]:
        ids = self.subtree(group_id) if nested else {group_id}
        return tuple(h for h in self.hosts if h.group in ids)

    def all_tags(self) -> dict[str, int]:
        """Every tag in use, with how many hosts carry it."""
        counts: dict[str, int] = {}
        for host in self.hosts:
            for tag in host.tags:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    # ---- edits (each returns a new list) ----

    def new_id(self, prefix: str) -> str:
        taken = {g.id for g in self.groups} | {h.id for h in self.hosts}
        while True:
            candidate = prefix + uuid.uuid4().hex[:12]
            if candidate not in taken:
                return candidate

    def add_group(self, name: str, parent: str | None = None) -> tuple["HostList", Group]:
        if parent is not None and self.group(parent) is None:
            raise HostListRuleError(_("The parent group doesn't exist."))
        group = Group(id=self.new_id("g"), name=_required_name(name), parent=parent)
        return replace(self, groups=(*self.groups, group)), group

    def rename_group(self, group_id: str, name: str) -> "HostList":
        self._require_group(group_id)
        name = _required_name(name)
        groups = tuple(replace(g, name=name) if g.id == group_id else g for g in self.groups)
        return replace(self, groups=groups)

    def remove_group(self, group_id: str) -> "HostList":
        """Removes the group, the groups nested in it, and their hosts."""
        self._require_group(group_id)
        gone = self.subtree(group_id)
        return replace(
            self,
            groups=tuple(g for g in self.groups if g.id not in gone),
            hosts=tuple(h for h in self.hosts if h.group not in gone),
        )

    def add_host(
        self,
        name: str,
        group: str,
        *,
        address: str = "",
        tags: Iterable[str] = (),
        notes: str = "",
    ) -> tuple["HostList", Host]:
        self._require_group(group)
        host = Host(
            id=self.new_id("h"),
            name=_required_name(name),
            group=group,
            address=address.strip(),
            tags=clean_tags(tags),
            notes=notes,
        )
        return replace(self, hosts=(*self.hosts, host)), host

    def update_host(self, host: Host) -> "HostList":
        """Replaces the host with the same ID; typed fields are cleaned the same way as on add."""
        if self.host(host.id) is None:
            raise HostListRuleError(_("That host is no longer in the list."))
        self._require_group(host.group)
        host = replace(
            host,
            name=_required_name(host.name),
            address=host.address.strip(),
            tags=clean_tags(host.tags),
        )
        return replace(self, hosts=tuple(host if h.id == host.id else h for h in self.hosts))

    def remove_hosts(self, host_ids: Iterable[str]) -> "HostList":
        gone = set(host_ids)
        return replace(self, hosts=tuple(h for h in self.hosts if h.id not in gone))

    def _require_group(self, group_id: str) -> None:
        if self.group(group_id) is None:
            raise HostListRuleError(_("That group doesn't exist."))


def _required_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HostListRuleError(_("A name is required."))
    return name
