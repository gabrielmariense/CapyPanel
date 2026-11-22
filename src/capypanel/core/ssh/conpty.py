"""Nothing typed or printed is logged."""

from __future__ import annotations

import ctypes
import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from ctypes import wintypes as wt
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class COORD(ctypes.Structure):
    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("lpReserved", wt.LPWSTR),
        ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD),
        ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD),
        ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD),
        ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD),
        ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (n, ctypes.c_ulonglong)
        for n in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_HANDLE_P = ctypes.POINTER(wt.HANDLE)
k32.CreatePipe.argtypes = [_HANDLE_P, _HANDLE_P, ctypes.c_void_p, wt.DWORD]
k32.CreatePipe.restype = wt.BOOL
k32.CreatePseudoConsole.argtypes = [COORD, wt.HANDLE, wt.HANDLE, wt.DWORD, _HANDLE_P]
k32.CreatePseudoConsole.restype = ctypes.c_long
k32.ResizePseudoConsole.argtypes = [wt.HANDLE, COORD]
k32.ResizePseudoConsole.restype = ctypes.c_long
k32.ClosePseudoConsole.argtypes = [wt.HANDLE]
k32.ClosePseudoConsole.restype = None
k32.InitializeProcThreadAttributeList.argtypes = [
    ctypes.c_void_p,
    wt.DWORD,
    wt.DWORD,
    ctypes.POINTER(ctypes.c_size_t),
]
k32.InitializeProcThreadAttributeList.restype = wt.BOOL
k32.UpdateProcThreadAttribute.argtypes = [
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_void_p,
]
k32.UpdateProcThreadAttribute.restype = wt.BOOL
k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
k32.DeleteProcThreadAttributeList.restype = None
k32.CreateProcessW.argtypes = [
    wt.LPCWSTR,
    wt.LPWSTR,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wt.BOOL,
    wt.DWORD,
    ctypes.c_void_p,
    wt.LPCWSTR,
    ctypes.POINTER(STARTUPINFOEXW),
    ctypes.POINTER(PROCESS_INFORMATION),
]
k32.CreateProcessW.restype = wt.BOOL
k32.ReadFile.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    ctypes.c_void_p,
]
k32.ReadFile.restype = wt.BOOL
k32.WriteFile.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    ctypes.c_void_p,
]
k32.WriteFile.restype = wt.BOOL
k32.CloseHandle.argtypes = [wt.HANDLE]
k32.CloseHandle.restype = wt.BOOL
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.GetExitCodeProcess.restype = wt.BOOL
k32.ResumeThread.argtypes = [wt.HANDLE]
k32.ResumeThread.restype = wt.DWORD
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.TerminateProcess.restype = wt.BOOL
k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wt.LPCWSTR]
k32.CreateJobObjectW.restype = wt.HANDLE
k32.SetInformationJobObject.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
k32.SetInformationJobObject.restype = wt.BOOL
k32.AssignProcessToJobObject.argtypes = [wt.HANDLE, wt.HANDLE]
k32.AssignProcessToJobObject.restype = wt.BOOL
k32.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wt.BOOL]
k32.SetConsoleCtrlHandler.restype = wt.BOOL

_PSEUDOCONSOLE = 0x00020016
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT_INFORMATION = 9
_STARTF_USESTDHANDLES = 0x00000100
_INFINITE = 0xFFFFFFFF
STATUS_CONTROL_C_EXIT = 0xC000013A  # what a program ends with when its pseudo console is closed

_ctrl_c_allowed = False


def allow_ctrl_c_in_children() -> None:
    """Clears an inherited "ignore Ctrl+C" flag: with it, Ctrl+C never stops ping in cmd."""
    global _ctrl_c_allowed
    if not _ctrl_c_allowed:
        k32.SetConsoleCtrlHandler(None, False)
        _ctrl_c_allowed = True


def _environment_block(env: Mapping[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    items = sorted(env.items(), key=lambda kv: kv[0].upper())
    return ctypes.create_unicode_buffer("".join(f"{k}={v}\0" for k, v in items) + "\0")


CARRIED_DIR = Path(__file__).resolve().parents[2] / "vendor" / "conpty"
WINDOWS_11 = 22000  # Windows 11's first build: from it on, Windows' own engine is enough
_GLYPH_WIDTH_CONSOLE = 0x18  # the carried engine counts cells as Windows' own console does


@dataclass(frozen=True)
class Engine:
    name: str
    create: Callable[..., int]
    resize: Callable[..., int]
    close: Callable[..., None]
    flags: int = 0
    # Half a flag (a regional indicator): the one character the two engines count apart.
    regional_indicator_cells: int = 2


WINDOWS = Engine(
    "Windows' own engine", k32.CreatePseudoConsole, k32.ResizePseudoConsole, k32.ClosePseudoConsole
)
_carried: list[Engine | None] = []


def carried_engine() -> Engine | None:
    if not _carried:
        _carried.append(_load_carried())
    return _carried[0]


def _load_carried() -> Engine | None:
    if not (CARRIED_DIR / "OpenConsole.exe").is_file():  # conpty.dll would run Windows' own
        log.warning("The console engine CapyPanel carries is missing from %s", CARRIED_DIR)
        return None
    try:
        dll = ctypes.WinDLL(str(CARRIED_DIR / "conpty.dll"))
        functions = (
            dll.ConptyCreatePseudoConsole,
            dll.ConptyResizePseudoConsole,
            dll.ConptyClosePseudoConsole,
        )
    except (OSError, AttributeError) as error:
        log.warning("The console engine CapyPanel carries won't load: %s", error)
        return None
    windows = (k32.CreatePseudoConsole, k32.ResizePseudoConsole, k32.ClosePseudoConsole)
    for carried, own in zip(functions, windows, strict=True):
        carried.argtypes, carried.restype = own.argtypes, own.restype
    return Engine(
        "the engine CapyPanel carries",
        *functions,
        flags=_GLYPH_WIDTH_CONSOLE,
        regional_indicator_cells=1,
    )


def _windows_build() -> int:
    return sys.getwindowsversion().build


def default_engine() -> Engine:
    """Windows 10's own engine takes no key once ssh.exe logs in: it gets the carried one."""
    if _windows_build() < WINDOWS_11:
        carried = carried_engine()
        if carried is not None:
            return carried
    return WINDOWS


class PseudoConsole:
    """on_ready and on_exit come on this class's own threads: receivers hand the work to theirs."""

    def __init__(
        self,
        argv: Sequence[str],
        cols: int,
        rows: int,
        *,
        on_ready: Callable[[], None],
        on_exit: Callable[[int], None],
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        max_pending: int = 1 << 20,
        flags: int = 0,
        engine: Engine | None = None,
    ) -> None:
        """Never INHERIT_CURSOR: it asks for the cursor position at start."""
        self.argv = list(argv)
        self.engine = engine or default_engine()
        self._on_ready = on_ready
        self._on_exit = on_exit
        self._max_pending = max_pending
        self._pending = bytearray()
        self._cond = threading.Condition()
        self._eof = False
        self._closing = False
        self._closed = False
        self.bytes_read = 0
        self.bytes_written = 0
        self.exit_code: int | None = None
        self.started_at = time.monotonic()

        allow_ctrl_c_in_children()
        in_r, in_w, out_r, out_w = wt.HANDLE(), wt.HANDLE(), wt.HANDLE(), wt.HANDLE()
        if not (
            k32.CreatePipe(ctypes.byref(in_r), ctypes.byref(in_w), None, 0)
            and k32.CreatePipe(ctypes.byref(out_r), ctypes.byref(out_w), None, 0)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        hr = self._create(cols, rows, in_r, out_w, flags)
        if hr != 0 and self.engine is not WINDOWS:
            log.warning(
                "%s didn't start (%#x): Windows' own instead", self.engine.name, hr & 0xFFFFFFFF
            )
            self.engine = WINDOWS
            hr = self._create(cols, rows, in_r, out_w, flags)
        k32.CloseHandle(in_r)
        k32.CloseHandle(out_w)
        if hr != 0:
            k32.CloseHandle(in_w)
            k32.CloseHandle(out_r)
            raise OSError(f"CreatePseudoConsole failed: {hr & 0xFFFFFFFF:#x}")
        log.info("Pseudo console from %s", self.engine.name)
        self._in, self._out = in_w, out_r

        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        self._attrs = ctypes.create_string_buffer(size.value)
        self._attrs_ready = False
        if not k32.InitializeProcThreadAttributeList(self._attrs, 1, 0, ctypes.byref(size)):
            error = ctypes.get_last_error()
            self._undo_start()
            raise ctypes.WinError(error)
        self._attrs_ready = True
        if not k32.UpdateProcThreadAttribute(
            self._attrs,
            0,
            _PSEUDOCONSOLE,
            ctypes.c_void_p(self._hpc.value),
            ctypes.sizeof(wt.HANDLE),
            None,
            None,
        ):
            error = ctypes.get_last_error()
            self._undo_start()
            raise ctypes.WinError(error)
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        # Empty std handles: otherwise a program started from redirected ones writes there.
        si.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        si.lpAttributeList = ctypes.cast(self._attrs, ctypes.c_void_p)
        self._pi = PROCESS_INFORMATION()
        # Suspended until it's in the job that ends it on close: no ssh.exe outlives its tab.
        flags = _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT | _CREATE_SUSPENDED
        env_block = _environment_block(env) if env is not None else None
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(self.argv))
        if not k32.CreateProcessW(
            None,
            cmdline,
            None,
            None,
            False,
            flags,
            ctypes.cast(env_block, ctypes.c_void_p) if env_block else None,
            cwd,
            ctypes.byref(si),
            ctypes.byref(self._pi),
        ):
            error = ctypes.get_last_error()
            self._undo_start()
            raise ctypes.WinError(error)
        self.pid = int(self._pi.dwProcessId)
        self._job = k32.CreateJobObjectW(None, None)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not (
            self._job
            and k32.SetInformationJobObject(
                self._job, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
            )
            and k32.AssignProcessToJobObject(self._job, self._pi.hProcess)
        ):
            error = ctypes.get_last_error()
            k32.TerminateProcess(self._pi.hProcess, 1)
            k32.CloseHandle(self._pi.hThread)
            k32.CloseHandle(self._pi.hProcess)
            if self._job:
                k32.CloseHandle(self._job)
            self._undo_start()
            raise ctypes.WinError(error)
        self._writes: queue.Queue[bytes | None] = queue.Queue()
        self._reader = threading.Thread(target=self._read, name="conpty-reader", daemon=True)
        self._writer = threading.Thread(target=self._write, name="conpty-writer", daemon=True)
        self._waiter = threading.Thread(target=self._wait, name="conpty-waiter", daemon=True)
        self._reader.start()
        self._writer.start()
        k32.ResumeThread(self._pi.hThread)
        self._waiter.start()

    def _create(self, cols: int, rows: int, in_r: wt.HANDLE, out_w: wt.HANDLE, flags: int) -> int:
        self._hpc = wt.HANDLE()
        size, flags = COORD(cols, rows), flags | self.engine.flags
        return self.engine.create(size, in_r, out_w, flags, ctypes.byref(self._hpc))

    def _read(self) -> None:
        buf = ctypes.create_string_buffer(65536)
        got = wt.DWORD()
        while k32.ReadFile(self._out, buf, 65536, ctypes.byref(got), None) and got.value:
            chunk = buf.raw[: got.value]
            with self._cond:
                # Full: the reader waits, so a flood waits for the screen and Ctrl+C acts at once.
                while len(self._pending) >= self._max_pending and not self._closing:
                    self._cond.wait(0.1)
                was_empty = not self._pending
                self._pending += chunk
                self.bytes_read += len(chunk)
            if was_empty:
                self._on_ready()
        with self._cond:
            self._eof = True
        self._on_ready()

    def take(self, limit: int) -> bytes:
        with self._cond:
            data = bytes(self._pending[:limit])
            del self._pending[:limit]
            self._cond.notify_all()
            return data

    @property
    def pending(self) -> int:
        with self._cond:
            return len(self._pending)

    @property
    def at_eof(self) -> bool:
        with self._cond:
            return self._eof and not self._pending

    def write(self, data: bytes) -> None:
        if data and not self._closed:
            self._writes.put(data)

    def _write(self) -> None:
        done = wt.DWORD()
        while True:
            data = self._writes.get()
            if data is None:
                return
            if not k32.WriteFile(self._in, data, len(data), ctypes.byref(done), None):
                return
            self.bytes_written += len(data)

    def _undo_start(self) -> None:
        self._closed = True
        self.engine.close(self._hpc)
        k32.CloseHandle(self._in)
        k32.CloseHandle(self._out)
        if getattr(self, "_attrs_ready", False):
            k32.DeleteProcThreadAttributeList(self._attrs)

    def _wait(self) -> None:
        k32.WaitForSingleObject(self._pi.hProcess, _INFINITE)
        code = wt.DWORD()
        k32.GetExitCodeProcess(self._pi.hProcess, ctypes.byref(code))
        self.exit_code = int(code.value)
        self._on_exit(self.exit_code)

    @property
    def running(self) -> bool:
        return self.exit_code is None

    def resize(self, cols: int, rows: int) -> None:
        if not self._closed:
            self.engine.resize(self._hpc, COORD(max(1, cols), max(1, rows)))

    def close(self) -> float:
        if self._closed:
            return 0.0
        self._closed = True
        with self._cond:
            self._closing = True
            self._cond.notify_all()
        start = time.perf_counter()
        self.engine.close(self._hpc)
        took = time.perf_counter() - start
        self._writes.put(None)
        self._writer.join(2)
        k32.CloseHandle(self._in)
        k32.CloseHandle(self._job)
        self._reader.join(3)
        self._waiter.join(3)
        k32.CloseHandle(self._out)
        k32.DeleteProcThreadAttributeList(self._attrs)
        k32.CloseHandle(self._pi.hThread)
        k32.CloseHandle(self._pi.hProcess)
        return took
