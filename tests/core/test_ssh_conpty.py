"""One program on a pseudo console (core/ssh/conpty.py), from each engine: output, keys, Ctrl+C,
closing and a flood, with Windows' own cmd.exe and timeout.exe; nothing reaches the network."""

import ctypes
import json
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator
from ctypes import wintypes as wt
from dataclasses import replace
from pathlib import Path

import pytest
from console_cells import CONSOLE_CELLS

from capypanel.core.ssh import conpty
from capypanel.core.ssh.conpty import Engine, PseudoConsole
from capypanel.core.ssh.screen import TermScreen, TermStream

SYSTEM32 = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32"
CMD = str(SYSTEM32 / "cmd.exe")
CMD_ENV = {**os.environ, "PROMPT": "$P$G"}  # each prompt line ends with ">"
# Windows' own timeout.exe by its whole path: one earlier on PATH (Git's) refuses /t and ends
WAIT_A_MINUTE = f'"{SYSTEM32 / "timeout.exe"}" /t 60 /nobreak\r'.encode()
VERSION = re.compile(r"Windows.*\d+\.\d+\.\d+")  # what ver prints, in any language
CELLS_CHILD = Path(__file__).resolve().parent.parent / "helpers" / "console_cells.py"
FLAGS = ["\U0001f1e7", "\U0001f1e7\U0001f1f7\U0001f1e7", "x\U0001f1e7y"]  # halves of flags


def _carried() -> Engine:
    engine = conpty.carried_engine()
    assert engine is not None  # vendor/conpty comes with CapyPanel
    return engine


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


@pytest.fixture(params=["Windows' own", "carried"])
def engine(request: pytest.FixtureRequest) -> Engine:
    return _carried() if request.param == "carried" else conpty.WINDOWS


@pytest.fixture
def runs(engine: Engine) -> Iterator[Callable[..., Run]]:
    """Starts programs on the engine and closes every one at the end, whatever the test found."""
    started: list[Run] = []

    def start(argv: list[str], **kw) -> Run:
        run = Run(argv, engine=engine, **kw)
        started.append(run)
        assert run.console.engine is engine  # it started: nothing took over
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
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    run.console.write(WAIT_A_MINUTE)
    assert run.until(lambda: bool(_children(run.console.pid, "timeout.exe")))
    time.sleep(0.3)  # timeout reads its arguments and starts counting
    assert _children(run.console.pid, "timeout.exe")  # it counts: nothing stopped it yet
    run.console.write(b"\x03")
    assert run.until(
        lambda: not _children(run.console.pid, "timeout.exe") and run.prompts() == 1, seconds=10
    )
    assert run.console.running


def test_closing_ends_the_program_and_everything_it_started(
    runs: Callable[..., Run], engine: Engine
) -> None:
    hosts_before = set(_children(os.getpid(), "openconsole.exe"))
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    run.console.write(WAIT_A_MINUTE)
    assert run.until(lambda: bool(_children(run.console.pid, "timeout.exe")))
    hosts = [p for p in _children(os.getpid(), "openconsole.exe") if p not in hosts_before]
    assert len(hosts) == (0 if engine is conpty.WINDOWS else 1)
    started = [run.console.pid, *_children(run.console.pid, "timeout.exe"), *hosts]
    run.console.close()
    end = time.monotonic() + 5
    while any(map(_alive, started)) and time.monotonic() < end:
        time.sleep(0.05)
    assert not any(map(_alive, started))
    assert run.console.exit_code is not None


def test_a_flood_waits_for_its_reader(runs: Callable[..., Run]) -> None:
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


def test_a_resize_reaches_the_program(runs: Callable[..., Run]) -> None:
    run = runs([CMD, "/d"], env=CMD_ENV)
    assert run.until(lambda: run.prompts() == 1)
    run.console.resize(70, 20)
    run.screen.resize(20, 70)
    size = f'"{sys.executable}" -I -c "import os; print(*os.get_terminal_size())"\r'
    run.console.write(size.encode())
    assert run.until(lambda: "70 20" in run.lines())


def test_the_carried_engine_takes_ctrl_c_as_key_events() -> None:
    ctrl_c = b"\x1b[17;29;0;1;8;1_\x1b[67;46;3;1;8;1_\x1b[67;46;3;0;8;1_\x1b[17;29;0;0;0;1_"
    run = Run([CMD, "/d"], env=CMD_ENV, engine=_carried())
    try:
        assert run.until(lambda: run.prompts() == 1)
        assert run.screen.win32_input
        run.console.write(WAIT_A_MINUTE)
        assert run.until(lambda: bool(_children(run.console.pid, "timeout.exe")))
        time.sleep(0.3)  # timeout reads its arguments and starts counting
        run.console.write(ctrl_c)
        assert run.until(
            lambda: not _children(run.console.pid, "timeout.exe") and run.prompts() == 1,
            seconds=10,
        )
    finally:
        run.console.close()


def test_windows_before_11_gets_the_carried_engine_and_windows_11_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conpty, "_windows_build", lambda: 19045)  # Windows 10 22H2, the test VM
    assert conpty.default_engine() is _carried()
    monkeypatch.setattr(conpty, "_windows_build", lambda: 22000)
    assert conpty.default_engine() is conpty.WINDOWS


def test_a_carried_engine_left_out_or_broken_leaves_windows_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(conpty, "_windows_build", lambda: 19045)
    monkeypatch.setattr(conpty, "CARRIED_DIR", tmp_path)  # empty: a build that left it out
    monkeypatch.setattr(conpty, "_carried", [])
    with caplog.at_level(logging.WARNING, logger=conpty.__name__):
        assert conpty.default_engine() is conpty.WINDOWS
        (tmp_path / "OpenConsole.exe").write_bytes(b"")
        (tmp_path / "conpty.dll").write_bytes(b"not a library")
        monkeypatch.setattr(conpty, "_carried", [])
        assert conpty.default_engine() is conpty.WINDOWS
    assert "is missing from" in caplog.text and "won't load" in caplog.text


def test_an_engine_that_wont_start_hands_over_to_windows_own(
    caplog: pytest.LogCaptureFixture,
) -> None:
    e_fail = -0x7FFFBFFB  # 0x80004005 as the signed number ctypes returns
    broken = replace(_carried(), name="a broken engine", create=lambda *_args: e_fail)
    with caplog.at_level(logging.INFO, logger=conpty.__name__):
        run = Run([CMD, "/d", "/c", "exit 5"], engine=broken)
    try:
        assert run.console.engine is conpty.WINDOWS
        assert run.until(run.ended.is_set)
        assert run.console.exit_code == 5
    finally:
        run.console.close()
    assert "a broken engine didn't start (0x80004005)" in caplog.text
    assert "Pseudo console from Windows' own engine" in caplog.text


def test_the_carried_engine_counts_cells_as_the_screen_does_on_it(tmp_path: Path) -> None:
    carried = _carried()
    samples = [sample for sample, _cells in CONSOLE_CELLS] + FLAGS
    (tmp_path / "samples.json").write_text(json.dumps(samples), encoding="utf-8")
    answer = tmp_path / "cells.json"
    argv = [sys.executable, "-I", str(CELLS_CHILD), str(tmp_path / "samples.json"), str(answer)]
    run = Run(argv, columns=120, engine=carried)
    try:
        assert run.until(run.ended.is_set, seconds=30)
        assert run.console.exit_code == 0
    finally:
        run.console.close()
    measured = json.loads(answer.read_text(encoding="utf-8"))
    on_screen = []
    for sample in samples:
        screen = TermScreen(40, 3)
        screen.regional_indicator_cells = carried.regional_indicator_cells
        TermStream(screen).feed(sample.encode())
        on_screen.append(screen.cursor.x)
    assert on_screen == measured
    flag = samples.index("\U0001f1e7\U0001f1f7")
    assert measured[flag] == 2 and dict(CONSOLE_CELLS)[samples[flag]] == 4  # 4 on Windows' own


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


def _children(pid: int, name: str) -> list[int]:
    """The programs called `name` (in lower case) that `pid` started."""
    snapshot = _k32.CreateToolhelp32Snapshot(_SNAPPROCESS, 0)
    found = []
    try:
        entry = _Entry()
        entry.dwSize = ctypes.sizeof(_Entry)
        more = _k32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == pid and entry.szExeFile.lower() == name:
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
