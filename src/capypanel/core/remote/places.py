"""Opening another PC's folders and management consoles on this PC: File Explorer over its admin
shares (C$, D$…) and Windows' consoles pointed at it. Nothing runs on the other PC; Windows asks
for a password itself when the user's own account isn't let in."""

import os
import re
from enum import StrEnum
from pathlib import PureWindowsPath

STARTUP = r"ProgramData\Microsoft\Windows\Start Menu\Programs\Startup"  # every user's
_DRIVE = re.compile(r"^([A-Za-z])(?::|\$)")  # "D:\…", "D:", "D$\…"


class Console(StrEnum):
    COMPUTER_MANAGEMENT = "compmgmt.msc"
    EVENT_VIEWER = "eventvwr.exe"
    SERVICES = "services.msc"


def share(host: str, path: str = "") -> str:
    r"""`path` on `host`'s C: drive, as `\\host\C$\path`."""
    return _join(f"\\\\{host}\\C$", path)


def startup_folder(host: str) -> str:
    """The Startup folder every user of `host` shares."""
    return share(host, STARTUP)


def typed_path(host: str, typed: str) -> str:
    r"""What someone typed in Open a path…, as a path File Explorer opens: `D:\Logs` or
    `D$\Logs` on `host`, a path on its C: drive (`Users\Public`), or a full `\\PC\share\…` kept as
    it is. Quotes around it, as File Explorer's "Copy as path" adds, are dropped. Raises
    ValueError when nothing is left."""
    path = typed.strip().strip('"').strip().replace("/", "\\")
    if not path.strip("\\"):
        raise ValueError("no path")
    if path.startswith("\\\\"):
        return path
    drive = _DRIVE.match(path)
    if drive:
        return _join(f"\\\\{host}\\{drive.group(1).upper()}$", path[drive.end() :])
    return share(host, path)


def user_folder(host: str, user: str) -> str:
    r"""The profile folder of `user` ("DOMAIN\name" or "name") on `host`. Windows names a
    second profile for the same name `name.DOMAIN` or `name.000`; then the newest one is picked.
    Raises FileNotFoundError (and OSError when `host`'s C$ can't be read)."""
    name = user.rpartition("\\")[2]
    folders = share(host, "Users")
    exact = _join(folders, name)
    if os.path.isdir(exact):
        return exact
    prefix = f"{name.casefold()}."
    found = [
        entry
        for entry in os.scandir(folders)
        if entry.is_dir() and entry.name.casefold().startswith(prefix)
    ]
    if not found:
        raise FileNotFoundError(f"no profile folder for {name}")
    return max(found, key=lambda entry: entry.stat().st_mtime).path


def open_folder(path: str) -> None:
    """Opens `path` in File Explorer. Raises OSError when Windows can't."""
    os.startfile(path)  # noqa: S606 (Windows' own "open", as a double-click)


def open_console(host: str, console: Console) -> None:
    """Opens one of Windows' management consoles pointed at `host`. Windows asks to elevate when
    the console needs it. Raises OSError."""
    # Each console's own way to name a PC: "/computer=" for the MMC ones, a plain \\name for
    # Event Viewer.
    target = f"\\\\{host}" if console is Console.EVENT_VIEWER else f"/computer={host}"
    os.startfile(console.value, arguments=target)  # noqa: S606


def _join(root: str, path: str) -> str:
    parts = [part for part in PureWindowsPath(path.strip("\\")).parts if part not in ("", ".")]
    return "\\".join([root, *parts])
