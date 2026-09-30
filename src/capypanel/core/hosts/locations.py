"""Where host lists live (default, personal, shared) and the recent-lists menu."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core import settings

RECENT_KEY = "recent_lists"
RECENT_LIMIT = 10


class ListKind(StrEnum):
    DEFAULT = "default"  # in the app folder, read-only, placed by an admin
    PERSONAL = "personal"  # the user's own, in Documents
    SHARED = "shared"  # any other file the user picked, e.g. on a network share


def default_list_path(folder: Path | None = None) -> Path:
    return (folder if folder is not None else settings.app_dir()) / "data" / "hosts.json"


def personal_list_path(paths: settings.Paths, documents: Path | None = None) -> Path:
    if paths.portable:
        return paths.settings_dir / "hosts.json"
    return (documents if documents is not None else documents_dir()) / "CapyPanel" / "hosts.json"


def documents_dir() -> Path:
    """The real Documents folder, which may be redirected (OneDrive, a server share)."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    folderid_documents = GUID(
        0xFDD39AD0,
        0x238F,
        0x46AF,
        (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7),
    )
    result = ctypes.c_wchar_p()
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    try:
        status = shell32.SHGetKnownFolderPath(
            ctypes.byref(folderid_documents), 0, None, ctypes.byref(result)
        )
        if status == 0 and result.value:
            return Path(result.value)
    finally:
        ole32.CoTaskMemFree(result)
    return Path.home() / "Documents"


def list_kind(path: Path, *, default: Path, personal: Path) -> ListKind:
    if same_path(path, default):
        return ListKind.DEFAULT
    if same_path(path, personal):
        return ListKind.PERSONAL
    return ListKind.SHARED


def recent_lists(prefs: dict[str, Any]) -> list[Path]:
    value = prefs.get(RECENT_KEY)
    if not isinstance(value, list):
        return []
    return [Path(p) for p in value if isinstance(p, str) and p]


def remember_list(prefs: dict[str, Any], path: Path) -> None:
    """Puts `path` first in the recent lists (the first one is reopened at start)."""
    others = [p for p in recent_lists(prefs) if not same_path(p, path)]
    prefs[RECENT_KEY] = [str(path), *map(str, others)][:RECENT_LIMIT]


def forget_list(prefs: dict[str, Any], path: Path) -> None:
    prefs[RECENT_KEY] = [str(p) for p in recent_lists(prefs) if not same_path(p, path)]


def same_path(a: Path, b: Path) -> bool:
    """Whether two paths point to the same file (Windows paths ignore case)."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
