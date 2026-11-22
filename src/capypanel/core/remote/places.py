"""Another PC's folders and management consoles, opened on this PC: nothing runs there."""

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
    return share(host, STARTUP)


def typed_path(host: str, typed: str) -> str:
    r"""Open a path…'s text as File Explorer opens it: `D:\Logs` or `D$\Logs` on `host`, a path on
    its C: (`Users\Public`), or `\\PC\share\…` as is, quotes dropped. ValueError when empty."""
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
    r"""The profile folder of `user` ("DOMAIN\name" or "name") on `host`, the newest when Windows
    made more (`name.DOMAIN`, `name.000`). Raises FileNotFoundError, or OSError (C$ unreadable)."""
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


def require_folder(path: str) -> None:
    """Raises NotADirectoryError unless `path` is a folder: Windows' "open" runs a file, so a typed
    path to a script on the PC would run it here. It reads over the network: off the UI thread."""
    if not os.path.isdir(path):
        raise NotADirectoryError(path)


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
