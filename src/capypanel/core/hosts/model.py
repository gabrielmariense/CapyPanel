"""Hosts, groups and the list that holds them. Records are immutable: edits return a new list."""

import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.i18n import _


class HostListRuleError(ValueError):
    """An edit that would break a rule of the list (e.g. a host in a group that doesn't exist)."""


MAX_ADDRESS = 253  # the longest DNS name
# A computer name or IP address: letters, digits, "-" and "_", in parts joined by dots.
_HOSTNAME = re.compile(r"^[A-Za-z0-9_]([A-Za-z0-9_-]{0,62})(\.[A-Za-z0-9_]([A-Za-z0-9_-]{0,62}))*$")


def is_hostname(text: str) -> bool:
    return len(text) <= MAX_ADDRESS and bool(_HOSTNAME.match(text))


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    parent: str | None = None  # None = top level
    profile: str = ""  # connection profile id for the hosts inside; "" = from the parent
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys this version doesn't know


@dataclass(frozen=True)
class Host:
    id: str
    name: str
    group: str
    address: str = ""
    tags: tuple[str, ...] = ()
    notes: str = ""
    profile: str = ""  # connection profile id; "" = the group's
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> str:
        """What to connect to: the address, or the name when no address was typed."""
        return self.address or self.name

    @property
    def connect_address(self) -> str:
        """The address, or the name when it's a valid computer name; "" when neither works."""
        if self.address:
            return self.address
        return self.name if is_hostname(self.name) else ""


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

    def profile_of(
        self, host: Host, exists: Callable[[str], bool] = lambda _id: True
    ) -> tuple[str, Group | None]:
        """The host's connection profile id and the group it comes from (None: the host's own).
        A profile that doesn't `exist` is skipped, so the nearest group's applies instead.
        ("", None) when neither the host nor any group around it sets one that exists."""
        if host.profile and exists(host.profile):
            return host.profile, None
        return self.group_profile(host.group, exists)

    def group_profile(
        self, group_id: str | None, exists: Callable[[str], bool] = lambda _id: True
    ) -> tuple[str, Group | None]:
        """The profile a group gives its hosts: its own, else the nearest parent's."""
        seen: set[str] = set()
        group = self.group(group_id) if group_id else None
        while group is not None and group.id not in seen:
            if group.profile and exists(group.profile):
                return group.profile, group
            seen.add(group.id)
            group = self.group(group.parent) if group.parent else None
        return "", None

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

    def set_group_profile(self, group_id: str, profile: str) -> "HostList":
        self._require_group(group_id)
        groups = tuple(replace(g, profile=profile) if g.id == group_id else g for g in self.groups)
        return replace(self, groups=groups)

    def set_hosts_profile(self, host_ids: Iterable[str], profile: str) -> "HostList":
        """Sets several hosts at once; "" makes them follow their group again."""
        wanted = set(host_ids)
        hosts = tuple(replace(h, profile=profile) if h.id in wanted else h for h in self.hosts)
        return replace(self, hosts=hosts)

    def arrange_groups(self, order: Sequence[tuple[str, str | None]]) -> "HostList":
        """Every group's new parent, in the new order (siblings show in this order). Used by
        drag and drop, Manage groups and Sort A–Z. A group can't end up inside itself."""
        if sorted(gid for gid, _p in order) != sorted(g.id for g in self.groups):
            raise HostListRuleError(_("The groups changed meanwhile; try again."))
        parents = dict(order)
        for group_id in parents:
            seen, current = {group_id}, parents[group_id]
            while current is not None:
                if current in seen or current not in parents:
                    raise HostListRuleError(_("A group can't be moved inside itself."))
                seen.add(current)
                current = parents[current]
        by_id = {g.id: g for g in self.groups}
        groups = tuple(replace(by_id[gid], parent=parent) for gid, parent in order)
        return replace(self, groups=groups)

    def move_group(self, group_id: str, parent: str | None) -> "HostList":
        """Puts the group, with everything inside it, into `parent` (None: the top level),
        after the groups already there."""
        group = self.group(group_id)
        if group is None:
            raise HostListRuleError(_("That group doesn't exist."))
        if parent is not None:
            self._require_group(parent)
            if parent in self.subtree(group_id):
                raise HostListRuleError(_("A group can't be moved inside itself."))
        if group.parent == parent:
            return self
        others = tuple(g for g in self.groups if g.id != group_id)
        return replace(self, groups=(*others, replace(group, parent=parent)))

    def move_hosts(self, host_ids: Iterable[str], group_id: str) -> "HostList":
        self._require_group(group_id)
        wanted = set(host_ids)
        hosts = tuple(replace(h, group=group_id) if h.id in wanted else h for h in self.hosts)
        return replace(self, hosts=hosts)

    def can_keep_contents(self, group_id: str) -> bool:
        """Whether removing the group can move what's inside it up a level. Hosts always need
        a group, so a top-level group's own hosts have nowhere to go."""
        group = self.group(group_id)
        return group is not None and (
            group.parent is not None or not any(h.group == group_id for h in self.hosts)
        )

    def remove_group(self, group_id: str, *, keep_contents: bool = False) -> "HostList":
        """Removes the group. keep_contents moves its hosts and groups up a level, into its
        parent; otherwise the groups nested in it and their hosts go with it."""
        self._require_group(group_id)
        if keep_contents:
            if not self.can_keep_contents(group_id):
                raise HostListRuleError(_("Move this group's hosts to another group first."))
            group = self.group(group_id)
            parent = group.parent if group else None
            groups = tuple(
                replace(g, parent=parent) if g.parent == group_id else g
                for g in self.groups
                if g.id != group_id
            )
            hosts = tuple(
                replace(h, group=parent) if h.group == group_id and parent else h
                for h in self.hosts
            )
            return replace(self, groups=groups, hosts=hosts)
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
        profile: str = "",
    ) -> tuple["HostList", Host]:
        self._require_group(group)
        host = Host(
            id=self.new_id("h"),
            name=_required_name(name),
            group=group,
            address=address.strip(),
            tags=clean_tags(tags),
            notes=notes,
            profile=profile,
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
