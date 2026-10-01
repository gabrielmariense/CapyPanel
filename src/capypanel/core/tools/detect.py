"""Finding a tool's program on this PC: the path the user set, then where Windows says the
program was installed, then the usual folders, then PATH. Nothing is ever downloaded."""

import os
import shutil
import winreg
from collections.abc import Iterator
from pathlib import Path

from capypanel.core.tools.definitions import ToolDefinition

_UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"


def find_executable(tool: ToolDefinition) -> Path | None:
    for candidate in candidates(tool):
        if candidate.is_file():
            return candidate
    return None


def candidates(tool: ToolDefinition) -> Iterator[Path]:
    if tool.executable:
        yield Path(os.path.expandvars(tool.executable))
        return  # a path the user chose is final: no silent fallback to another copy
    d = tool.detect
    if d.exe:
        for folder in installed_folders(d.installed_as):
            yield folder / d.exe
    for path in d.paths:
        expanded = os.path.expandvars(path)
        if "%" not in expanded:  # a variable this PC doesn't have, e.g. %ProgramFiles(x86)%
            yield Path(expanded)
    if d.exe:
        found = shutil.which(d.exe)
        if found:
            yield Path(found)


def installed_folders(names: tuple[str, ...]) -> Iterator[Path]:
    """Install folders of programs whose name in "Installed apps" starts with one of `names`.
    Finds tools installed anywhere, e.g. C:\\Programas instead of C:\\Program Files."""
    wanted = tuple(n.casefold() for n in names)
    if not wanted:
        return
    for display_name, location, uninstaller in _installed_programs():
        if not display_name.casefold().startswith(wanted):
            continue
        if location:
            yield Path(location)
        elif uninstaller:
            # No install location recorded: the uninstaller usually sits in the install folder.
            yield Path(
                uninstaller.strip().split('"')[1] if uninstaller.startswith('"') else uninstaller
            ).parent


def _installed_programs() -> Iterator[tuple[str, str, str]]:
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for root, view in [(winreg.HKEY_LOCAL_MACHINE, v) for v in views] + [
        (winreg.HKEY_CURRENT_USER, 0)
    ]:
        try:
            key = winreg.OpenKey(root, _UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, sub_name) as sub:
                        yield (
                            _value(sub, "DisplayName"),
                            _value(sub, "InstallLocation"),
                            _value(sub, "UninstallString"),
                        )
                except OSError:
                    continue


def _value(key: winreg.HKEYType, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return value if isinstance(value, str) else ""
