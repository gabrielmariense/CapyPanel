"""The separate window's holder (topic-029 E): CapyPanel's own exe, started with FLAG, runs
ssh.exe in a console window of its own. When ssh.exe ends with an error the window stays open
under ssh.exe's message until a key is pressed, so the message can be read; after a normal end
it closes, as ssh.exe's own window did.

- Its console: it lets go of any console it was started with and opens its own, so a run from
  source shows the same window as the built exe. Started with ATTACH, a probe's flag, it keeps
  the console it was started with, or takes its parent's, so nothing shows on screen.
- ssh.exe starts suspended, goes into a job object that ends it whenever the holder ends
  (closing the window ends both), and only then runs.
- Ctrl+C is ssh.exe's: the holder's own handler keeps the holder alive through it. It never
  sets "ignore Ctrl+C" for itself, which ssh.exe would inherit (then Ctrl+C couldn't cancel a
  hanging connection), and it clears one it was started with.

The exe reads FLAG before Qt is imported (__main__), so this start skips the single-instance
check and the tray. It writes no settings and no log."""

import ctypes
import subprocess
import time
from collections.abc import Sequence
from ctypes import wintypes as wt
from dataclasses import dataclass
from typing import Protocol

from capypanel.core import i18n
from capypanel.core.i18n import _
from capypanel.core.ssh.ending import error_line, is_error

FLAG = "--ssh-holder"
ATTACH = "--attach"  # a probe's: the console it's given, so nothing shows on screen
LANGUAGE, HOST = "--lang=", "--host="

# The holder's own exit codes. After ssh.exe's end, and after the key, it's always 0: Windows
# Terminal closes a tab whose program ends with 0, and keeps one open that ends otherwise.
DONE, NOT_STARTED_BY_CAPYPANEL, NO_CONSOLE = 0, 2, 3
# Seconds after the words show in which a key doesn't close the window. At the host key
# question a bare Enter refuses and ssh.exe ends at once, so a quick second Enter, pressed
# because nothing seemed to happen, would close it before "Host key verification failed." was
# read (Kerrigan).
KEY_GRACE = 1.0


@dataclass(frozen=True)
class Request:
    argv: list[str]  # the program and its arguments: ssh.exe's, or a probe's stand-in
    host: str  # the name the words use
    language: str
    attach: bool = False


def args_for(argv: Sequence[str], host: str, language: str) -> list[str]:
    """What follows CapyPanel's own exe to start a holder for `argv`."""
    return [FLAG, LANGUAGE + language, HOST + host, "--", *argv]


def parse(args: Sequence[str]) -> Request | None:
    """The arguments after FLAG; None for anything CapyPanel wouldn't have written."""
    host, language, attach = "", i18n.DEFAULT_LANGUAGE, False
    rest = list(args)
    while rest and rest[0] != "--":
        arg = rest.pop(0)
        if arg == ATTACH:
            attach = True
        elif arg.startswith(LANGUAGE):
            language = arg.removeprefix(LANGUAGE)
        elif arg.startswith(HOST):
            host = arg.removeprefix(HOST)
        else:
            return None
    if len(rest) < 2:  # "--" and at least the program
        return None
    argv = rest[1:]
    return Request(argv=argv, host=host or argv[-1], language=language, attach=attach)


class Console(Protocol):
    """What the holder needs from Windows. The tests give it a pretend one."""

    def open(self, *, attach: bool) -> bool: ...
    def set_title(self, title: str) -> None: ...
    def let_ctrl_c_through(self) -> None: ...
    def run(self, argv: Sequence[str]) -> int: ...
    def write(self, text: str) -> None: ...
    def wait_for_key(self, grace: float) -> None: ...


def run(args: Sequence[str], console: Console | None = None) -> int:
    """The holder, from FLAG's arguments to its exit code."""
    request = parse(args)
    if request is None:
        return NOT_STARTED_BY_CAPYPANEL
    i18n.set_language(request.language)
    console = console if console is not None else WindowsConsole()
    if not console.open(attach=request.attach):
        return NO_CONSOLE  # nowhere to show anything
    console.set_title(request.argv[0])  # as ssh.exe's own window was titled
    console.let_ctrl_c_through()
    try:
        code = console.run(request.argv)
    except OSError as e:
        why = _("Couldn't start ssh.exe: {error}").format(error=e.strerror or e)
        _say_and_wait(console, why)
        return DONE
    if is_error(code):
        _say_and_wait(console, error_line(request.host, code))
    return DONE


def _say_and_wait(console: Console, line: str) -> None:
    """`line` under what ssh.exe printed, then waits for a key."""
    console.write(f"\r\n{line}\r\n{_('Press any key to close this window.')}\r\n")
    console.wait_for_key(KEY_GRACE)


# ---- Windows ----

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ATTACH_PARENT_PROCESS = 0xFFFFFFFF  # (DWORD)-1
_ALREADY_ATTACHED = 5  # ERROR_ACCESS_DENIED, from AttachConsole
_GENERIC_READ, _GENERIC_WRITE = 0x80000000, 0x40000000
_FILE_SHARE_READ, _FILE_SHARE_WRITE = 0x1, 0x2
_OPEN_EXISTING = 3
_INVALID_HANDLE = wt.HANDLE(-1).value
_STARTF_USESTDHANDLES = 0x100
_CREATE_SUSPENDED = 0x4
_EXTENDED_STARTUPINFO_PRESENT = 0x80000
_HANDLE_LIST = 0x20002  # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT_INFORMATION = 9
_INFINITE = 0xFFFFFFFF
_ENABLE_PROCESSED_INPUT = 0x1
_KEY_EVENT = 0x1
# Keys that make no character: pressing them (Alt+Tab to another window, for one) never closes
# the window.
_NOT_A_KEY_PRESS = frozenset({
    0x10, 0x11, 0x12, 0x14, 0x5B, 0x5C, 0x90, 0x91, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5,
})  # fmt: skip


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wt.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wt.BOOL),
    )


class _StartupInfo(ctypes.Structure):
    _fields_ = (
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
    )


class _StartupInfoEx(ctypes.Structure):
    _fields_ = (("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p))


class _ProcessInformation(ctypes.Structure):
    _fields_ = (
        ("hProcess", wt.HANDLE),
        ("hThread", wt.HANDLE),
        ("dwProcessId", wt.DWORD),
        ("dwThreadId", wt.DWORD),
    )


class _BasicLimits(ctypes.Structure):
    _fields_ = (
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wt.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wt.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wt.DWORD),
        ("SchedulingClass", wt.DWORD),
    )


class _ExtendedLimits(ctypes.Structure):
    _fields_ = (
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", ctypes.c_ulonglong * 6),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )


class _KeyEvent(ctypes.Structure):
    _fields_ = (
        ("bKeyDown", wt.BOOL),
        ("wRepeatCount", wt.WORD),
        ("wVirtualKeyCode", wt.WORD),
        ("wVirtualScanCode", wt.WORD),
        ("UnicodeChar", wt.WCHAR),
        ("dwControlKeyState", wt.DWORD),
    )


class _Event(ctypes.Union):
    _fields_ = (("KeyEvent", _KeyEvent), ("_size", ctypes.c_byte * 16))


class _InputRecord(ctypes.Structure):
    _fields_ = (("EventType", wt.WORD), ("Event", _Event))


_HandlerRoutine = ctypes.WINFUNCTYPE(wt.BOOL, wt.DWORD)
_P = ctypes.POINTER

_k32.FreeConsole.restype = wt.BOOL
_k32.AllocConsole.restype = wt.BOOL
_k32.AttachConsole.argtypes = (wt.DWORD,)
_k32.AttachConsole.restype = wt.BOOL
_k32.CreateFileW.argtypes = (
    wt.LPCWSTR, wt.DWORD, wt.DWORD, _P(_SecurityAttributes), wt.DWORD, wt.DWORD, wt.HANDLE
)  # fmt: skip
_k32.CreateFileW.restype = wt.HANDLE
_k32.SetConsoleTitleW.argtypes = (wt.LPCWSTR,)
_k32.SetConsoleTitleW.restype = wt.BOOL
_k32.SetConsoleCtrlHandler.argtypes = (ctypes.c_void_p, wt.BOOL)
_k32.SetConsoleCtrlHandler.restype = wt.BOOL
_k32.InitializeProcThreadAttributeList.argtypes = (
    ctypes.c_void_p, wt.DWORD, wt.DWORD, _P(ctypes.c_size_t)
)  # fmt: skip
_k32.InitializeProcThreadAttributeList.restype = wt.BOOL
_k32.UpdateProcThreadAttribute.argtypes = (
    ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
    ctypes.c_void_p, ctypes.c_void_p,
)  # fmt: skip
_k32.UpdateProcThreadAttribute.restype = wt.BOOL
_k32.DeleteProcThreadAttributeList.argtypes = (ctypes.c_void_p,)
_k32.DeleteProcThreadAttributeList.restype = None
_k32.CreateProcessW.argtypes = (
    wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD, ctypes.c_void_p,
    wt.LPCWSTR, ctypes.c_void_p, _P(_ProcessInformation),
)  # fmt: skip
_k32.CreateProcessW.restype = wt.BOOL
_k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wt.LPCWSTR)
_k32.CreateJobObjectW.restype = wt.HANDLE
_k32.SetInformationJobObject.argtypes = (wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD)
_k32.SetInformationJobObject.restype = wt.BOOL
_k32.AssignProcessToJobObject.argtypes = (wt.HANDLE, wt.HANDLE)
_k32.AssignProcessToJobObject.restype = wt.BOOL
_k32.ResumeThread.argtypes = (wt.HANDLE,)
_k32.ResumeThread.restype = wt.DWORD
_k32.TerminateProcess.argtypes = (wt.HANDLE, wt.UINT)
_k32.TerminateProcess.restype = wt.BOOL
_k32.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.GetExitCodeProcess.argtypes = (wt.HANDLE, _P(wt.DWORD))
_k32.GetExitCodeProcess.restype = wt.BOOL
_k32.CloseHandle.argtypes = (wt.HANDLE,)
_k32.CloseHandle.restype = wt.BOOL
_k32.WriteConsoleW.argtypes = (wt.HANDLE, wt.LPCWSTR, wt.DWORD, _P(wt.DWORD), ctypes.c_void_p)
_k32.WriteConsoleW.restype = wt.BOOL
_k32.FlushConsoleInputBuffer.argtypes = (wt.HANDLE,)
_k32.FlushConsoleInputBuffer.restype = wt.BOOL
_k32.GetConsoleMode.argtypes = (wt.HANDLE, _P(wt.DWORD))
_k32.GetConsoleMode.restype = wt.BOOL
_k32.SetConsoleMode.argtypes = (wt.HANDLE, wt.DWORD)
_k32.SetConsoleMode.restype = wt.BOOL
_k32.ReadConsoleInputW.argtypes = (wt.HANDLE, _P(_InputRecord), wt.DWORD, _P(wt.DWORD))
_k32.ReadConsoleInputW.restype = wt.BOOL


def _failed() -> OSError:
    return ctypes.WinError(ctypes.get_last_error())


class WindowsConsole:
    """The holder's console, ssh.exe in it, and the key at the end."""

    def __init__(self) -> None:
        self._in: int | None = None
        self._out: int | None = None
        self._job: int | None = None  # kept open while the holder runs: ssh.exe ends with it
        self._handler: object = None  # kept: Windows calls it

    def open(self, *, attach: bool) -> bool:
        if attach:
            attached = _k32.AttachConsole(_ATTACH_PARENT_PROCESS)
            if not attached and ctypes.get_last_error() != _ALREADY_ATTACHED:
                return False
        else:
            _k32.FreeConsole()  # whatever console it was started with: from source, a parent's
            if not _k32.AllocConsole():
                return False
        self._in, self._out = self._open_file("CONIN$"), self._open_file("CONOUT$")
        return self._in is not None and self._out is not None

    @staticmethod
    def _open_file(name: str) -> int | None:
        """The console's input or screen, as a handle ssh.exe may inherit (and no other)."""
        inherit = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
        handle = _k32.CreateFileW(
            name,
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE,
            ctypes.byref(inherit),
            _OPEN_EXISTING,
            0,
            None,
        )
        return None if handle in (None, _INVALID_HANDLE) else handle

    def set_title(self, title: str) -> None:
        _k32.SetConsoleTitleW(title)

    def let_ctrl_c_through(self) -> None:
        _k32.SetConsoleCtrlHandler(None, False)  # an "ignore Ctrl+C" it was started with
        handler = _HandlerRoutine(lambda _event: True)
        self._handler = handler
        _k32.SetConsoleCtrlHandler(ctypes.cast(handler, ctypes.c_void_p), True)

    def run(self, argv: Sequence[str]) -> int:
        """`argv` in this console, suspended until it's in the job; its exit code."""
        handles = (wt.HANDLE * 2)(self._in, self._out)
        size = ctypes.c_size_t()
        _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attrs = ctypes.create_string_buffer(size.value)
        if not _k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)):
            raise _failed()
        try:
            if not _k32.UpdateProcThreadAttribute(
                attrs, 0, _HANDLE_LIST, handles, ctypes.sizeof(handles), None, None
            ):
                raise _failed()
            info = _StartupInfoEx()
            info.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
            info.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            info.StartupInfo.hStdInput = self._in
            info.StartupInfo.hStdOutput = info.StartupInfo.hStdError = self._out
            info.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
            process = _ProcessInformation()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
            flags = _CREATE_SUSPENDED | _EXTENDED_STARTUPINFO_PRESENT
            if not _k32.CreateProcessW(
                argv[0], command, None, None, True, flags, None, None, ctypes.byref(info),
                ctypes.byref(process),
            ):  # fmt: skip
                raise _failed()
        finally:
            _k32.DeleteProcThreadAttributeList(attrs)
        try:
            self._into_job(process.hProcess)
        except OSError:
            _k32.TerminateProcess(process.hProcess, 1)  # still suspended: it never ran
            _k32.CloseHandle(process.hThread)
            _k32.CloseHandle(process.hProcess)
            raise
        _k32.ResumeThread(process.hThread)
        _k32.CloseHandle(process.hThread)
        _k32.WaitForSingleObject(process.hProcess, _INFINITE)
        code = wt.DWORD()
        _k32.GetExitCodeProcess(process.hProcess, ctypes.byref(code))
        _k32.CloseHandle(process.hProcess)
        return code.value

    def _into_job(self, process: int) -> None:
        job = _k32.CreateJobObjectW(None, None)
        if not job:
            raise _failed()
        self._job = job
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not (
            _k32.SetInformationJobObject(
                job, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)
            )
            and _k32.AssignProcessToJobObject(job, process)
        ):
            raise _failed()

    def write(self, text: str) -> None:
        buffer = ctypes.create_unicode_buffer(text)
        written = wt.DWORD()
        _k32.WriteConsoleW(self._out, buffer, len(buffer) - 1, ctypes.byref(written), None)

    def wait_for_key(self, grace: float) -> None:
        """Until a key is pressed, `grace` seconds on: keys pressed before then are dropped.
        Shift, Ctrl, Alt, Windows and the lock keys alone don't count, and Ctrl+C counts as a
        key here."""
        time.sleep(grace)
        _k32.FlushConsoleInputBuffer(self._in)
        mode = wt.DWORD()
        if _k32.GetConsoleMode(self._in, ctypes.byref(mode)):
            _k32.SetConsoleMode(self._in, mode.value & ~_ENABLE_PROCESSED_INPUT)
        record, read = _InputRecord(), wt.DWORD()
        while _k32.ReadConsoleInputW(self._in, ctypes.byref(record), 1, ctypes.byref(read)):
            key = record.Event.KeyEvent
            if (
                record.EventType == _KEY_EVENT
                and key.bKeyDown
                and key.wVirtualKeyCode not in _NOT_A_KEY_PRESS
            ):
                return
