"""The Windows user profiles on a PC: which are there, how big they are, and deleting the ones
nobody uses any more.

A shared PC keeps a profile (a folder in C:\\Users plus its registry entry) for everyone who ever
signed in, until the disk is full. Everything here is read from your PC: Windows' own list
(Win32_UserProfile) and the registry's ProfileList over WMI, the folders over the PC's drive
share. Nothing is installed or run on the PC.

Deleting is final: with local profiles the person's desktop and documents go too. So only a
profile that's READY can be deleted (not signed in, not one of Windows' own, inside the Users
folder), each delete checks the PC again right before it happens, and each one is written to a
log. A normal profile is removed by Windows itself (deleting its Win32_UserProfile, which takes
the folder and the registry entries together and refuses a profile in use). Two leftovers are
handled apart: a registry entry whose folder is gone, and a folder no registry entry names."""

import contextlib
import ctypes
import json
import logging
import os
import queue
import re
import stat
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, nullcontext
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core.applog import append_line
from capypanel.core.remote import inventory
from capypanel.core.remote.access import (
    Account,
    RemoteError,
    as_account,
    check_reachable,
    network_identity,
    reason_of,
)

log = logging.getLogger(__name__)

DELETE_TIMEOUT = 60 * 60  # seconds Windows gets to remove one profile: big ones take minutes


class Kind(StrEnum):
    PROFILE = "profile"  # what Windows lists as a profile
    ENTRY = "entry"  # a registry entry whose folder is gone
    FOLDER = "folder"  # a folder in Users that no registry entry names
    BACKUP = "backup"  # a ".bak" entry with its folder: a profile that failed to load


class State(StrEnum):  # in this order: the first that applies
    PROTECTED = "protected"  # one of Windows' own, or the built-in Administrator's
    OUTSIDE = "outside"  # not in the Users folder
    IN_USE = "in-use"  # signed in now
    REVIEW = "review"  # a .bak entry: fixed by hand, never deleted here
    READY = "ready"


@dataclass(frozen=True)
class Profile:
    sid: str  # "" for a folder no entry names
    key: str  # its ProfileList key: the SID, or "<SID>.bak"; "" when it has none
    user: str  # "EXAMPLE\\ana"; the folder's name when Windows can't name the account
    known: bool  # whether Windows could name the account (False: likely deleted)
    path: str  # C:\Users\ana, as the PC sees it; "" for an entry without one
    kind: Kind
    state: State
    last_used: datetime | None = None  # the last sign-in or sign-out Windows wrote down (UTC)
    modified: datetime | None = None  # the folder's own date (UTC)

    @property
    def ident(self) -> str:
        """Tells it from every other row of a scan, whatever its kind."""
        return self.key or self.sid or self.path.casefold()

    @property
    def ready(self) -> bool:
        return self.state is State.READY


@dataclass(frozen=True)
class Scan:
    host: str
    root: str  # the PC's Users folder: C:\Users
    profiles: tuple[Profile, ...]


class Outcome(StrEnum):
    DELETED = "deleted"
    SKIPPED = "skipped"  # the check right before found a reason not to
    FAILED = "failed"


class Why(StrEnum):
    NOT_READY = "not-ready"  # it wasn't READY in the scan
    IN_USE = "in-use"  # signed in since the scan
    GONE = "gone"  # no longer there
    CHANGED = "changed"  # not what the scan saw: scan again
    PROTECTED = "protected"
    LEFT = "left"  # some of its files couldn't be removed
    ERROR = "error"  # Windows refused, or the PC stopped answering


@dataclass(frozen=True)
class Deleted:
    profile: Profile
    outcome: Outcome
    why: Why | None = None
    detail: str = ""  # Windows' own words or code, when it gave any


# Maps a path as the PC sees it (C:\Users\ana) to one this PC can open.
Opened = Callable[[str], str]
# An account's name for its SID, "EXAMPLE\\ana", or "" when Windows knows none.
NameOf = Callable[[str], str]

# People: domain and local accounts (S-1-5-21-…) and Entra ID ones (S-1-12-1-…).
_PERSON = re.compile(r"S-1-(?:5-21|12-1)(?:-\d+)+")
_KEY = re.compile(r"S-1-(?:5-21|12-1)(?:-\d+)+(?:\.bak)?", re.IGNORECASE)
_BUILTIN_ADMIN = "-500"  # how the built-in Administrator's SID ends, whatever its name
# Folders Windows makes itself in Users, in the languages it names them in.
_WINDOWS_OWN = (
    "Public", "Default", "All Users", "Default User", "defaultuser0", "Administrator",
    "Administrador", "WDAGUtilityAccount",
)  # fmt: skip
_SERVICE_PROFILES = (
    r"system32\config\systemprofile", r"ServiceProfiles\LocalService",
    r"ServiceProfiles\NetworkService",
)  # fmt: skip


def share_path(host: str, path: str) -> str:
    r"""`path` on `host` (C:\Users\ana) as this PC opens it, through the drive's admin share and
    in Windows' long form, so paths deep in AppData work: \\?\UNC\host\C$\Users\ana."""
    if not re.fullmatch(r"[A-Za-z]:(\\.*)?", path):
        raise ValueError(f"not a path on a drive: {path!r}")
    return rf"\\?\UNC\{host}\{path[0]}$" + path[2:].rstrip("\\")


def confirmed(typed: str, host: str) -> bool:
    """Whether what the admin typed is the PC's name: the last step before deleting."""
    return bool(host.strip()) and typed.strip().casefold() == host.strip().casefold()


# ---- reading ----


def scan(
    host: str,
    account: Account | None = None,
    *,
    opened: Opened | None = None,
    name_of: NameOf | None = None,
) -> Scan:
    """Every user profile on `host`, and the leftovers of old ones, by name. Reads only.
    Raises RemoteError or TimeoutError."""
    from capypanel.core.remote import inventory  # its PowerShell parts load on first use

    check_reachable(host)
    facts = inventory.run_cim(_FACTS, host, account)
    with as_account(account):
        return _combine(
            host, facts, opened or (lambda path: share_path(host, path)),
            name_of or (lambda sid: account_of(host, sid)),
        )  # fmt: skip


def _combine(host: str, facts: Mapping[str, Any], opened: Opened, name_of: NameOf) -> Scan:
    """One row per profile and leftover, from what WMI said and what the folders show."""
    root = str(facts.get("root") or r"C:\Users").rstrip("\\")
    try:
        os.stat(opened(root))
    except OSError as e:  # the share, not one folder: nothing below can be told apart
        raise RemoteError(reason_of(e.winerror or 0), e.winerror or 0) from e
    own = _own_paths(facts, root)
    hives = {str(h.get("sid") or ""): h for h in _rows(facts.get("hives"))}
    listed = {str(p.get("sid") or ""): p for p in _rows(facts.get("profiles"))}
    named: set[str] = set()  # the paths a registry entry or Windows' list names, case-folded
    found: list[Profile] = []
    for key in _rows(facts.get("keys")):
        name = str(key.get("name") or "")
        if not _KEY.fullmatch(name):
            continue  # Windows' own (S-1-5-18…): never listed
        sid = name[:-4] if name.casefold().endswith(".bak") else name
        path = str(key.get("path") or "").rstrip("\\")
        folder = _look(opened, path)
        cim = listed.get(sid, {})
        kind = Kind.ENTRY if folder is None else Kind.BACKUP if name != sid else Kind.PROFILE
        protected = (
            sid.endswith(_BUILTIN_ADMIN)
            or path.casefold() in own
            or bool(cim.get("special"))
            or (folder is not None and folder.link)
        )
        state = _state(
            protected,
            bool(path) and not _inside(root, path),
            sid in hives or bool(cim.get("loaded")),
            kind,
        )
        modified = folder.modified if folder else None
        found.append(_named(name_of, sid, name, path, kind, state, _last_used(key), modified))
        named.add(path.casefold())
    for sid, cim in listed.items():  # listed by Windows with no entry of its own: rare
        if not _PERSON.fullmatch(sid) or any(p.sid == sid for p in found):
            continue
        path = str(cim.get("path") or "").rstrip("\\")
        folder = _look(opened, path)
        protected = (
            sid.endswith(_BUILTIN_ADMIN) or path.casefold() in own or bool(cim.get("special"))
        )
        state = _state(
            protected,
            bool(path) and not _inside(root, path),
            sid in hives or bool(cim.get("loaded")),
            Kind.PROFILE,
        )
        modified = folder.modified if folder else None
        found.append(_named(name_of, sid, "", path, Kind.PROFILE, state, None, modified))
        named.add(path.casefold())
    found += _leftover_folders(facts, root, own, named, opened)
    return Scan(host, root, tuple(sorted(found, key=lambda p: (p.user.casefold(), p.ident))))


def _leftover_folders(
    facts: Mapping[str, Any], root: str, own: frozenset[str], named: set[str], opened: Opened
) -> list[Profile]:
    """The folders in Users that no entry names. One whose name is a signed-in person's counts
    as in use, even with no entry: better a folder left than a person's files gone."""
    hives = _rows(facts.get("hives"))
    active_paths = {str(h.get("folder") or "").rstrip("\\").casefold() for h in hives}
    active_names = {str(h.get("user") or "").casefold() for h in hives}
    active_names.add(str(facts.get("console") or "").rpartition("\\")[2].casefold())
    found = []
    for name, folder in _children(opened(root)):
        path = f"{root}\\{name}"
        if path.casefold() in named:
            continue
        loaded = path.casefold() in active_paths or name.casefold() in active_names
        state = _state(path.casefold() in own or folder.link, False, loaded, Kind.FOLDER)
        found.append(
            Profile("", "", name, False, path, Kind.FOLDER, state, modified=folder.modified)
        )
    return found


def _named(
    name_of: NameOf,
    sid: str,
    key: str,
    path: str,
    kind: Kind,
    state: State,
    last_used: datetime | None,
    modified: datetime | None,
) -> Profile:
    account = name_of(sid)
    user = account or path.rpartition("\\")[2] or sid
    return Profile(sid, key, user, bool(account), path, kind, state, last_used, modified)


def _state(protected: bool, outside: bool, loaded: bool, kind: Kind) -> State:
    if protected:
        return State.PROTECTED
    if outside:
        return State.OUTSIDE
    if loaded:
        return State.IN_USE
    return State.REVIEW if kind is Kind.BACKUP else State.READY


def _own_paths(facts: Mapping[str, Any], root: str) -> frozenset[str]:
    """Windows' own profile folders on this PC, case-folded."""
    windows = str(facts.get("windows") or r"C:\Windows").rstrip("\\")
    paths = [f"{windows}\\{sub}" for sub in _SERVICE_PROFILES]
    paths += [f"{root}\\{name}" for name in _WINDOWS_OWN]
    if admin := str(facts.get("admin") or ""):  # the built-in Administrator, when renamed
        paths.append(f"{root}\\{admin}")
    return frozenset(p.casefold() for p in paths)


def _inside(root: str, path: str) -> bool:
    return path.casefold().startswith(root.casefold() + "\\")


def _last_used(key: Mapping[str, Any]) -> datetime | None:
    """The later of the last sign-in and sign-out, which Windows keeps in the entry."""
    times = [
        _filetime(key.get(f"{which}_high"), key.get(f"{which}_low")) for which in ("load", "unload")
    ]
    return max((t for t in times if t), default=None)


def _filetime(high: object, low: object) -> datetime | None:
    if not isinstance(high, int) or not isinstance(low, int) or not (high or low):
        return None
    ticks = (high << 32) | low  # 100 ns steps since 1601
    try:
        return _plausible(datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10))
    except OverflowError:
        return None


_EARLIEST = datetime(1980, 1, 1, tzinfo=UTC)  # before any Windows that keeps profiles


def _plausible(when: datetime) -> datetime | None:
    """`when`, or None for a time no profile can have: a half-written registry value reads as
    1601 or the far future, and Windows can't show a date before 1970 in local time."""
    if when < _EARLIEST or when > datetime.now(UTC) + timedelta(days=2):
        return None
    return when


def _modified(seconds: float) -> datetime | None:
    """A folder's last change, from its file times; None when they make no sense."""
    try:
        return _plausible(datetime.fromtimestamp(seconds, UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _rows(value: object) -> list[Mapping[str, Any]]:
    """PowerShell writes a list of one as the one itself."""
    rows = value if isinstance(value, list) else [value]
    return [row for row in rows if isinstance(row, dict)]


# ---- folders ----


@dataclass(frozen=True)
class _Folder:
    modified: datetime | None
    link: bool  # a junction or another reparse point: its files live somewhere else; protected


def _look(opened: Opened, path: str) -> _Folder | None:
    """The folder at `path` on the PC, or None when there's none. One that's there but can't be
    read counts as a link: it's never taken for gone, and never touched."""
    if not path:
        return None
    try:
        found = os.stat(opened(path), follow_symlinks=False)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return None
    except OSError:
        return _Folder(None, link=True)
    if not (stat.S_ISDIR(found.st_mode) or _is_link(found)):
        return None
    return _Folder(_modified(found.st_mtime), _is_link(found))


def _is_link(found: os.stat_result) -> bool:
    return bool(found.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _children(folder: str) -> Iterator[tuple[str, _Folder]]:
    """The folders directly inside `folder`, links among them."""
    with os.scandir(folder) as entries:
        listed = sorted(entries, key=lambda e: e.name.casefold())
    for entry in listed:
        with contextlib.suppress(OSError):
            found = entry.stat(follow_symlinks=False)
            if entry.is_dir(follow_symlinks=False) or _is_link(found):
                yield (
                    entry.name,
                    _Folder(_modified(found.st_mtime), _is_link(found)),
                )


def profile_size(
    scanned: Scan,
    profile: Profile,
    account: Account | None = None,
    *,
    stop: Callable[[], bool] = lambda: False,
    opened: Opened | None = None,
    progress: Callable[[int], None] | None = None,
) -> int | None:
    """The bytes in `profile`'s folder, read over the PC's drive share; None when `stop` said
    so first, or when it has no folder. `progress` hears the bytes counted so far, folder by
    folder (from the threads that read them). Reads only. Raises RemoteError."""
    if not profile.path or profile.kind is Kind.ENTRY:
        return None
    opened = opened or (lambda path: share_path(scanned.host, path))
    with network_identity(account) as identity, identity():
        try:
            return folder_size(opened(profile.path), stop, progress, identity=identity)
        except OSError as e:
            raise RemoteError(reason_of(e.winerror or 0), e.winerror or 0) from e


WALKERS = 8  # folders of one profile read at the same time: each is a wait on the network


def folder_size(
    folder: str,
    stop: Callable[[], bool] = lambda: False,
    progress: Callable[[int], None] | None = None,
    *,
    walkers: int = WALKERS,
    identity: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> int | None:
    """The bytes in the files under `folder`; None when `stop` said so. Links are never followed
    (AppData has several, and the count would leave the profile), and a folder inside that can't
    be read counts as empty. Raises OSError when `folder` itself can't be read.

    A profile is tens of thousands of folders, and over the network each one is a wait: read
    one after another, a profile took minutes. So `walkers` threads read folders at the same
    time, each inside `identity()` (the account that signs in applies per thread). `progress`
    hears the bytes so far after each folder, from whichever thread read it."""
    total, inside = _listed(folder)  # the folder itself, here: its error is the caller's
    if progress is not None:
        progress(total)
    if stop():
        return None
    if not inside:
        return total
    waiting: queue.SimpleQueue[str | None] = queue.SimpleQueue()
    for path in inside:
        waiting.put(path)
    left = len(inside)  # folders not read yet, the ones being read among them
    lock = threading.Lock()
    failed: list[BaseException] = []

    def release() -> None:
        for _walker in range(walkers):
            waiting.put(None)

    def walk() -> None:
        nonlocal total, left
        try:
            with identity():
                while (current := waiting.get()) is not None:
                    size, found = 0, []
                    if not stop():  # stopped: the folders waiting are let go unread
                        with contextlib.suppress(OSError):
                            size, found = _listed(current)
                    with lock:
                        total += size
                        left += len(found) - 1
                        so_far, over = total, left == 0
                    for path in found:
                        waiting.put(path)
                    if progress is not None:
                        progress(so_far)
                    if over:
                        release()
        except BaseException as e:  # noqa: BLE001 - told to the caller, on its own thread
            failed.append(e)
            release()

    threads = [
        threading.Thread(target=walk, name="folder-size", daemon=True)
        for _walker in range(max(1, walkers))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failed:
        raise failed[0]
    return None if stop() else total


def _listed(folder: str) -> tuple[int, list[str]]:
    """The bytes of the files directly in `folder`, and the folders in it that aren't links.
    One listing: Windows hands each entry's size and kind with its name."""
    size, folders = 0, []
    with os.scandir(folder) as entries:
        for entry in entries:
            with contextlib.suppress(OSError):
                found = entry.stat(follow_symlinks=False)
                if _is_link(found):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folders.append(entry.path)
                else:
                    size += found.st_size
    return size, folders


# ---- deleting ----


def delete(
    scanned: Scan,
    profile: Profile,
    account: Account | None = None,
    *,
    log_file: Path | None = None,
    opened: Opened | None = None,
    name_of: NameOf | None = None,
) -> Deleted:
    """Deletes one profile or leftover of `scanned`'s PC, after checking it again there, and
    writes what happened to `log_file`. Never raises for what the PC answers: a refusal or a
    failure is the outcome."""
    host = scanned.host
    opened = opened or (lambda path: share_path(host, path))
    if not profile.ready:
        done = Deleted(profile, Outcome.SKIPPED, Why.NOT_READY)
    else:
        try:
            check_reachable(host)
            if profile.kind is Kind.FOLDER:
                names = name_of or (lambda sid: account_of(host, sid))
                done = _delete_folder(scanned, profile, account, opened, names)
            elif profile.kind is Kind.ENTRY and profile.key:
                done = _delete_entry(host, profile, account, opened)
            else:
                done = _delete_profile(host, profile, account)
        except (RemoteError, TimeoutError, OSError) as e:
            done = Deleted(profile, Outcome.FAILED, Why.ERROR, str(e))
    if log_file is not None:
        _write_log(log_file, host, account, done)
    return done


def _delete_profile(host: str, profile: Profile, account: Account | None) -> Deleted:
    """Windows' own removal: the folder and the registry entries together."""
    from capypanel.core.remote import inventory

    if not _PERSON.fullmatch(profile.sid):  # it goes into a WMI query
        return Deleted(profile, Outcome.SKIPPED, Why.CHANGED)
    answer = inventory.run_cim(
        _DELETE_PROFILE,
        host,
        account,
        values={"sid": profile.sid, "path": profile.path, "wait": str(DELETE_TIMEOUT)},
        timeout=DELETE_TIMEOUT + 60,
    )
    return _answered(profile, answer)


def _delete_entry(host: str, profile: Profile, account: Account | None, opened: Opened) -> Deleted:
    """A registry entry whose folder is gone: the entry goes, and the PC's index of profile
    GUIDs with it. What the entry held is kept in the log."""
    from capypanel.core.remote import inventory

    if not _KEY.fullmatch(profile.key):
        return Deleted(profile, Outcome.SKIPPED, Why.CHANGED)
    with as_account(account):
        if _look(opened, profile.path) is not None:  # its folder is back: a profile again
            return Deleted(profile, Outcome.SKIPPED, Why.CHANGED)
    answer = inventory.run_cim(
        _DELETE_ENTRY,
        host,
        account,
        values={"key": profile.key, "sid": profile.sid, "path": profile.path},
    )
    return _answered(profile, answer)


def _delete_folder(
    scanned: Scan, profile: Profile, account: Account | None, opened: Opened, name_of: NameOf
) -> Deleted:
    """A folder no entry names. Scanned again first: it must still be a real folder directly in
    Users that nothing names and nobody signed in owns."""
    from capypanel.core.remote import inventory

    host, root = scanned.host, scanned.root
    if profile.path.rpartition("\\")[0].casefold() != root.casefold():
        return Deleted(profile, Outcome.SKIPPED, Why.CHANGED)
    facts = inventory.run_cim(_FACTS, host, account)
    with as_account(account):
        now = {p.ident: p for p in _combine(host, facts, opened, name_of).profiles}
        same = now.get(profile.ident)
        if same is None:
            gone = _look(opened, profile.path) is None
            return Deleted(profile, Outcome.SKIPPED, Why.GONE if gone else Why.CHANGED)
        if same.kind is not Kind.FOLDER or same.state is not State.READY:
            why = {State.IN_USE: Why.IN_USE, State.PROTECTED: Why.PROTECTED}
            return Deleted(profile, Outcome.SKIPPED, why.get(same.state, Why.CHANGED))
        left = remove_tree(opened(profile.path))
    if left:
        return Deleted(profile, Outcome.FAILED, Why.LEFT, left[0])
    return Deleted(profile, Outcome.DELETED)


def remove_tree(folder: str) -> list[str]:
    """Deletes `folder` and everything in it. A link inside is removed as a link: what it points
    at is never touched. Answers with what couldn't be removed, as "path: why"."""
    failed: list[str] = []

    def drop(path: str, *, is_dir: bool) -> None:
        remove = os.rmdir if is_dir else os.unlink
        try:
            try:
                remove(path)
            except PermissionError:  # a read-only file refuses to go; the link itself, never
                os.chmod(path, stat.S_IWRITE, follow_symlinks=False)  # what it points at
                remove(path)
        except OSError as e:
            failed.append(f"{path}: {e.strerror or e}")

    def empty(path: str) -> None:
        try:
            with os.scandir(path) as entries:
                listed = list(entries)
        except OSError as e:
            failed.append(f"{path}: {e.strerror or e}")
            return
        for entry in listed:
            try:
                found = entry.stat(follow_symlinks=False)
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as e:
                failed.append(f"{entry.path}: {e.strerror or e}")
                continue
            if is_dir and not _is_link(found):
                empty(entry.path)
            # A junction is a folder to Windows: removed with rmdir, its target left alone.
            drop(entry.path, is_dir=is_dir or (_is_link(found) and _directory(found)))

    try:
        if _is_link(os.stat(folder, follow_symlinks=False)):
            return [f"{folder}: a link"]
    except OSError as e:
        return [f"{folder}: {e.strerror or e}"]
    empty(folder)
    drop(folder, is_dir=True)
    return failed


def _directory(found: os.stat_result) -> bool:
    return bool(found.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY)


_WHYS = {
    "gone": Why.GONE,
    "in-use": Why.IN_USE,
    "changed": Why.CHANGED,
    "protected": Why.PROTECTED,
}


def _answered(profile: Profile, answer: object) -> Deleted:
    """What a delete script said."""
    said = answer if isinstance(answer, dict) else {}
    outcome = str(said.get("outcome") or "")
    if outcome == "deleted":
        kept = said.get("kept")
        return Deleted(profile, Outcome.DELETED, detail=f"it held {kept}" if kept else "")
    if outcome in _WHYS:
        return Deleted(profile, Outcome.SKIPPED, _WHYS[outcome])
    return Deleted(profile, Outcome.FAILED, Why.ERROR, str(said.get("text") or "").strip())


def _write_log(log_file: Path, host: str, account: Account | None, done: Deleted) -> None:
    """One line per delete asked for: when, the PC, who asked, what, and how it ended."""
    p = done.profile
    who = account.user if account is not None else "(your Windows account)"
    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ended = done.outcome.value + (f": {done.why.value}" if done.why else "")
    if done.detail:
        ended += f" ({done.detail})"
    line = "\t".join((when, host, who, p.user, p.sid or "-", p.path or "-", p.kind.value, ended))
    try:
        append_line(log_file, line.replace("\n", " ").replace("\r", " "))
    except OSError as e:
        log.warning("Couldn't write the user profiles log %s: %s", log_file, e)


# ---- account names ----

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
_advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
_advapi32.LookupAccountSidW.restype = wintypes.BOOL
_advapi32.LookupAccountSidW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
]  # fmt: skip
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_DELETED_ACCOUNT, _UNKNOWN_ACCOUNT = 6, 8  # what kind of name came back


def account_of(host: str, sid: str) -> str:
    """The account `host` knows `sid` by, "EXAMPLE\\ana", or "" when it knows none: the account
    was deleted, or its domain can't be asked. `host` answers, so its own local accounts get
    their names too."""
    binary = ctypes.c_void_p()
    if not _advapi32.ConvertStringSidToSidW(sid, ctypes.byref(binary)):
        return ""
    try:
        name, domain = ctypes.create_unicode_buffer(257), ctypes.create_unicode_buffer(257)
        name_size, domain_size = wintypes.DWORD(257), wintypes.DWORD(257)
        kind = wintypes.DWORD()
        if not _advapi32.LookupAccountSidW(
            host or None, binary, name, ctypes.byref(name_size), domain,
            ctypes.byref(domain_size),
            ctypes.byref(kind),
        ):  # fmt: skip
            return ""
        if kind.value in (_DELETED_ACCOUNT, _UNKNOWN_ACCOUNT) or not name.value:
            return ""
        return f"{domain.value}\\{name.value}" if domain.value else name.value
    finally:
        _kernel32.LocalFree(binary)


# ---- the WMI scripts (they run on your PC, with a session to the other) ----

_REG = r"""
$list = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
$guids = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileGuid'
"""

# ProfileList has an entry per profile, with its folder and when it was last loaded and unloaded;
# HKEY_USERS a hive per person signed in, whose Volatile Environment names them and their folder.
_FACTS = (
    _REG
    + r"""
try {
  $os = Get-CimInstance -CimSession $session Win32_OperatingSystem
  $system = Get-CimInstance -CimSession $session Win32_ComputerSystem
  $keys = New-Object System.Collections.ArrayList
  foreach ($name in @((Reg EnumKey $list).sNames)) {
    if ($name -notmatch '^S-1-(5-21|12-1)-') { continue }
    $key = "$list\$name"
    [void]$keys.Add(@{
      name = $name
      path = (Reg GetExpandedStringValue $key ProfileImagePath).sValue
      load_high = (Reg GetDWORDValue $key LocalProfileLoadTimeHigh).uValue
      load_low = (Reg GetDWORDValue $key LocalProfileLoadTimeLow).uValue
      unload_high = (Reg GetDWORDValue $key LocalProfileUnloadTimeHigh).uValue
      unload_low = (Reg GetDWORDValue $key LocalProfileUnloadTimeLow).uValue
    })
  }
  $profiles = New-Object System.Collections.ArrayList
  foreach ($p in @(Get-CimInstance -CimSession $session Win32_UserProfile)) {
    [void]$profiles.Add(@{sid = $p.SID; path = $p.LocalPath; loaded = [bool]$p.Loaded
                          special = [bool]$p.Special})
  }
  $hives = New-Object System.Collections.ArrayList
  foreach ($sid in @((UReg EnumKey '').sNames)) {
    if ($sid -notmatch '^S-1-(5-21|12-1)-[\d-]+$') { continue }
    [void]$hives.Add(@{
      sid = $sid
      user = (UReg GetStringValue "$sid\Volatile Environment" USERNAME).sValue
      folder = (UReg GetStringValue "$sid\Volatile Environment" USERPROFILE).sValue
    })
  }
  $admin = ''
  try {
    $admin = [string](Get-CimInstance -CimSession $session Win32_UserAccount `
        -Filter 'LocalAccount=True' | Where-Object { $_.SID -match '-500$' } |
      Select-Object -First 1).Name
  } catch { }
  Send @{keys = @($keys); profiles = @($profiles); hives = @($hives); admin = $admin
         console = [string]$system.UserName; windows = [string]$os.WindowsDirectory
         root = (Reg GetExpandedStringValue $list ProfilesDirectory).sValue}
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""
)

# Checked again in the same session that deletes: still there, still the same folder, not
# Windows' own, nobody signed in to it.
_DELETE_PROFILE = (
    _REG
    + r"""
try {
  $p = Get-CimInstance -CimSession $session Win32_UserProfile -Filter "SID='$($in.sid)'"
  if (-not $p) { Send @{outcome = 'gone'} }
  elseif ($p.Special) { Send @{outcome = 'protected'} }
  elseif ($p.Loaded -or (@((UReg EnumKey '').sNames) -contains $in.sid)) {
    Send @{outcome = 'in-use'}
  }
  elseif (([string]$p.LocalPath).TrimEnd('\') -ne $in.path) { Send @{outcome = 'changed'} }
  else {
    try {
      Remove-CimInstance -CimSession $session -InputObject $p -OperationTimeoutSec ([int]$in.wait)
      Send @{outcome = 'deleted'}
    } catch { Send @{outcome = 'failed'; text = $_.Exception.Message} }
  }
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""
)

# The entry's values are read first and sent back, for the log. The PC's GUID index loses the
# SID's line only when no twin entry (the SID beside its .bak) still stands for that person.
_DELETE_ENTRY = (
    _REG
    + r"""
function DropKey($key) {
  foreach ($sub in @((Reg EnumKey $key).sNames)) { if ($sub) { DropKey "$key\$sub" } }
  $done = Reg DeleteKey $key
  if ($done.ReturnValue -ne 0) { throw "Windows error $($done.ReturnValue) deleting $key" }
}
try {
  $key = "$list\$($in.key)"
  $values = Reg EnumValues $key
  if ($values.ReturnValue -ne 0) { Send @{outcome = 'gone'} }
  elseif (@((UReg EnumKey '').sNames) -contains $in.sid) { Send @{outcome = 'in-use'} }
  elseif (([string](Reg GetExpandedStringValue $key ProfileImagePath).sValue).TrimEnd('\') -ne
          $in.path) { Send @{outcome = 'changed'} }
  else {
    try {
      $kept = @{}
      $names = @($values.sNames); $types = @($values.Types)
      for ($i = 0; $i -lt $names.Count; $i++) {
        $n = $names[$i]; $t = $types[$i]
        if ($t -eq 1 -or $t -eq 2) { $kept[$n] = (Reg GetStringValue $key $n).sValue }
        elseif ($t -eq 4) { $kept[$n] = (Reg GetDWORDValue $key $n).uValue }
        elseif ($t -eq 11) { $kept[$n] = (Reg GetQWORDValue $key $n).uValue }
        elseif ($t -eq 7) { $kept[$n] = @((Reg GetMultiStringValue $key $n).sValue) }
        elseif ($t -eq 3) {
          $kept[$n] = [BitConverter]::ToString([byte[]]@((Reg GetBinaryValue $key $n).uValue))
        }
      }
      $twin = if ($in.key -eq $in.sid) { "$($in.sid).bak" } else { $in.sid }
      if ((Reg EnumValues "$list\$twin").ReturnValue -ne 0) {
        foreach ($g in @((Reg EnumKey $guids).sNames)) {
          if ($g -and (Reg GetStringValue "$guids\$g" SidString).sValue -eq $in.sid) {
            DropKey "$guids\$g"
          }
        }
      }
      DropKey $key
      Send @{outcome = 'deleted'; kept = (ConvertTo-Json -InputObject $kept -Compress)}
    } catch { Send @{outcome = 'failed'; text = $_.Exception.Message} }
  }
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""
)


# ---- the same reads and deletes over WMI directly ----

_LIST = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
_GUIDS = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileGuid"
_LISTED = re.compile(r"S-1-(5-21|12-1)-.*", re.IGNORECASE)  # ProfileList's people
_SIGNED_IN = re.compile(r"S-1-(5-21|12-1)-[\d-]+", re.IGNORECASE)  # HKEY_USERS' people


def _signed_in(wmi: Any) -> list[str]:
    from capypanel.core.remote.wmi import HKU

    return wmi.subkeys(HKU, "")


@inventory.reads(_FACTS)
def _facts_direct(wmi: Any, _values: Mapping[str, str]) -> dict[str, Any]:
    from capypanel.core.remote.wmi import HKLM, HKU

    os_ = wmi.first("SELECT WindowsDirectory FROM Win32_OperatingSystem")
    system = wmi.first("SELECT UserName FROM Win32_ComputerSystem")
    keys = []
    for name in wmi.subkeys(HKLM, _LIST):
        if not _LISTED.match(name):
            continue
        key = f"{_LIST}\\{name}"
        keys.append({
            "name": name,
            "path": wmi.expanded(HKLM, key, "ProfileImagePath"),
            "load_high": wmi.dword(HKLM, key, "LocalProfileLoadTimeHigh"),
            "load_low": wmi.dword(HKLM, key, "LocalProfileLoadTimeLow"),
            "unload_high": wmi.dword(HKLM, key, "LocalProfileUnloadTimeHigh"),
            "unload_low": wmi.dword(HKLM, key, "LocalProfileUnloadTimeLow"),
        })  # fmt: skip
    profiles = [
        {"sid": p.SID, "path": p.LocalPath, "loaded": bool(p.Loaded), "special": bool(p.Special)}
        for p in wmi.rows("SELECT SID, LocalPath, Loaded, Special FROM Win32_UserProfile")
    ]
    hives = [
        {"sid": sid,
         "user": wmi.string(HKU, f"{sid}\\Volatile Environment", "USERNAME"),
         "folder": wmi.string(HKU, f"{sid}\\Volatile Environment", "USERPROFILE")}
        for sid in _signed_in(wmi)
        if _SIGNED_IN.fullmatch(sid)
    ]  # fmt: skip
    admin = ""
    with contextlib.suppress(RemoteError):  # a renamed built-in Administrator; often unreadable
        for found in wmi.rows("SELECT Name, SID FROM Win32_UserAccount WHERE LocalAccount=True"):
            if str(found.SID or "").endswith("-500"):
                admin = str(found.Name or "")
                break
    return {
        "keys": keys, "profiles": profiles, "hives": hives, "admin": admin,
        "console": str(system.UserName or ""), "windows": str(os_.WindowsDirectory or ""),
        "root": wmi.expanded(HKLM, _LIST, "ProfilesDirectory"),
    }  # fmt: skip


@inventory.reads(_DELETE_PROFILE)
def _delete_profile_direct(wmi: Any, values: Mapping[str, str]) -> dict[str, Any]:
    """Checked again in the same connection that deletes, then Windows' own removal: the
    folder and the registry entries together, done by WMI on that PC."""
    import pywintypes

    from capypanel.core.remote.wmi import message_of

    sid = values["sid"]
    if not _PERSON.fullmatch(sid):  # it goes into the query
        return {"outcome": "changed"}
    found = wmi.first(f"SELECT * FROM Win32_UserProfile WHERE SID='{sid}'")
    if found is None:
        return {"outcome": "gone"}
    if found.Special:
        return {"outcome": "protected"}
    if found.Loaded or sid in _signed_in(wmi):
        return {"outcome": "in-use"}
    if str(found.LocalPath or "").rstrip("\\") != values["path"]:
        return {"outcome": "changed"}
    try:
        found.Delete_()
    except pywintypes.com_error as e:
        return {"outcome": "failed", "text": message_of(e)}
    return {"outcome": "deleted"}


_STRINGS, _BINARY, _DWORD, _MULTI, _QWORD = (1, 2), 3, 4, 7, 11  # registry value types


@inventory.reads(_DELETE_ENTRY)
def _delete_entry_direct(wmi: Any, values: Mapping[str, str]) -> dict[str, Any]:
    """The entry's values are read first and sent back, for the log. The PC's GUID index loses
    the SID's line only when no twin entry (the SID beside its .bak) still stands for that
    person."""
    from capypanel.core.remote.wmi import HKLM

    key, sid = f"{_LIST}\\{values['key']}", values["sid"]
    answer, names, types = wmi.value_names(HKLM, key)
    if answer:
        return {"outcome": "gone"}
    if sid in _signed_in(wmi):
        return {"outcome": "in-use"}
    if str(wmi.expanded(HKLM, key, "ProfileImagePath") or "").rstrip("\\") != values["path"]:
        return {"outcome": "changed"}
    try:
        kept: dict[str, Any] = {}
        for name, kind in zip(names, types, strict=False):
            if kind in _STRINGS:
                kept[name] = wmi.string(HKLM, key, name)
            elif kind == _DWORD:
                kept[name] = wmi.dword(HKLM, key, name)
            elif kind == _QWORD:
                value = wmi.reg("GetQWORDValue", HKLM, key, name).uValue
                kept[name] = None if value is None else int(value)
            elif kind == _MULTI:
                kept[name] = list(wmi.reg("GetMultiStringValue", HKLM, key, name).sValue or ())
            elif kind == _BINARY:
                data = wmi.reg("GetBinaryValue", HKLM, key, name).uValue or ()
                kept[name] = "-".join(f"{int(b):02X}" for b in data)
        twin = f"{sid}.bak" if values["key"] == sid else sid
        if wmi.value_names(HKLM, f"{_LIST}\\{twin}")[0]:  # no twin left: the GUID line goes
            for guid in wmi.subkeys(HKLM, _GUIDS):
                if wmi.string(HKLM, f"{_GUIDS}\\{guid}", "SidString") == sid:
                    _drop_key(wmi, f"{_GUIDS}\\{guid}")
        _drop_key(wmi, key)
    except (RemoteError, OSError) as e:
        return {"outcome": "failed", "text": str(e)}
    return {"outcome": "deleted", "kept": json.dumps(kept, separators=(",", ":"))}


def _drop_key(wmi: Any, key: str) -> None:
    """A registry key and everything under it: StdRegProv deletes only empty keys."""
    from capypanel.core.remote.wmi import HKLM

    for sub in wmi.subkeys(HKLM, key):
        _drop_key(wmi, f"{key}\\{sub}")
    code = int(wmi.reg("DeleteKey", HKLM, key).ReturnValue or 0)
    if code:
        raise OSError(code, f"Windows error {code} deleting {key}")
