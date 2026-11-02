"""Restarting or shutting down another PC, and cancelling a restart that's still waiting: Windows'
remote shutdown call (the InitShutdown pipe over file sharing), as `shutdown /m` does. Nothing is
installed or run on the target; the account needs the right to shut it down remotely, which
admins have."""

import ctypes
from ctypes import wintypes

from capypanel.core.remote.access import (
    Account,
    RemoteError,
    as_account,
    check_reachable,
    last_error,
)

MAX_DELAY = 600  # seconds; longer waits are better planned another way
# "Other (Planned)": what `shutdown /m` reports when given no reason.
_PLANNED = 0x80000000
_IN_PROGRESS, _NONE_PENDING = 1115, 1116


def restart(host: str, delay: int = 0, message: str = "", account: Account | None = None) -> None:
    """Restarts `host` after `delay` seconds, showing `message` to its users meanwhile. Open
    programs close without saving. Raises RemoteError."""
    _shut_down(host, delay, message, True, account)


def shut_down(host: str, delay: int = 0, message: str = "", account: Account | None = None) -> None:
    """Turns `host` off after `delay` seconds; like restart(). Raises RemoteError."""
    _shut_down(host, delay, message, False, account)


def cancel(host: str, account: Account | None = None) -> bool:
    """Cancels a restart or shutdown still waiting on `host`. False when none was waiting.
    Raises RemoteError."""
    check_reachable(host)
    with as_account(account):
        if _advapi32.AbortSystemShutdownW(f"\\\\{host}"):
            return True
        error = last_error()
        if error.code == _NONE_PENDING:
            return False
        raise error


def already_pending(error: RemoteError) -> bool:
    """Whether a restart or shutdown failed because another one is already on its way."""
    return error.code == _IN_PROGRESS


def _shut_down(host: str, delay: int, message: str, restart: bool, account: Account | None) -> None:
    if not 0 <= delay <= MAX_DELAY:
        raise ValueError(f"delay must be 0 to {MAX_DELAY} seconds")
    check_reachable(host)
    with as_account(account):
        if not _advapi32.InitiateSystemShutdownExW(
            f"\\\\{host}", message or None, delay, True, restart, _PLANNED
        ):
            raise last_error()


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.InitiateSystemShutdownExW.restype = wintypes.BOOL
_advapi32.InitiateSystemShutdownExW.argtypes = [
    wintypes.LPWSTR, wintypes.LPWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.BOOL,
    wintypes.DWORD,
]  # fmt: skip
_advapi32.AbortSystemShutdownW.restype = wintypes.BOOL
_advapi32.AbortSystemShutdownW.argtypes = [wintypes.LPWSTR]
