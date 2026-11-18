"""One program on a pseudo console (core/ssh/conpty.py): what it prints comes back, typed keys
reach it, Ctrl+C stops what it runs, closing ends it and everything it started, and a flood
waits for the reader. Windows' own cmd.exe and timeout.exe only, cmd started with /d (no
AutoRun) and the standard prompt; nothing reaches the network."""

import ctypes
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from ctypes import wintypes as wt
from pathlib import Path

import pytest

from capypanel.core.ssh.conpty import PseudoConsole
from capypanel.core.ssh.screen import TermScreen, TermStream

CMD = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "cmd.exe")
CMD_ENV = {**os.environ, "PROMPT": "$P$G"}  # each prompt line ends with ">"
VERSION = re.compile(r"Windows.*\d+\.\d+\.\d+")  # what ver prints, in any language


class Run:
    """One program on a pseudo console, its output drawn on a screen on the test's thread."""

    def __init__(self, argv: list[str], *, columns: int = 100, rows: int = 30, **kw) -> None:
        self.ended = threading.Event()
        self.screen = TermScreen(columns, rows)
        self.stream = TermStream(self.screen)
        self.console = PseudoConsole(
            argv, columns, rows, on_ready=lambda: None, on_exit=lambda _c: self.ended.set(), **kw
        )

    def pump(self) -> int:
        data = self.console.take(1 << 20)
        if data:
            self.stream.feed(data)
        return len(data)

    def until(self, test: Callable[[], bool], seconds: float = 15.0) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.pump()
            if test():
                return True
            time.sleep(0.02)
        self.pump()
        return test()

    def lines(self) -> list[str]:
        return [line for line in self.screen.scrollback_text() + self.screen.screen_text() if line]

    def prompts(self) -> int:
        return sum(1 for line in self.lines() if line.endswith(">"))


@pytest.fixture
def runs() -> Iterator[Callable[..., Run]]:
    """Starts programs and closes every one at the end, whatever the test found."""
    started: list[Run] = []

    def start(argv: list[str], **kw) -> Run:
        run = Run(argv, **kw)
        started.append(run)
        return run

    yield start
    for run in started:
        run.console.close()


def test_typed_keys_reach_cmd_and_its_answer_comes_back(runs: Callable[..., Run]) -> None:
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    before = len(run.lines())  # the banner holds a version too
    run.console.write(b"ver\r")
    assert run.until(lambda: any(VERSION.search(line) for line in run.lines()[before:]))
    run.console.write(b"exit\r")
    assert run.until(run.ended.is_set)
    assert run.console.exit_code == 0


@pytest.mark.parametrize("code", [0, 130, 255])
def test_the_programs_exit_code_comes_through(runs: Callable[..., Run], code: int) -> None:
    run = runs([CMD, "/d", "/c", f"exit {code}"])
    assert run.until(run.ended.is_set)
    assert run.console.exit_code == code


def test_ctrl_c_stops_what_cmd_runs_and_cmd_carries_on(runs: Callable[..., Run]) -> None:
    """An "ignore Ctrl+C" flag inherited from whatever started the tests would keep Ctrl+C from
    stopping the program: the pseudo console clears it first."""
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    run.console.write(b"timeout /t 60 /nobreak\r")
    assert run.until(lambda: bool(_children(run.console.pid)))
    time.sleep(0.3)  # timeout reads its arguments and starts counting
    run.console.write(b"\x03")
    assert run.until(lambda: not _children(run.console.pid) and run.prompts() == 1, seconds=10)
    assert run.console.running


def test_closing_ends_the_program_and_everything_it_started(runs: Callable[..., Run]) -> None:
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    run.console.write(b"timeout /t 60 /nobreak\r")
    assert run.until(lambda: bool(_children(run.console.pid)))
    started = [run.console.pid, *_children(run.console.pid)]
    run.console.close()
    end = time.monotonic() + 5
    while any(map(_alive, started)) and time.monotonic() < end:
        time.sleep(0.05)
    assert not any(map(_alive, started))
    assert run.console.exit_code is not None


def test_a_flood_waits_for_its_reader(runs: Callable[..., Run]) -> None:
    """While nothing is taken the reader stops at its bound, so cmd waits instead of filling
    memory; then every line comes through, in order. The pseudo console keeps its output open
    after the program ends, until it is closed: closing it is what brings the end of it."""
    bound, one_read = 16_384, 65_536  # the reader may hold one read past its bound
    flood = "for /L %i in (1,1,20000) do @echo line %i"  # about 250 KB
    run = runs([CMD, "/d", "/c", flood], max_pending=bound)
    end = time.monotonic() + 15
    while run.console.pending < bound and time.monotonic() < end:
        time.sleep(0.05)
    time.sleep(0.5)  # time for anything the bound would let through
    assert bound <= run.console.pending <= bound + one_read
    assert not run.ended.is_set()  # cmd waits for the reader
    assert run.until(run.ended.is_set, seconds=60)
    run.console.close()
    assert run.until(lambda: run.console.at_eof, seconds=10)
    numbers = [int(line[5:]) for line in run.lines() if line.startswith("line ")]
    assert numbers[-1] == 20000
    assert numbers == list(range(numbers[0], 20001))


# ---- Windows' list of processes ----

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_SNAPPROCESS, _SYNCHRONIZE, _TIMEOUT = 0x2, 0x00100000, 0x102


class _Entry(ctypes.Structure):
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


_k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
_k32.Process32FirstW.argtypes = (wt.HANDLE, ctypes.POINTER(_Entry))
_k32.Process32NextW.argtypes = (wt.HANDLE, ctypes.POINTER(_Entry))
_k32.OpenProcess.restype = wt.HANDLE
_k32.WaitForSingleObject.argtypes = (wt.HANDLE, wt.DWORD)
_k32.CloseHandle.argtypes = (wt.HANDLE,)


def _children(pid: int) -> list[int]:
    snapshot = _k32.CreateToolhelp32Snapshot(_SNAPPROCESS, 0)
    found = []
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        more = _k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == pid and entry.szExeFile.lower() == "timeout.exe":
                found.append(int(entry.th32ProcessID))
            more = _k32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snapshot)
    return found


def _alive(pid: int) -> bool:
    handle = _k32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not handle:
        return False  # gone (its number may be reused later, never this soon)
    try:
        return _k32.WaitForSingleObject(handle, 0) == _TIMEOUT
    finally:
        _k32.CloseHandle(handle)
