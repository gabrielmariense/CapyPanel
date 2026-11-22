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
    PROFILE = "profile"
    ENTRY = "entry"  # a registry entry whose folder is gone
    FOLDER = "folder"  # a folder in Users that no registry entry names
    BACKUP = "backup"


class State(StrEnum):
    PROTECTED = "protected"  # one of Windows' own, or the built-in Administrator's
    OUTSIDE = "outside"
    IN_USE = "in-use"
    REVIEW = "review"  # a .bak entry: fixed by hand, never deleted here
    READY = "ready"


@dataclass(frozen=True)
class Profile:
    sid: str
    key: str
    user: str
    known: bool
    path: str
    kind: Kind
    state: State
    last_used: datetime | None = None
    modified: datetime | None = None

    @property
    def ident(self) -> str:
        return self.key or self.sid or self.path.casefold()

    @property
    def ready(self) -> bool:
        return self.state is State.READY


@dataclass(frozen=True)
class Scan:
    host: str
    root: str
    profiles: tuple[Profile, ...]


class Outcome(StrEnum):
    DELETED = "deleted"
    SKIPPED = "skipped"
    FAILED = "failed"


class Why(StrEnum):
    NOT_READY = "not-ready"
    IN_USE = "in-use"
    GONE = "gone"
    CHANGED = "changed"
    PROTECTED = "protected"
    LEFT = "left"
    ERROR = "error"


@dataclass(frozen=True)
class Deleted:
    profile: Profile
    outcome: Outcome
    why: Why | None = None
    detail: str = ""


Opened = Callable[[str], str]
NameOf = Callable[[str], str]

# People: domain and local accounts (S-1-5-21-…) and Entra ID ones (S-1-12-1-…).
_PERSON = re.compile(r"S-1-(?:5-21|12-1)(?:-\d+)+")
_KEY = re.compile(r"S-1-(?:5-21|12-1)(?:-\d+)+(?:\.bak)?", re.IGNORECASE)
_BUILTIN_ADMIN = "-500"  # how the built-in Administrator's SID ends, whatever its name
_WINDOWS_OWN = (
    "Public", "Default", "All Users", "Default User", "defaultuser0", "Administrator",
    "Administrador", "WDAGUtilityAccount",
)  # fmt: skip
_SERVICE_PROFILES = (
    r"system32\config\systemprofile", r"ServiceProfiles\LocalService",
    r"ServiceProfiles\NetworkService",
)  # fmt: skip


def share_path(host: str, path: str) -> str:
    r"""Through C$ in Windows' long form (\\?\UNC\…), so paths deep in AppData work."""
    if not re.fullmatch(r"[A-Za-z]:(\\.*)?", path):
        raise ValueError(f"not a path on a drive: {path!r}")
    return rf"\\?\UNC\{host}\{path[0]}$" + path[2:].rstrip("\\")


def confirmed(typed: str, host: str) -> bool:
    return bool(host.strip()) and typed.strip().casefold() == host.strip().casefold()


def scan(
    host: str,
    account: Account | None = None,
    *,
    opened: Opened | None = None,
    name_of: NameOf | None = None,
) -> Scan:
    from capypanel.core.remote import inventory

    check_reachable(host)
    facts = inventory.run_cim(_FACTS, host, account)
    with as_account(account):
        return _combine(
            host, facts, opened or (lambda path: share_path(host, path)),
            name_of or (lambda sid: account_of(host, sid)),
        )  # fmt: skip


def _combine(host: str, facts: Mapping[str, Any], opened: Opened, name_of: NameOf) -> Scan:
    root = str(facts.get("root") or r"C:\Users").rstrip("\\")
    try:
        os.stat(opened(root))
    except OSError as e:
        raise RemoteError(reason_of(e.winerror or 0), e.winerror or 0) from e
    own = _own_paths(facts, root)
    hives = {str(h.get("sid") or ""): h for h in _rows(facts.get("hives"))}
    listed = {str(p.get("sid") or ""): p for p in _rows(facts.get("profiles"))}
    named: set[str] = set()
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
    for sid, cim in listed.items():
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
    windows = str(facts.get("windows") or r"C:\Windows").rstrip("\\")
    paths = [f"{windows}\\{sub}" for sub in _SERVICE_PROFILES]
    paths += [f"{root}\\{name}" for name in _WINDOWS_OWN]
    if admin := str(facts.get("admin") or ""):
        paths.append(f"{root}\\{admin}")
    return frozenset(p.casefold() for p in paths)


def _inside(root: str, path: str) -> bool:
    return path.casefold().startswith(root.casefold() + "\\")


def _last_used(key: Mapping[str, Any]) -> datetime | None:
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
    """None for a time no profile can have: half-written values read as 1601 or the far future."""
    if when < _EARLIEST or when > datetime.now(UTC) + timedelta(days=2):
        return None
    return when


def _modified(seconds: float) -> datetime | None:
    try:
        return _plausible(datetime.fromtimestamp(seconds, UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _rows(value: object) -> list[Mapping[str, Any]]:
    rows = value if isinstance(value, list) else [value]
    return [row for row in rows if isinstance(row, dict)]


@dataclass(frozen=True)
class _Folder:
    modified: datetime | None
    link: bool  # a junction or another reparse point: its files live somewhere else; protected


def _look(opened: Opened, path: str) -> _Folder | None:
    """A folder that can't be read counts as a link: never taken for gone, never touched."""
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
    if not profile.path or profile.kind is Kind.ENTRY:
        return None
    opened = opened or (lambda path: share_path(scanned.host, path))
    with network_identity(account) as identity, identity():
        try:
            return folder_size(opened(profile.path), stop, progress, identity=identity)
        except OSError as e:
            raise RemoteError(reason_of(e.winerror or 0), e.winerror or 0) from e


WALKERS = 8


def folder_size(
    folder: str,
    stop: Callable[[], bool] = lambda: False,
    progress: Callable[[int], None] | None = None,
    *,
    walkers: int = WALKERS,
    identity: Callable[[], AbstractContextManager[None]] = nullcontext,
) -> int | None:
    """Links aren't followed; an unreadable folder inside counts as empty."""
    total, inside = _listed(folder)
    if progress is not None:
        progress(total)
    if stop():
        return None
    if not inside:
        return total
    waiting: queue.SimpleQueue[str | None] = queue.SimpleQueue()
    for path in inside:
        waiting.put(path)
    left = len(inside)
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
                    if not stop():
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


def delete(
    scanned: Scan,
    profile: Profile,
    account: Account | None = None,
    *,
    log_file: Path | None = None,
    opened: Opened | None = None,
    name_of: NameOf | None = None,
) -> Deleted:
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
    from capypanel.core.remote import inventory

    if not _KEY.fullmatch(profile.key):
        return Deleted(profile, Outcome.SKIPPED, Why.CHANGED)
    with as_account(account):
        if _look(opened, profile.path) is not None:
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
    """Checked again first: a folder in Users that nothing names and no signed-in person owns."""
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
    """A link inside is removed as a link: what it points at is never touched."""
    failed: list[str] = []

    def drop(path: str, *, is_dir: bool) -> None:
        remove = os.rmdir if is_dir else os.unlink
        try:
            try:
                remove(path)
            except PermissionError:
                os.chmod(path, stat.S_IWRITE, follow_symlinks=False)
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
    said = answer if isinstance(answer, dict) else {}
    outcome = str(said.get("outcome") or "")
    if outcome == "deleted":
        kept = said.get("kept")
        return Deleted(profile, Outcome.DELETED, detail=f"it held {kept}" if kept else "")
    if outcome in _WHYS:
        return Deleted(profile, Outcome.SKIPPED, _WHYS[outcome])
    return Deleted(profile, Outcome.FAILED, Why.ERROR, str(said.get("text") or "").strip())


def _write_log(log_file: Path, host: str, account: Account | None, done: Deleted) -> None:
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
_DELETED_ACCOUNT, _UNKNOWN_ACCOUNT = 6, 8  # SID_NAME_USE values


def account_of(host: str, sid: str) -> str:
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


_REG = r"""
$list = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList'
$guids = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileGuid'
"""

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

# The GUID index loses the SID's line only when no twin entry (the SID beside its .bak) remains.
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
    with contextlib.suppress(RemoteError):
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
    """Checked again in the same connection that deletes, then Windows' own removal."""
    import pywintypes

    from capypanel.core.remote.wmi import message_of

    sid = values["sid"]
    if not _PERSON.fullmatch(sid):
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
        if wmi.value_names(HKLM, f"{_LIST}\\{twin}")[0]:
            for guid in wmi.subkeys(HKLM, _GUIDS):
                if wmi.string(HKLM, f"{_GUIDS}\\{guid}", "SidString") == sid:
                    _drop_key(wmi, f"{_GUIDS}\\{guid}")
        _drop_key(wmi, key)
    except (RemoteError, OSError) as e:
        return {"outcome": "failed", "text": str(e)}
    return {"outcome": "deleted", "kept": json.dumps(kept, separators=(",", ":"))}


def _drop_key(wmi: Any, key: str) -> None:
    """StdRegProv deletes only empty keys: the subkeys go first."""
    from capypanel.core.remote.wmi import HKLM

    for sub in wmi.subkeys(HKLM, key):
        _drop_key(wmi, f"{key}\\{sub}")
    code = int(wmi.reg("DeleteKey", HKLM, key).ReturnValue or 0)
    if code:
        raise OSError(code, f"Windows error {code} deleting {key}")
