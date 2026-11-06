"""Who is logged on to a computer, and logging them off, disconnecting them or sending them a
message: the Windows session API (WTS) over its own RPC channel, called from here. Nothing is
installed or run on the target, and it reads typed fields, so it works whatever the target's
display language. Another account goes through `access.as_account`."""

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from capypanel.core.remote.access import Account, as_account, check_reachable, last_error

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Session:
    user: str
    domain: str
    kind: str  # "console", "rdp" or "unknown" (a disconnected session's type is gone)
    state: str  # "active", "disconnected", …
    logon_time: datetime | None
    client: str = ""  # the RDP client's computer name, when there is one
    session_id: int = -1  # Windows' number for it on that host, for Log off and the like


def read_sessions(host: str | None, account: Account | None = None) -> list[Session]:
    """The logged-on sessions of `host` (None: this PC). Sessions with no user (services, the
    listening RDP stack) aren't logons and are left out. Raises RemoteError."""
    if host is not None:
        check_reachable(host)
    with as_account(account):
        return _enumerate(host)


def log_off(host: str, session_id: int, account: Account | None = None) -> None:
    """Signs the session out; its open programs close without saving. Raises RemoteError."""
    _act(host, account, lambda server: _wts.WTSLogoffSession(server, session_id, False))


def disconnect(host: str, session_id: int, account: Account | None = None) -> None:
    """Disconnects the session: its programs keep running and the user can come back to them.
    Raises RemoteError."""
    _act(host, account, lambda server: _wts.WTSDisconnectSession(server, session_id, False))


def send_message(
    host: str, session_id: int, title: str, text: str, account: Account | None = None
) -> None:
    """Pops up `text` in the session, with an OK button; doesn't wait for the user to read it.
    Raises RemoteError."""
    style = 0x40 | 0x40000  # an information icon, kept above the user's windows
    answer = wintypes.DWORD()

    def call(server: int) -> bool:
        return _wts.WTSSendMessageW(
            server, session_id, title, len(title) * 2, text, len(text) * 2, style, 0,
            ctypes.byref(answer), False,
        )  # fmt: skip

    _act(host, account, call)


def _act(host: str, account: Account | None, call: Callable[[int], bool]) -> None:
    """Runs `call` with an open handle to `host`'s session API."""
    check_reachable(host)
    with as_account(account):
        server = _wts.WTSOpenServerW(host)
        if not server:
            raise last_error()
        try:
            if not call(server):
                raise last_error()
        finally:
            _wts.WTSCloseServer(server)


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
_wts.WTSLogoffSession.restype = wintypes.BOOL
_wts.WTSLogoffSession.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL]
_wts.WTSDisconnectSession.restype = wintypes.BOOL
_wts.WTSDisconnectSession.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL]
_wts.WTSSendMessageW.restype = wintypes.BOOL
_wts.WTSSendMessageW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, wintypes.LPWSTR,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
]  # fmt: skip


def _enumerate(host: str | None) -> list[Session]:
    server = _wts.WTSOpenServerW(host) if host else wintypes.HANDLE(0).value  # 0: this PC
    if host and not server:
        raise last_error()
    try:
        listing = ctypes.POINTER(_SessionInfo)()
        count = wintypes.DWORD()
        if not _wts.WTSEnumerateSessionsW(server, 0, 1, ctypes.byref(listing), ctypes.byref(count)):
            raise last_error()
        try:
            found, seen = [], []
            for index in range(count.value):
                info = listing[index]
                user = _text(server, info.SessionId, _USER_NAME)
                station = info.pWinStationName or _text(server, info.SessionId, _STATION_NAME)
                state = _STATES.get(info.State, "unknown")
                seen.append(f"{info.SessionId}:{station or '-'}:{state}:{'user' if user else '-'}")
                if not user:
                    continue
                found.append(
                    Session(
                        user=user,
                        domain=_text(server, info.SessionId, _DOMAIN_NAME),
                        kind=session_kind(station or ""),
                        state=state,
                        logon_time=_logon_time(server, info.SessionId),
                        client=_text(server, info.SessionId, _CLIENT_NAME),
                        session_id=info.SessionId,
                    )
                )
            # Every session Windows listed (no names), to explain a user that didn't show up.
            log.info("Sessions on %s: %s", host or "this PC", " ".join(seen))
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
