"""One-time copies from older file layouts, so an update never loses a user's settings or list.
The old files are copied, never moved or deleted: going back to an older version still works."""

import ctypes
import os
import shutil
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path

from capypanel.core import settings
from capypanel.core.hosts import locations


def old_files(
    paths: settings.Paths, env: Mapping[str, str] | None = None, documents: Path | None = None
) -> tuple[Path, Path]:
    """Where 0.1 development builds kept the settings file and the personal list."""
    if paths.portable:
        return paths.root / "settings.json", paths.root / "hosts.json"
    env = os.environ if env is None else env
    documents = documents if documents is not None else documents_dir()
    return (
        Path(env["APPDATA"]) / settings.APP_ID / "settings.json",
        documents / "CapyPanel" / "hosts.json",
    )


def migrate(
    paths: settings.Paths, env: Mapping[str, str] | None = None, documents: Path | None = None
) -> list[str]:
    """Copies old files the new folder doesn't have yet; returns what was copied, for the log."""
    old_settings, old_list = old_files(paths, env, documents)
    copied = []
    for old, new in ((old_settings, paths.settings_file), (old_list, paths.personal_list)):
        if old.is_file() and not new.exists():
            shutil.copy2(old, new)
            copied.append(f"{old} -> {new}")
    if copied and paths.settings_file.exists():
        # Recent lists and the start choice may name the old personal list: point them here.
        prefs = settings.load_settings(paths.settings_file)
        recent = [
            paths.personal_list if locations.same_path(p, old_list) else p
            for p in locations.recent_lists(prefs)
        ]
        prefs[locations.RECENT_KEY] = [str(p) for p in recent]
        start = prefs.get(locations.START_KEY)
        if isinstance(start, str) and locations.same_path(Path(start), old_list):
            prefs[locations.START_KEY] = locations.START_PERSONAL
        settings.save_settings(paths.settings_file, prefs)
    return copied


def documents_dir() -> Path:
    """The real Documents folder, which may be redirected (OneDrive, a server share)."""

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
