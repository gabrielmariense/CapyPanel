"""The printers installed on another PC, and clearing a printer's queue: Windows' print spooler
over its own remote call, as the Print Management console does. Nothing is installed or run on
the target. Printers a user added for themselves from a print server aren't the PC's own and
don't show; the PC's own printers do, whoever uses them."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from capypanel.core.remote.access import Account, as_account, check_reachable, last_error

_ENUM_LOCAL, _ENUM_NAME = 0x2, 0x8
_ADMINISTER = 0x4
_PURGE = 3  # PRINTER_CONTROL_PURGE: deletes every job in the queue
_SHORT_BUFFER = 122  # ERROR_INSUFFICIENT_BUFFER
# The spooler's status bits that mean someone should look, as Windows names them.
_PROBLEMS = {
    0x2: "error", 0x8: "paper jam", 0x10: "out of paper", 0x40: "paper problem",
    0x80: "offline", 0x400: "output bin full", 0x40000: "out of toner", 0x80000: "toner low",
    0x100000: "page punt", 0x200000: "user intervention", 0x400000: "out of memory",
    0x800000: "door open", 0x1: "paused",
}  # fmt: skip


@dataclass(frozen=True)
class HostPrinter:
    name: str
    driver: str
    port: str
    shared_as: str  # the share name, or "" when not shared
    jobs: int  # documents waiting in its queue
    problems: tuple[str, ...]  # what the spooler reports, e.g. ("paper jam",); () when fine


def list_printers(host: str | None, account: Account | None = None) -> list[HostPrinter]:
    """The printers installed on `host` (None: this PC), by name. Raises RemoteError."""
    if host is not None:
        check_reachable(host)
    with as_account(account):
        return sorted(_enumerate(host), key=lambda p: p.name.casefold())


def clear_queue(host: str, printer: str, account: Account | None = None) -> None:
    """Deletes every document waiting for `printer` on `host`. Raises RemoteError."""
    check_reachable(host)
    with as_account(account):
        handle = wintypes.HANDLE()
        defaults = _Defaults(None, None, _ADMINISTER)
        if not _winspool.OpenPrinterW(
            f"\\\\{host}\\{printer}", ctypes.byref(handle), ctypes.byref(defaults)
        ):
            raise last_error()
        try:
            if not _winspool.SetPrinterW(handle, 0, None, _PURGE):
                raise last_error()
        finally:
            _winspool.ClosePrinter(handle)


def _enumerate(host: str | None) -> list[HostPrinter]:
    flags, name = (_ENUM_NAME, f"\\\\{host}") if host else (_ENUM_LOCAL, None)
    needed, count = wintypes.DWORD(), wintypes.DWORD()
    _winspool.EnumPrintersW(flags, name, 2, None, 0, ctypes.byref(needed), ctypes.byref(count))
    if not needed.value:
        error = last_error()
        if error.code and error.code != _SHORT_BUFFER:
            raise error
        return []
    buffer = ctypes.create_string_buffer(needed.value)
    if not _winspool.EnumPrintersW(
        flags, name, 2, buffer, needed, ctypes.byref(needed), ctypes.byref(count)
    ):
        raise last_error()
    infos = ctypes.cast(buffer, ctypes.POINTER(_Info2))
    return [_printer(infos[index]) for index in range(count.value)]


def _printer(info: "_Info2") -> HostPrinter:
    full = info.pPrinterName or ""
    return HostPrinter(
        name=full.rsplit("\\", 1)[-1],  # "\\\\PC\\Name" from a remote listing
        driver=info.pDriverName or "",
        port=info.pPortName or "",
        shared_as=(info.pShareName or "") if info.Attributes & 0x8 else "",  # ATTRIBUTE_SHARED
        jobs=info.cJobs,
        problems=tuple(text for bit, text in _PROBLEMS.items() if info.Status & bit),
    )


class _Defaults(ctypes.Structure):
    _fields_ = [
        ("pDatatype", wintypes.LPWSTR),
        ("pDevMode", ctypes.c_void_p),
        ("DesiredAccess", wintypes.DWORD),
    ]


class _Info2(ctypes.Structure):
    _fields_ = [
        *((name, wintypes.LPWSTR) for name in (
            "pServerName", "pPrinterName", "pShareName", "pPortName", "pDriverName",
            "pComment", "pLocation")),
        ("pDevMode", ctypes.c_void_p),
        *((name, wintypes.LPWSTR) for name in (
            "pSepFile", "pPrintProcessor", "pDatatype", "pParameters")),
        ("pSecurityDescriptor", ctypes.c_void_p),
        *((name, wintypes.DWORD) for name in (
            "Attributes", "Priority", "DefaultPriority", "StartTime", "UntilTime", "Status",
            "cJobs", "AveragePPM")),
    ]  # fmt: skip


_winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
_winspool.EnumPrintersW.restype = wintypes.BOOL
_winspool.EnumPrintersW.argtypes = [
    wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
]  # fmt: skip
_winspool.OpenPrinterW.restype = wintypes.BOOL
_winspool.OpenPrinterW.argtypes = [
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.HANDLE),
    ctypes.POINTER(_Defaults),
]
_winspool.SetPrinterW.restype = wintypes.BOOL
_winspool.SetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_winspool.ClosePrinter.restype = wintypes.BOOL
_winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
