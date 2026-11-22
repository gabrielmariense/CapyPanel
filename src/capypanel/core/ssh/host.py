"""An SSH host's port and login name, under its entry's "ssh" key; no secret: ssh.exe asks."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.hosts.model import Group, Host, HostList

KEY = "ssh"
DEFAULT_PORT = 22
MAX_PORT = 65535
MAX_LOGIN = 100  # a domain account's user@domain fits
# What Windows' own ssh.exe 9.5 refuses in a name to log in with (see REFUSED_IN_ADDRESS in
# launch.py): DOMAIN\user, user@domain and a name ending in $ still pass.
REFUSED_IN_LOGIN = frozenset("\"&'();<>`{|}")


@dataclass(frozen=True)
class SshInfo:
    port: int = DEFAULT_PORT
    login: str = ""  # "": ssh.exe's config decides, then the Windows user name
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys this version doesn't know


def is_port(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_PORT


def is_login(text: str) -> bool:
    """A name ssh.exe can be given to log in with: no spaces or control characters, no leading
    "-", which ssh.exe would read as an option, and none of REFUSED_IN_LOGIN."""
    return (
        0 < len(text) <= MAX_LOGIN
        and not text.startswith("-")
        and all(c.isprintable() and not c.isspace() and c not in REFUSED_IN_LOGIN for c in text)
    )


def info_of(host: Host) -> SshInfo:
    data = host.extra.get(KEY)
    if not isinstance(data, Mapping):
        return SshInfo()
    port, login = data.get("port"), data.get("login")
    good_port = is_port(port)
    good_login = isinstance(login, str) and is_login(login.strip())
    return SshInfo(
        port=port if good_port else DEFAULT_PORT,  # type: ignore[arg-type]
        login=login.strip() if good_login else "",  # type: ignore[union-attr]
        extra={
            k: v
            for k, v in data.items()
            if not (k == "port" and good_port) and not (k == "login" and good_login)
        },
    )


def with_info(host: Host, info: SshInfo) -> Host:
    """The host with these details. The default port and an empty login aren't written, so
    entries stay short."""
    data: dict[str, Any] = dict(info.extra)  # an odd value kept as found, unless replaced now
    if info.port != DEFAULT_PORT:
        data["port"] = info.port
    if info.login:
        data["login"] = info.login
    extra = {k: v for k, v in host.extra.items() if k != KEY}
    if data:
        extra[KEY] = data
    return replace(host, extra=extra)


def with_login(host: Host, login: str) -> Host:
    """The host with its own name to log in as; "" follows its group again."""
    return with_info(host, replace(info_of(host), login=login))


def group_login(group: Group) -> str:
    """The name a group gives its hosts ("" for none), read as a host's own is."""
    data = group.extra.get(KEY)
    login = data.get("login") if isinstance(data, Mapping) else None
    return login.strip() if isinstance(login, str) and is_login(login.strip()) else ""


def group_login_of(hosts: HostList, group_id: str | None) -> tuple[str, Group | None]:
    """The name a group gives its hosts and the group it comes from: its own, else the nearest
    parent's. ("", None) when none of them sets one."""
    seen: set[str] = set()
    group = hosts.group(group_id) if group_id else None
    while group is not None and group.id not in seen:
        if login := group_login(group):
            return login, group
        seen.add(group.id)
        group = hosts.group(group.parent) if group.parent else None
    return "", None


def login_of(hosts: HostList, host: Host) -> tuple[str, Group | None]:
    """The name the host logs in with and the group it comes from (None: its own, or none at
    all). With none, ssh.exe takes the person's SSH config, then their Windows user name."""
    own = info_of(host).login
    return (own, None) if own else group_login_of(hosts, host.group)


def connect_info(hosts: HostList, host: Host) -> SshInfo:
    """What Connect gives ssh.exe: the host's port, and its own name or its group's."""
    return replace(info_of(host), login=login_of(hosts, host)[0])


def with_group_login(hosts: HostList, group_id: str, login: str) -> HostList:
    """The list with the group's own name to log in as; "" follows its parent again. The rest of
    the group's "ssh" key stays as found; a non-mapping one is replaced, as with_info does."""

    def changed(group: Group) -> Group:
        if group.id != group_id:
            return group
        data = group.extra.get(KEY)
        kept = {k: v for k, v in data.items() if k != "login"} if isinstance(data, Mapping) else {}
        if login:
            kept["login"] = login
        extra = {k: v for k, v in group.extra.items() if k != KEY}
        if kept:
            extra[KEY] = kept
        return replace(group, extra=extra)

    return replace(hosts, groups=tuple(changed(g) for g in hosts.groups))


def logins_in(hosts: HostList) -> list[str]:
    """Every name the list's hosts and groups log in with, A to Z: the pickers' choices."""
    names = {info_of(h).login for h in hosts.hosts} | {group_login(g) for g in hosts.groups}
    names.discard("")
    return sorted(names, key=str.casefold)
