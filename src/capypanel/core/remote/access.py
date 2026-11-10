"""What every call to another PC shares: the reasons Windows refuses one, a quick check that the PC
answers at all, and calling as another account.

Another account (an admin, when the user's daily one isn't) goes through a "new credentials"
logon, like `runas /netonly`: only the network identity of this thread changes, for the call.
Windows doesn't check that password here; each target does, so callers must stop at the first
rejection instead of trying the same password on every host (account lockout)."""

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
    UNREACHABLE = "unreachable"  # off, not on the network, or blocked by a firewall
    NOT_ADMIN = "not-admin"  # the account was accepted, but isn't an admin there
    REJECTED = "rejected"  # the account wasn't accepted: wrong password, locked…
    OTHER = "other"


# Codes seen on real hosts: 259 for a non-admin caller, 5 for an account the host refused.
_REJECTED = {5, 1326, 1327, 1330, 1331, 1909}
_UNREACHABLE = {53, 67, 1231, 1237, 1721, 1722, 1723, 1753}


def code_text(code: int) -> str:
    """A Windows error's number as people look it up: 5 or 1722, and 0x80041002 for the long
    ones (WMI's and COM's), which nobody finds as 2147749890."""
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
    """The error Windows left for this thread's last failed call."""
    code = ctypes.get_last_error()
    return RemoteError(reason_of(code), code)


@dataclass(frozen=True)
class Account:
    user: str  # "DOMAIN\\name" or "name@domain"
    password: str


def check_reachable(host: str) -> None:
    """Raises RemoteError (UNREACHABLE) unless `host` answers on file sharing's port."""
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
    """This thread uses `account` for the network calls inside; nothing changes locally."""
    with network_identity(account) as identity, identity():
        yield


@contextmanager
def network_identity(
    account: Account | None,
) -> Iterator[Callable[[], AbstractContextManager[None]]]:
    """Logs `account` on once, for the network only; each `with identity():` block inside then
    uses it on this thread. One logon means one connection to each PC for all the blocks, and
    programs started between them run as the user, as usual."""
    if account is None:
        yield nullcontext
        return
    domain, _sep, name = account.user.rpartition("\\")  # "DOMAIN\\name", or a UPN
    token = wintypes.HANDLE()
    new_credentials, provider_winnt50 = 9, 3
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
