"""Whether ssh.exe will ask to trust a server, from ssh.exe's own settings: nothing connects."""

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from capypanel.core.ssh import launch
from capypanel.core.ssh.host import DEFAULT_PORT, SshInfo

TIMEOUT = 5  # s, for each program run
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_NOT_FOUND = 1  # ssh-keygen -F: 0 found, 1 not found, 255 a file it couldn't read
_PROGRAM_DATA = "__PROGRAMDATA__"
# ssh.exe -G lists known_hosts files on one line, unquoted, so "C:\Users\Ana Maria" holds a space:
# a new file starts only at a drive, a UNC path, ~ or __PROGRAMDATA__.
_NEXT_FILE = re.compile(r" (?=[A-Za-z]:[\\/]|[\\/]{2}|~[\\/]|__PROGRAMDATA__)")


def asks_to_trust(destination: str, info: SshInfo) -> bool:
    exe = launch.ssh_exe()
    if exe is None:
        return False
    keygen = exe.with_name("ssh-keygen.exe")
    try:
        argv = launch.command_line(exe, destination, info)
    except ValueError:
        return False
    answer = _run([argv[0], "-G", *argv[1:]])
    if answer is None or answer[0] != 0:
        return False
    settings = settings_of(answer[1])
    if settings.get("stricthostkeychecking") != "ask" or "knownhostscommand" in settings:
        return False
    name = stored_name(settings)
    if not name or not keygen.is_file():
        return False
    for path in known_files(settings):
        if not path.is_file():
            continue
        found = _run([str(keygen), "-F", name, "-f", str(path)])
        if found is None or found[0] != _NOT_FOUND:
            return False
    return True


def settings_of(text: str) -> dict[str, str]:
    settings: dict[str, str] = {}
    for line in text.splitlines():
        key, _space, value = line.strip().partition(" ")
        if key:
            settings.setdefault(key.lower(), value.strip())
    return settings


def stored_name(settings: Mapping[str, str]) -> str:
    if alias := settings.get("hostkeyalias"):
        return alias
    host, port = settings.get("hostname", ""), settings.get("port", str(DEFAULT_PORT))
    if not host or port == str(DEFAULT_PORT):
        return host
    return f"[{host}]:{port}"


def known_files(settings: Mapping[str, str]) -> list[Path]:
    data = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    files = []
    for key in ("userknownhostsfile", "globalknownhostsfile"):
        for part in _NEXT_FILE.split(settings.get(key, "")):
            part = part.strip()
            if not part or part.lower() == "none":
                continue
            if part.startswith(_PROGRAM_DATA):
                part = data + part[len(_PROGRAM_DATA) :]
            elif part.startswith("~"):
                part = str(Path.home()) + part[1:]
            files.append(Path(part))
    return files


def _run(argv: Sequence[str]) -> tuple[int, str] | None:
    try:
        done = subprocess.run(  # noqa: S603 -- Windows' own programs, checked arguments
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=TIMEOUT,
            creationflags=_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode, _text(done.stdout)


def _text(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("mbcs", "replace")
