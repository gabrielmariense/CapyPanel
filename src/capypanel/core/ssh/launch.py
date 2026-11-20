"""Connecting with Windows' own ssh.exe, in a tab or a window of its own (holder.py): only the
address, port and login name reach it, checked first, so no password passes through CapyPanel."""

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes as wt
from dataclasses import dataclass
from pathlib import Path

from capypanel.core import i18n
from capypanel.core.hosts.model import MAX_ADDRESS
from capypanel.core.ssh import holder
from capypanel.core.ssh.host import DEFAULT_PORT, SshInfo, is_login, is_port
from capypanel.core.updates import NO_SPLASH

log = logging.getLogger(__name__)
# What Windows' own ssh.exe 9.5 refuses in a host name on its command line (OpenSSH 9.6's fix
# for CVE-2023-51385), and so CapyPanel too, whichever ssh.exe the PC has.
REFUSED_IN_ADDRESS = frozenset("\"$&'(),;<>\\`{|}")


class SshMissing(Exception):
    """Windows' SSH client isn't installed: it's an optional feature, "OpenSSH Client"."""


def ssh_exe() -> Path | None:
    """Windows' own ssh.exe by its full path, or None when it isn't installed. Never looked up
    through PATH, where another ssh.exe could stand in for it."""
    root = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows")
    path = root / "System32" / "OpenSSH" / "ssh.exe"
    return path if path.is_file() else None


def is_destination(text: str) -> bool:
    """An address or a computer name ssh.exe can be given: no spaces or control characters, no
    leading "-", which ssh.exe would read as an option, and none of REFUSED_IN_ADDRESS."""
    return (
        0 < len(text) <= MAX_ADDRESS
        and not text.startswith("-")
        and all(c.isprintable() and not c.isspace() and c not in REFUSED_IN_ADDRESS for c in text)
    )


def command_line(exe: Path, destination: str, info: SshInfo) -> list[str]:
    """ssh.exe's arguments: the port unless 22, the name unless none (its config decides), "--",
    then the address. Raises ValueError for an address, port or name ssh.exe would misread."""
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


def tab_command(destination: str, info: SshInfo) -> list[str]:
    """ssh.exe's command line for a connection in a tab, which runs it on a pseudo console.
    Raises SshMissing or ValueError, as connect does."""
    exe = ssh_exe()
    if exe is None:
        raise SshMissing
    argv = command_line(exe, destination, info)
    log.info("Starting ssh.exe %s in a tab", subprocess.list2cmdline(argv[1:]))  # no secret
    return argv


def connect(destination: str, info: SshInfo, name: str = "") -> subprocess.Popen[bytes]:
    """ssh.exe in a window of its own, the holder's; `name` is the host as its words say it. Returns
    once the holder started (it outlives CapyPanel). Raises SshMissing, ValueError or OSError."""
    exe = ssh_exe()
    if exe is None:
        raise SshMissing
    argv = command_line(exe, destination, info)
    log.info("Starting ssh.exe %s", subprocess.list2cmdline(argv[1:]))  # no secret in it
    return subprocess.Popen(  # noqa: S603 -- CapyPanel's own exe; ssh.exe's arguments checked
        [*own_start(), *holder.args_for(argv, name or destination, i18n.language())],
        # No console from CapyPanel: typing goes to ssh.exe in the holder's own. No new process
        # group either: it would start ignoring Ctrl+C.
        creationflags=subprocess.DETACHED_PROCESS,
        close_fds=True,
        env={**os.environ, NO_SPLASH: "1"},  # the built exe's launcher shows no splash
    )


def own_start() -> list[str]:
    """How CapyPanel starts itself: its exe when built, `python -m capypanel` from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "capypanel"]


def open_windows() -> int:
    """How many separate windows this copy has open (its exe in this Windows session, other than
    this process): they hold its files, which an update can't replace. 0 from source."""
    if not getattr(sys, "frozen", False):
        return 0
    exe = Path(sys.executable)
    me = os.getpid()
    session = _session(me)
    return sum(
        1
        for running in _running(exe.name)
        if running.pid != me and running.session == session and _same_file(running.path, exe)
    )


@dataclass(frozen=True)
class Running:
    pid: int
    path: str  # its exe's full path; "" when Windows won't say
    session: int | None


def _same_file(path: str, exe: Path) -> bool:
    try:
        return bool(path) and os.path.samefile(path, exe)
    except OSError:
        return False


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_SNAPPROCESS = 0x2
_QUERY_LIMITED_INFORMATION = 0x1000
_INVALID_HANDLE = wt.HANDLE(-1).value


class _ProcessEntry(ctypes.Structure):
    _fields_ = (
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * 260),
    )


_k32.CreateToolhelp32Snapshot.argtypes = (wt.DWORD, wt.DWORD)
_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_k32.Process32FirstW.argtypes = (wt.HANDLE, ctypes.POINTER(_ProcessEntry))
_k32.Process32FirstW.restype = wt.BOOL
_k32.Process32NextW.argtypes = (wt.HANDLE, ctypes.POINTER(_ProcessEntry))
_k32.Process32NextW.restype = wt.BOOL
_k32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
_k32.OpenProcess.restype = wt.HANDLE
_k32.QueryFullProcessImageNameW.argtypes = (
    wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
)  # fmt: skip
_k32.QueryFullProcessImageNameW.restype = wt.BOOL
_k32.ProcessIdToSessionId.argtypes = (wt.DWORD, ctypes.POINTER(wt.DWORD))
_k32.ProcessIdToSessionId.restype = wt.BOOL
_k32.CloseHandle.argtypes = (wt.HANDLE,)
_k32.CloseHandle.restype = wt.BOOL


def _running(exe_name: str) -> list[Running]:
    """Every process whose exe has this file name, with its path and Windows session."""
    snapshot = _k32.CreateToolhelp32Snapshot(_SNAPPROCESS, 0)
    if snapshot in (None, _INVALID_HANDLE):
        return []
    found = []
    try:
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        more = _k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.casefold() == exe_name.casefold():
                pid = int(entry.th32ProcessID)
                found.append(Running(pid, _image_path(pid), _session(pid)))
            more = _k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snapshot)
    return found


def _image_path(pid: int) -> str:
    process = _k32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return ""
    try:
        size = wt.DWORD(32_768)
        path = ctypes.create_unicode_buffer(size.value)
        if not _k32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(size)):
            return ""
        return path.value
    finally:
        _k32.CloseHandle(process)


def _session(pid: int) -> int | None:
    session = wt.DWORD()
    if not _k32.ProcessIdToSessionId(pid, ctypes.byref(session)):
        return None
    return session.value
