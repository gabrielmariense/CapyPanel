"""Who is logged on to a computer: the Windows session API (WTS) over its own RPC channel,
called from here. Nothing is installed or run on the target, and it reads typed fields, so it
works whatever the target's display language.

Another account (an admin, when the user's daily one isn't) goes through a "new credentials"
logon, like `runas /netonly`: only the network identity of this thread changes, for the call.
Windows doesn't check that password here; each target does, so callers must stop at the first
rejection instead of trying the same password on every host (account lockout)."""

import ctypes
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

REACH_PORT = 445  # the session API's RPC runs over SMB named pipes
REACH_TIMEOUT = 2.0  # seconds: an offline PC otherwise holds the call for ~20 s


class Reason(StrEnum):
    UNREACHABLE = "unreachable"  # off, not on the network, or blocked by a firewall
    NOT_ADMIN = "not-admin"  # the account was accepted, but isn't an admin there
    REJECTED = "rejected"  # the account wasn't accepted: wrong password, locked…
    OTHER = "other"


# Codes seen on real hosts: 259 for a non-admin caller, 5 for an account the host refused.
_REJECTED = {5, 1326, 1327, 1330, 1331, 1909}
_UNREACHABLE = {53, 67, 1231, 1237, 1721, 1722, 1723, 1753}


class SessionsError(Exception):
    def __init__(self, reason: Reason, code: int = 0) -> None:
        super().__init__(f"{reason} (Windows error {code})" if code else str(reason))
        self.reason, self.code = reason, code


def reason_of(code: int) -> Reason:
    if code == 259:  # ERROR_NO_MORE_ITEMS: how a non-admin remote enumerate fails
        return Reason.NOT_ADMIN
    if code in _REJECTED:
        return Reason.REJECTED
    if code in _UNREACHABLE:
        return Reason.UNREACHABLE
    return Reason.OTHER


@dataclass(frozen=True)
class Account:
    user: str  # "DOMAIN\\name" or "name@domain"
    password: str


@dataclass(frozen=True)
class Session:
    user: str
    domain: str
    kind: str  # "console", "rdp" or "unknown" (a disconnected session's type is gone)
    state: str  # "active", "disconnected", …
    logon_time: datetime | None
    client: str = ""  # the RDP client's computer name, when there is one


def read_sessions(host: str | None, account: Account | None = None) -> list[Session]:
    """The logged-on sessions of `host` (None: this PC). Sessions with no user (services, the
    listening RDP stack) aren't logons and are left out. Raises SessionsError."""
    if host is not None:
        _check_reachable(host)
    with _as_account(account):
        return _enumerate(host)


def _check_reachable(host: str) -> None:
    try:
        socket.create_connection((host, REACH_PORT), REACH_TIMEOUT).close()
    except OSError as e:
        raise SessionsError(Reason.UNREACHABLE) from e


# ---- the Windows API ----

_STATES = {
    0: "active", 1: "connected", 2: "connectquery", 3: "shadow", 4: "disconnected",
    5: "idle", 6: "listen", 7: "reset", 8: "down", 9: "init",
}  # fmt: skip
_USER_NAME, _STATION_NAME, _DOMAIN_NAME, _CLIENT_NAME, _INFO_EX = 5, 6, 7, 10, 25


class _SessionInfo(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


class _InfoEx1(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("SessionState", ctypes.c_int),
        ("SessionFlags", ctypes.c_int),
        ("WinStationName", ctypes.c_wchar * 33),
        ("UserName", ctypes.c_wchar * 21),
        ("DomainName", ctypes.c_wchar * 18),
        ("LogonTime", ctypes.c_longlong),
        ("ConnectTime", ctypes.c_longlong),
        ("DisconnectTime", ctypes.c_longlong),
        ("LastInputTime", ctypes.c_longlong),
        ("CurrentTime", ctypes.c_longlong),
        ("IncomingBytes", ctypes.c_int),
        ("OutgoingBytes", ctypes.c_int),
        ("IncomingFrames", ctypes.c_int),
        ("OutgoingFrames", ctypes.c_int),
        ("IncomingCompressedBytes", ctypes.c_int),
        ("OutgoingCompressedBytes", ctypes.c_int),
    ]


class _InfoEx(ctypes.Structure):
    # A DWORD level, a 4-byte gap, then the 8-byte-aligned data.
    _fields_ = [("Level", ctypes.c_int), ("Reserved", ctypes.c_int), ("Data", _InfoEx1)]


_wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
_wts.WTSOpenServerW.restype = wintypes.HANDLE
_wts.WTSOpenServerW.argtypes = [wintypes.LPWSTR]
_wts.WTSCloseServer.argtypes = [wintypes.HANDLE]
_wts.WTSEnumerateSessionsW.restype = wintypes.BOOL
_wts.WTSEnumerateSessionsW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(ctypes.POINTER(_SessionInfo)), ctypes.POINTER(wintypes.DWORD),
]  # fmt: skip
_wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
_wts.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD),
]  # fmt: skip
_wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.LogonUserW.restype = wintypes.BOOL
_advapi32.LogonUserW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]  # fmt: skip
_advapi32.ImpersonateLoggedOnUser.restype = wintypes.BOOL
_advapi32.ImpersonateLoggedOnUser.argtypes = [wintypes.HANDLE]
_advapi32.RevertToSelf.restype = wintypes.BOOL
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _enumerate(host: str | None) -> list[Session]:
    server = _wts.WTSOpenServerW(host) if host else wintypes.HANDLE(0).value  # 0: this PC
    if host and not server:
        raise SessionsError(reason_of(err := ctypes.get_last_error()), err)
    try:
        listing = ctypes.POINTER(_SessionInfo)()
        count = wintypes.DWORD()
        if not _wts.WTSEnumerateSessionsW(server, 0, 1, ctypes.byref(listing), ctypes.byref(count)):
            raise SessionsError(reason_of(err := ctypes.get_last_error()), err)
        try:
            found = []
            for index in range(count.value):
                info = listing[index]
                user = _text(server, info.SessionId, _USER_NAME)
                if not user:
                    continue
                station = info.pWinStationName or _text(server, info.SessionId, _STATION_NAME)
                found.append(
                    Session(
                        user=user,
                        domain=_text(server, info.SessionId, _DOMAIN_NAME),
                        kind=session_kind(station or ""),
                        state=_STATES.get(info.State, "unknown"),
                        logon_time=_logon_time(server, info.SessionId),
                        client=_text(server, info.SessionId, _CLIENT_NAME),
                    )
                )
            return found
        finally:
            _wts.WTSFreeMemory(listing)
    finally:
        if host:
            _wts.WTSCloseServer(server)


def session_kind(station: str) -> str:
    station = station.casefold()
    if station == "console":
        return "console"
    return "rdp" if station.startswith("rdp-tcp") else "unknown"


def filetime(value: int) -> datetime | None:
    """A Windows FILETIME (100 ns steps since 1601, UTC) as a datetime; None when unset."""
    if value <= 0:
        return None
    try:
        return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=value // 10)
    except OverflowError:
        return None


def _query(server: int | None, session: int, kind: int) -> ctypes.c_void_p | None:
    buffer, size = ctypes.c_void_p(), wintypes.DWORD()
    if not _wts.WTSQuerySessionInformationW(
        server, session, kind, ctypes.byref(buffer), ctypes.byref(size)
    ):
        return None
    return buffer


def _text(server: int | None, session: int, kind: int) -> str:
    buffer = _query(server, session, kind)
    if buffer is None:
        return ""
    try:
        return ctypes.wstring_at(buffer) if buffer.value else ""
    finally:
        _wts.WTSFreeMemory(buffer)


def _logon_time(server: int | None, session: int) -> datetime | None:
    buffer = _query(server, session, _INFO_EX)
    if buffer is None:
        return None
    try:
        info = ctypes.cast(buffer, ctypes.POINTER(_InfoEx)).contents
        return filetime(info.Data.LogonTime) if info.Level == 1 else None
    finally:
        _wts.WTSFreeMemory(buffer)


@contextmanager
def _as_account(account: Account | None) -> Iterator[None]:
    """This thread uses `account` for the network calls inside; nothing changes locally."""
    if account is None:
        yield
        return
    domain, _sep, name = account.user.rpartition("\\")  # "DOMAIN\\name", or a UPN
    token = wintypes.HANDLE()
    new_credentials, provider_winnt50 = 9, 3
    if not _advapi32.LogonUserW(
        name, domain or None, account.password, new_credentials, provider_winnt50,
        ctypes.byref(token),
    ):  # fmt: skip
        raise SessionsError(reason_of(err := ctypes.get_last_error()), err)
    try:
        if not _advapi32.ImpersonateLoggedOnUser(token):
            raise SessionsError(Reason.OTHER, ctypes.get_last_error())
        try:
            yield
        finally:
            _advapi32.RevertToSelf()
    finally:
        _kernel32.CloseHandle(token)
