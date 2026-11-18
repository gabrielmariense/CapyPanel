"""Connecting to an SSH host with Windows' own client, ssh.exe, in a console window of its own.
CapyPanel hands it the address, the port and the name to log in as, nothing more: ssh.exe asks
for the password itself, or uses a key, so no password ever passes through CapyPanel.

What reaches ssh.exe comes from a list file anyone who can write to it could edit, so it's
checked first: an address or a name that starts with "-" would be read as an option (ssh's
-oProxyCommand= runs a program), and "--" ends ssh.exe's options before the address anyway."""

import logging
import os
import subprocess
from pathlib import Path

from capypanel.core.hosts.model import MAX_ADDRESS
from capypanel.core.ssh.host import DEFAULT_PORT, SshInfo, is_login, is_port

log = logging.getLogger(__name__)


class SshMissing(Exception):
    """Windows' SSH client isn't installed: it's an optional feature, "OpenSSH Client"."""


def ssh_exe() -> Path | None:
    """Windows' own ssh.exe by its full path, or None when it isn't installed. Never looked up
    through PATH, where another ssh.exe could stand in for it."""
    root = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    path = root / "System32" / "OpenSSH" / "ssh.exe"
    return path if path.is_file() else None


def is_destination(text: str) -> bool:
    """An address or a computer name ssh.exe can be given: no spaces or control characters,
    and no leading "-", which ssh.exe would read as an option."""
    return (
        0 < len(text) <= MAX_ADDRESS
        and not text.startswith("-")
        and all(c.isprintable() and not c.isspace() for c in text)
    )


def command_line(exe: Path, destination: str, info: SshInfo) -> list[str]:
    """ssh.exe and its arguments: the port unless it's 22 and the name unless there's none
    (ssh.exe's own config decides those then), "--", then the address. Raises ValueError for
    an address, port or name ssh.exe would misread."""
    if not is_destination(destination):
        raise ValueError("not an address ssh.exe can take")
    argv = [str(exe)]
    if info.port != DEFAULT_PORT:
        if not is_port(info.port):
            raise ValueError("not a port")
        argv += ["-p", str(info.port)]
    if info.login:
        if not is_login(info.login):
            raise ValueError("not a name ssh.exe can take")
        argv += ["-l", info.login]
    return [*argv, "--", destination]


def connect(destination: str, info: SshInfo) -> subprocess.Popen[bytes]:
    """ssh.exe connecting in a new console window; returns as soon as it has started, and the
    window lives on its own. Raises SshMissing, ValueError or OSError."""
    exe = ssh_exe()
    if exe is None:
        raise SshMissing
    argv = command_line(exe, destination, info)
    log.info("Starting ssh.exe %s", subprocess.list2cmdline(argv[1:]))  # no secret in it
    return subprocess.Popen(  # noqa: S603 -- Windows' own ssh.exe by full path, arguments checked
        argv,
        stdin=None,  # its own console's: the person types into ssh.exe, never into CapyPanel
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
