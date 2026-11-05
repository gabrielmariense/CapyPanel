"""Restarting a Windows service on another PC (the Print Spooler, for a stuck queue), and
whether it's running: Windows' service manager over its own remote call, as `sc \\\\PC query`,
`stop` and `start` do. Nothing is installed or run on the target; the account needs admin rights
there."""

import ctypes
import time
from collections.abc import Callable
from ctypes import wintypes

from capypanel.core.remote.access import Account, as_account, check_reachable, last_error

SPOOLER = "Spooler"
STOP_TIMEOUT = 30.0  # seconds a service gets to stop before giving up
_CONNECT = 0x0001
_QUERY, _START, _STOP = 0x0004, 0x0010, 0x0020
_STOPPED, _STOP_CONTROL = 1, 1
STATES = {  # what QueryServiceStatus reports, by the words sc.exe uses
    1: "stopped", 2: "starting", 3: "stopping", 4: "running",
    5: "continuing", 6: "pausing", 7: "paused",
}  # fmt: skip
_NOT_ACTIVE = 1062  # ERROR_SERVICE_NOT_ACTIVE: stopping one that's already stopped


class _Status(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in ("type", "state", "accepted", "exit", "service_exit", "checkpoint", "wait")
    ]


def restart_service(
    host: str,
    name: str,
    account: Account | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Stops service `name` on `host`, waits until it has stopped, and starts it again. A
    stopped service is just started. Raises RemoteError, or TimeoutError when it won't stop."""
    check_reachable(host)
    with as_account(account):
        manager = _advapi32.OpenSCManagerW(host, None, _CONNECT)
        if not manager:
            raise last_error()
        try:
            service = _advapi32.OpenServiceW(manager, name, _QUERY | _START | _STOP)
            if not service:
                raise last_error()
            try:
                _stop(service, sleep)
                if not _advapi32.StartServiceW(service, 0, None):
                    raise last_error()
            finally:
                _advapi32.CloseServiceHandle(service)
        finally:
            _advapi32.CloseServiceHandle(manager)


def service_state(host: str, name: str, account: Account | None = None) -> str:
    """Whether service `name` on `host` runs: "running", "stopped"… (STATES). Raises
    RemoteError."""
    check_reachable(host)
    with as_account(account):
        manager = _advapi32.OpenSCManagerW(host, None, _CONNECT)
        if not manager:
            raise last_error()
        try:
            service = _advapi32.OpenServiceW(manager, name, _QUERY)
            if not service:
                raise last_error()
            try:
                status = _Status()
                if not _advapi32.QueryServiceStatus(service, ctypes.byref(status)):
                    raise last_error()
                return STATES.get(status.state, "unknown")
            finally:
                _advapi32.CloseServiceHandle(service)
        finally:
            _advapi32.CloseServiceHandle(manager)


def _stop(service: int, sleep: Callable[[float], None]) -> None:
    status = _Status()
    if not _advapi32.ControlService(service, _STOP_CONTROL, ctypes.byref(status)):
        error = last_error()
        if error.code != _NOT_ACTIVE:
            raise error
        return
    waited = 0.0
    while status.state != _STOPPED:
        if waited >= STOP_TIMEOUT:
            raise TimeoutError(f"the service didn't stop within {STOP_TIMEOUT:.0f} s")
        sleep(0.5)
        waited += 0.5
        if not _advapi32.QueryServiceStatus(service, ctypes.byref(status)):
            raise last_error()


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.OpenSCManagerW.restype = wintypes.HANDLE
_advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
_advapi32.OpenServiceW.restype = wintypes.HANDLE
_advapi32.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
_advapi32.ControlService.restype = wintypes.BOOL
_advapi32.ControlService.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(_Status)]
_advapi32.QueryServiceStatus.restype = wintypes.BOOL
_advapi32.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Status)]
_advapi32.StartServiceW.restype = wintypes.BOOL
_advapi32.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
_advapi32.CloseServiceHandle.restype = wintypes.BOOL
_advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
