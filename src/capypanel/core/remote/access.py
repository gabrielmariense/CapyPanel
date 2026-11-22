import ctypes
import socket
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum

REACH_PORT = 445  # Windows' remote calls (sessions, shutdown, services, printers) use SMB pipes
REACH_TIMEOUT = 2.0  # seconds: an offline PC otherwise holds a call for ~20 s


class Reason(StrEnum):
    UNREACHABLE = "unreachable"
    NOT_ADMIN = "not-admin"
    REJECTED = "rejected"
    OTHER = "other"


# Codes seen on real hosts: 259 for a non-admin caller, 5 for an account the host refused.
_REJECTED = {5, 1326, 1327, 1330, 1331, 1909}
_UNREACHABLE = {53, 67, 1231, 1237, 1721, 1722, 1723, 1753}


def code_text(code: int) -> str:
    """Long codes (WMI's, COM's) in hex: nobody finds 0x80041002 as 2147749890."""
    return f"0x{code:08X}" if code > 0xFFFF else str(code)


class RemoteError(Exception):
    def __init__(self, reason: Reason, code: int = 0) -> None:
        super().__init__(f"{reason} (Windows error {code_text(code)})" if code else str(reason))
        self.reason, self.code = reason, code


def reason_of(code: int) -> Reason:
    if code == 259:  # ERROR_NO_MORE_ITEMS: how a non-admin remote enumerate fails
        return Reason.NOT_ADMIN
    if code in _REJECTED:
        return Reason.REJECTED
    if code in _UNREACHABLE:
        return Reason.UNREACHABLE
    return Reason.OTHER


def last_error() -> RemoteError:
    code = ctypes.get_last_error()
    return RemoteError(reason_of(code), code)


@dataclass(frozen=True)
class Account:
    user: str
    password: str


def check_reachable(host: str) -> None:
    try:
        socket.create_connection((host, REACH_PORT), REACH_TIMEOUT).close()
    except OSError as e:
        raise RemoteError(Reason.UNREACHABLE) from e


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


@contextmanager
def as_account(account: Account | None) -> Iterator[None]:
    with network_identity(account) as identity, identity():
        yield


@contextmanager
def network_identity(
    account: Account | None,
) -> Iterator[Callable[[], AbstractContextManager[None]]]:
    """Network-only logon: remote calls use `account`; programs started meanwhile don't."""
    if account is None:
        yield nullcontext
        return
    domain, _sep, name = account.user.rpartition("\\")
    token = wintypes.HANDLE()
    new_credentials, provider_winnt50 = 9, 3  # each PC checks the password, not this one
    if not _advapi32.LogonUserW(
        name, domain or None, account.password, new_credentials, provider_winnt50,
        ctypes.byref(token),
    ):  # fmt: skip
        raise last_error()
    try:
        yield lambda: _impersonating(token)
    finally:
        _kernel32.CloseHandle(token)


@contextmanager
def _impersonating(token: wintypes.HANDLE) -> Iterator[None]:
    if not _advapi32.ImpersonateLoggedOnUser(token):
        raise RemoteError(Reason.OTHER, ctypes.get_last_error())
    try:
        yield
    finally:
        _advapi32.RevertToSelf()
