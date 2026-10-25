"""One-time copies from older file layouts, so an update never loses a user's settings or list.
The old files are copied, never moved or deleted: going back to an older version still works."""

import ctypes
import logging
import os
import shutil
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path

from capypanel.core import files, settings
from capypanel.core.hosts import locations

log = logging.getLogger(__name__)
HOSTS = "hosts"  # the Hosts tool's id: every list before 0.20 was a host list


def _lists_into_tool_folders(paths: settings.Paths) -> list[str]:
    """From 0.20 each tool keeps its lists in a folder of its own. 0.19's lists were all host
    lists: they're copied into lists\\hosts\\ (shared and the user's own) the first time that
    folder doesn't exist, and the Hosts settings that name them follow. A folder this user
    can't create is left for someone who can."""
    hosts = paths.lists(HOSTS)
    pairs: list[tuple[Path, Path]] = []
    for old_dir, new_dir in (
        (paths.lists_dir, hosts.shared_dir),
        (paths.user_lists_dir, hosts.user_dir),
    ):
        old_lists = sorted(old_dir.glob("*.json")) if old_dir.is_dir() else []
        if new_dir.exists() or not old_lists:
            continue
        try:
            if new_dir == hosts.shared_dir:
                files.make_shared_folder(new_dir)  # everyone reads it, only its maker changes it
            else:
                new_dir.mkdir(parents=True)
            for old in old_lists:
                shutil.copy2(old, new_dir / old.name)
                pairs.append((old, new_dir / old.name))
        except OSError as e:
            log.warning("Couldn't copy the lists in %s to %s: %s", old_dir, new_dir, e)
    if pairs and paths.settings_file.exists():
        prefs = settings.load_settings(paths.settings_file)
        section = settings.tool_prefs(prefs, HOSTS, inherit=True)  # 0.19's keys stay as they were
        for old, new in pairs:
            _repoint(section, old, new)
        settings.save_settings(paths.settings_file, prefs)
    return [f"{old} -> {new}" for old, new in pairs]


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
    copied = _lists_into_tool_folders(paths)
    copied += _lists_into_folders(paths)
    old_settings, old_list = old_files(paths, env, documents)
    hosts = paths.lists(HOSTS)
    moves = [(old_settings, paths.settings_file)]
    if not paths.portable:  # there, the old place is the default list's before 0.19
        moves.append((old_list, hosts.personal))
    for old, new in moves:
        if old.is_file() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
            copied.append(f"{old} -> {new}")
    if copied and paths.settings_file.exists():
        # Recent lists and the start choice may name the old personal list: point them here.
        prefs = settings.load_settings(paths.settings_file)
        recent = [
            hosts.personal if locations.same_path(p, old_list) else p
            for p in locations.recent_lists(prefs)
        ]
        prefs[locations.RECENT_KEY] = [str(p) for p in recent]
        start = prefs.get(locations.START_KEY)
        if isinstance(start, str) and locations.same_path(Path(start), old_list):
            prefs[locations.START_KEY] = locations.START_PERSONAL
        settings.save_settings(paths.settings_file, prefs)
    return copied


def _lists_into_folders(paths: settings.Paths) -> list[str]:
    """Before 0.19 the default and personal lists were hosts.json files beside the lists
    folders; they're copied in once, straight into Hosts' folders, and the settings that name
    them follow. Where 0.19 already copied one (lists\\default.json), it's left alone."""
    hosts = paths.lists(HOSTS)
    pairs = [
        (paths.root / "hosts.json", hosts.default, paths.lists_dir / "default.json"),
        (paths.user_dir / "hosts.json", hosts.personal, paths.user_lists_dir / "personal.json"),
    ]
    copied = []
    for old, new, in_0_19 in pairs:
        if old.is_file() and not new.exists() and not in_0_19.exists():
            if new == hosts.default and not new.parent.exists():
                files.make_shared_folder(new.parent)  # everyone reads it, only admins change it
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
            copied.append(f"{old} -> {new}")
    if copied and paths.settings_file.exists():
        prefs = settings.load_settings(paths.settings_file)
        for old, new, _in_0_19 in pairs:
            _repoint(prefs, old, new)
        settings.save_settings(paths.settings_file, prefs)
    return copied


def _repoint(prefs: dict[str, object], old: Path, new: Path) -> None:
    """Recent, added and hidden lists, the start choice and what each list shows first: from
    `old` to `new`."""
    for key in (locations.RECENT_KEY, locations.LISTS_KEY, locations.HIDDEN_KEY):
        value = prefs.get(key)
        if isinstance(value, list):
            prefs[key] = [
                str(new) if isinstance(p, str) and locations.same_path(Path(p), old) else p
                for p in value
            ]
    start = prefs.get(locations.START_KEY)
    if isinstance(start, str) and start and locations.same_path(Path(start), old):
        prefs[locations.START_KEY] = str(new)
    views = prefs.get(locations.VIEWS_KEY)
    if isinstance(views, dict):
        prefs[locations.VIEWS_KEY] = {
            (os.path.normcase(os.path.abspath(new)) if locations.same_path(Path(k), old) else k): v
            for k, v in views.items()
        }


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
