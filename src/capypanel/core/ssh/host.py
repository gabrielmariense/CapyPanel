"""An SSH host's own details: the port and the name to log in as.

They live in the host entry under one key, "ssh", in the host lists Hosts and Profile cleanup
show too: Hosts keeps the key as found when it saves. Odd values are read as the defaults and the
original is kept as found, so opening and saving a list never loses anything. Nothing secret is
kept: Windows' ssh.exe asks for the password, or uses a key, itself."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from capypanel.core.hosts.model import Host

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
    login: str = ""  # the name ssh.exe logs in with; "" leaves it to ssh.exe: its config, then
    # the Windows user name
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
