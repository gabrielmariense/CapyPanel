import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from ctypes import wintypes as wt
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fake_console import FakeConsole
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QColor, QGuiApplication, QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from test_themes import ACCENTS

from capypanel.core.ssh import conpty
from capypanel.core.ssh.screen import TermScreen, TermStream
from capypanel.ui import error_window, help_links, menus
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.shortcuts import EVERYWHERE, KeyCommand, Keys
from capypanel.ui.ssh_tool.terminal import glyphs, keys, palette
from capypanel.ui.ssh_tool.terminal import tab as tab_module
from capypanel.ui.ssh_tool.terminal import view as view_module
from capypanel.ui.ssh_tool.terminal.tab import EndedBar, TerminalTab
from capypanel.ui.ssh_tool.terminal.view import MAX_PT, PasteQuestion, TerminalView
from capypanel.ui.themes import engine as themes

CMD = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "cmd.exe")
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
KEYPAD = Qt.KeyboardModifier.KeypadModifier
NONE = Qt.KeyboardModifier.NoModifier
K = Qt.Key
MARKER = "capy7731"  # typed, pasted and printed: it must never reach a log


def _key(
    key: Qt.Key,
    vk: int,
    sc: int,
    *,
    native: int = 0,
    text: str = "",
    mods: Qt.KeyboardModifier = NONE,
    press: bool = True,
    repeat: bool = False,
) -> QKeyEvent:
    """As Qt gives it on Windows: virtual key, scan code and Windows' own modifiers."""
    kind = QEvent.Type.KeyPress if press else QEvent.Type.KeyRelease
    return QKeyEvent(kind, key, mods, sc, vk, native, text, repeat)


def _ctrl_c() -> QKeyEvent:
    return _key(K.Key_C, 0x43, 0x2E, native=keys.Q_CTRL_L, text="\x03", mods=CTRL)


def _until(test: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not test():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def _shown(widget: QWidget) -> None:
    """Shown, so it has its size, but never on the screen."""
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.resize(800, 400)
    widget.show()


def test_a_key_goes_to_the_server_down_and_up_as_a_windows_key_event() -> None:
    down = _key(K.Key_A, 0x41, 0x1E, text="a")
    up = _key(K.Key_A, 0x41, 0x1E, text="a", press=False)
    assert keys.encode(down, True) == b"\x1b[65;30;97;1;0;1_"
    assert keys.encode(up, False) == b"\x1b[65;30;97;0;0;1_"
    # No text, and Windows' extended bit: the console picks Up's bytes by the program's modes.
    arrow = _key(K.Key_Up, 0x26, 0x48, native=keys.Q_EXTENDED)
    assert keys.encode(arrow, True) == b"\x1b[38;72;0;1;256;1_"
    shifted = _key(K.Key_A, 0x41, 0x1E, text="A", mods=SHIFT)
    assert keys.encode(shifted, True) == b"\x1b[65;30;65;1;16;1_"


def test_altgr_text_loses_ctrl_and_alt_and_alt_alone_keeps_its_bit() -> None:
    altgr = keys.Q_CTRL_L | keys.Q_ALT_R
    slash = _key(K.Key_Q, 0x51, 0x10, native=altgr, text="/", mods=CTRL | ALT)
    assert keys.encode(slash, True) == b"\x1b[81;16;47;1;0;1_"
    alt_b = _key(K.Key_B, 0x42, 0x30, native=keys.Q_ALT_L, text="b", mods=ALT)
    assert keys.encode(alt_b, True) == b"\x1b[66;48;98;1;2;1_"
    assert keys.encode(_ctrl_c(), True) == b"\x1b[67;46;3;1;8;1_"
    right_ctrl = _key(
        K.Key_C, 0x43, 0x2E, native=keys.Q_CTRL_R | keys.Q_EXTENDED, text="\x03", mods=CTRL
    )
    assert keys.encode(right_ctrl, True) == b"\x1b[67;46;3;1;260;1_"


def test_a_dead_key_sends_nothing_and_the_key_after_it_brings_the_letter() -> None:
    tilde = _key(K.Key_Dead_Tilde, 0xDE, 0x28)
    assert keys.encode(tilde, True) == b""
    assert keys.encode(_key(K.Key_Dead_Tilde, 0xDE, 0x28, press=False), False) == b""
    a_tilde = _key(K.Key_A, 0x41, 0x1E, text="ã")
    assert keys.encode(a_tilde, True) == b"\x1b[65;30;227;1;0;1_"


def test_text_a_key_event_has_no_room_for_goes_as_text() -> None:
    emoji = _key(K.Key_unknown, 0, 0, text="\U0001f600")
    assert keys.encode(emoji, True) == "\U0001f600".encode()
    assert keys.encode(emoji, False) == b""
    several = _key(K.Key_unknown, 0, 0, text="a\U0001f600")
    assert keys.encode(several, True) == "a\U0001f600".encode()
    assert keys.encode(_key(K.Key_unknown, 0, 0), True) == b""


def test_without_key_events_a_key_goes_as_its_text() -> None:
    text = keys.encode_text
    assert text(_key(K.Key_Y, 0x59, 0x15, text="y")) == b"y"
    assert text(_key(K.Key_A, 0x41, 0x1E, text="ã")) == "ã".encode()
    assert text(_key(K.Key_Dead_Tilde, 0xDE, 0x28)) == b""
    assert text(_key(K.Key_unknown, 0, 0, text="\U0001f600")) == "\U0001f600".encode()
    assert text(_key(K.Key_Return, 0x0D, 0x1C, text="\r")) == b"\r"
    assert text(_key(K.Key_Enter, 0x0D, 0x1C, text="\r", mods=KEYPAD)) == b"\r"
    assert text(_key(K.Key_Backspace, 0x08, 0x0E, text="\b")) == b"\x7f"
    ctrl_back = _key(K.Key_Backspace, 0x08, 0x0E, native=keys.Q_CTRL_L, text="\x7f", mods=CTRL)
    assert text(ctrl_back) == b"\x08"
    assert text(_key(K.Key_Tab, 0x09, 0x0F, text="\t")) == b"\t"
    assert text(_key(K.Key_Backtab, 0x09, 0x0F, native=keys.Q_SHIFT_L, mods=SHIFT)) == b"\x1b[Z"
    assert text(_key(K.Key_Escape, 0x1B, 0x01, text="\x1b")) == b"\x1b"
    assert text(_ctrl_c()) == b"\x03"
    assert text(_key(K.Key_C, 0x43, 0x2E, native=keys.Q_CTRL_L, mods=CTRL)) == b"\x03"
    ctrl_space = _key(K.Key_Space, 0x20, 0x39, native=keys.Q_CTRL_L, text=" ", mods=CTRL)
    assert text(ctrl_space) == b"\x00"
    alt_b = _key(K.Key_B, 0x42, 0x30, native=keys.Q_ALT_L, text="b", mods=ALT)
    assert text(alt_b) == b"\x1bb"
    altgr = keys.Q_CTRL_L | keys.Q_ALT_R
    assert text(_key(K.Key_Q, 0x51, 0x10, native=altgr, text="/", mods=CTRL | ALT)) == b"/"
    assert text(_key(K.Key_Shift, 0x10, 0x2A, native=keys.Q_SHIFT_L, mods=SHIFT)) == b""


def test_without_key_events_a_key_with_no_text_goes_as_xterm_s_sequence() -> None:
    up = _key(K.Key_Up, 0x26, 0x48, native=keys.Q_EXTENDED)
    assert keys.encode_text(up) == b"\x1b[A"
    assert keys.encode_text(up, app_cursor=True) == b"\x1bOA"  # after the program's ESC[?1h
    ctrl = keys.Q_EXTENDED | keys.Q_CTRL_L
    ctrl_left = _key(K.Key_Left, 0x25, 0x4B, native=ctrl, mods=CTRL)
    assert keys.encode_text(ctrl_left, app_cursor=True) == b"\x1b[1;5D"
    assert keys.encode_text(_key(K.Key_Home, 0x24, 0x47, native=keys.Q_EXTENDED)) == b"\x1b[H"
    delete = _key(K.Key_Delete, 0x2E, 0x53, native=keys.Q_EXTENDED, text="\x7f")
    assert keys.encode_text(delete) == b"\x1b[3~"  # the key, not the DEL Qt gives it as text
    assert keys.encode_text(_key(K.Key_PageDown, 0x22, 0x51)) == b"\x1b[6~"
    assert keys.encode_text(_key(K.Key_F1, 0x70, 0x3B)) == b"\x1bOP"
    assert keys.encode_text(_key(K.Key_F5, 0x74, 0x3F)) == b"\x1b[15~"
    shift_f5 = _key(K.Key_F5, 0x74, 0x3F, native=keys.Q_SHIFT_L, mods=SHIFT)
    assert keys.encode_text(shift_f5) == b"\x1b[15;2~"
    alt_f1 = _key(K.Key_F1, 0x70, 0x3B, native=keys.Q_ALT_L, mods=ALT)
    assert keys.encode_text(alt_f1) == b"\x1b[1;3P"


TODAY = {
    "app.settings": "Ctrl+,",
    "app.exit": "Ctrl+Q",
    "go.home": "Ctrl+0",
    "go.hosts": "Ctrl+1",
    "go.printers": "Ctrl+2",
    "go.profiles": "Ctrl+3",
    "go.ssh": "Ctrl+4",
}


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.keys = Keys({}, lambda: None)
        self.keys.load([KeyCommand(i, QAction(self), EVERYWHERE, key) for i, key in TODAY.items()])


@pytest.fixture
def consoles(monkeypatch: pytest.MonkeyPatch) -> list[FakeConsole]:
    made: list[FakeConsole] = []

    def start(*args: Any, **kwargs: Any) -> FakeConsole:
        made.append(FakeConsole(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(view_module, "PseudoConsole", start)
    return made


@pytest.fixture
def view(qapp: QApplication, consoles: list[FakeConsole]) -> Iterator[TerminalView]:
    window = _Window()
    terminal = TerminalView(host="web-01", parent=window)
    QVBoxLayout(window).addWidget(terminal)
    _shown(window)
    yield terminal
    terminal.close_connection()


def _asks_for_key_events(view: TerminalView, console: FakeConsole) -> None:
    """As Windows 11's console does first thing; Windows 10's never asks."""
    console.prints(b"\x1b[?9001h\x1b[?1004h")
    _until(lambda: view.term.win32_input)


@pytest.mark.parametrize(
    ("key", "mods", "leaves", "ours"),
    [
        (K.Key_Tab, CTRL, True, False),
        (K.Key_Backtab, CTRL | SHIFT, True, False),
        (K.Key_W, CTRL | SHIFT, True, False),
        (K.Key_1, CTRL, True, False),
        (K.Key_0, CTRL, True, False),
        (K.Key_Comma, CTRL, True, False),
        (K.Key_9, CTRL, False, False),
        (K.Key_Q, CTRL, False, False),
        (K.Key_W, CTRL, False, False),
        (K.Key_C, CTRL, False, False),
        (K.Key_V, CTRL, False, False),
        (K.Key_2, CTRL | ALT, False, False),  # AltGr+2: ² on ABNT2
        (K.Key_Tab, NONE, False, False),
        (K.Key_F1, NONE, False, False),
        (K.Key_Escape, NONE, False, False),
        (K.Key_C, CTRL | SHIFT, False, True),
        (K.Key_V, CTRL | SHIFT, False, True),
        (K.Key_Equal, CTRL, False, True),
        (K.Key_Plus, CTRL | SHIFT, False, True),
        (K.Key_Minus, CTRL, False, True),
        (K.Key_Plus, CTRL | ALT, False, False),
        (K.Key_Equal, CTRL | ALT, False, False),  # AltGr+=: § on ABNT2
    ],
)
def test_the_window_s_keys_leave_the_terminal_and_its_own_stay(
    view: TerminalView, key: Qt.Key, mods: Qt.KeyboardModifier, leaves: bool, ours: bool
) -> None:
    press = QKeyEvent(QEvent.Type.KeyPress, key, mods)
    assert view.leaves(press) is leaves
    assert TerminalView.is_ours(press) is ours


def test_a_key_someone_gave_a_tool_leaves_the_terminal_and_its_old_key_stays(
    view: TerminalView,
) -> None:
    window = view.window()
    assert isinstance(window, _Window)
    window.keys.set(window.keys.row("go.hosts"), "Alt+H")
    assert view.leaves(QKeyEvent(QEvent.Type.KeyPress, K.Key_H, ALT))
    assert not view.leaves(QKeyEvent(QEvent.Type.KeyPress, K.Key_1, CTRL))
    window.keys.set(window.keys.row("app.settings"), "")
    assert not view.leaves(QKeyEvent(QEvent.Type.KeyPress, K.Key_Comma, CTRL))


def _never_asked(_parent: QWidget, _lines: Sequence[str], _host: str) -> bool:
    raise AssertionError("asked before a paste that needs no question")


def test_every_key_but_the_tool_s_beats_the_app_s_shortcuts(view: TerminalView) -> None:
    for key, mods, kept in (
        (K.Key_W, CTRL, True),
        (K.Key_C, CTRL | SHIFT, True),
        (K.Key_Tab, CTRL, False),
        (K.Key_W, CTRL | SHIFT, False),
        (K.Key_4, CTRL, False),
    ):
        override = QKeyEvent(QEvent.Type.ShortcutOverride, key, mods)
        override.ignore()
        QApplication.sendEvent(view, override)
        assert override.isAccepted() is kept, (key, mods)


def test_a_key_s_release_follows_its_press_and_a_release_alone_sends_nothing(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    _asks_for_key_events(view, console)
    QApplication.sendEvent(view, _key(K.Key_B, 0x42, 0x30, text="b", press=False))
    assert console.written == []
    QApplication.sendEvent(view, _key(K.Key_A, 0x41, 0x1E, text="a"))
    QApplication.sendEvent(view, _key(K.Key_A, 0x41, 0x1E, text="a", repeat=True))
    QApplication.sendEvent(view, _key(K.Key_A, 0x41, 0x1E, text="a", press=False))
    down, up = b"\x1b[65;30;97;1;0;1_", b"\x1b[65;30;97;0;0;1_"
    assert console.written == [down, down, up]


def test_the_tool_s_keys_never_reach_the_program_and_tab_completes(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    _asks_for_key_events(view, console)
    for key, vk, mods, native in (
        (K.Key_Tab, 0x09, CTRL, keys.Q_CTRL_L),
        (K.Key_W, 0x57, CTRL | SHIFT, keys.Q_CTRL_L | keys.Q_SHIFT_L),
        (K.Key_3, 0x33, CTRL, keys.Q_CTRL_L),
    ):
        press = _key(key, vk, 0, native=native, mods=mods)
        QApplication.sendEvent(view, press)
        assert not press.isAccepted(), key
    assert console.written == []
    QApplication.sendEvent(view, _key(K.Key_Tab, 0x09, 0x0F, text="\t"))
    assert console.written == [b"\x1b[9;15;9;1;0;1_"]


def test_ctrl_c_copies_a_selection_and_the_next_one_reaches_the_program(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    _asks_for_key_events(view, console)
    console.prints(b"uptime: 3 days")
    _until(lambda: view.term.row_text(0) == "uptime: 3 days")
    view.select_cells((0, 0), (0, 5))
    QApplication.sendEvent(view, _ctrl_c())
    assert QGuiApplication.clipboard().text() == "uptime"
    assert console.written == []
    QApplication.sendEvent(view, _ctrl_c())
    assert console.written == [b"\x1b[67;46;3;1;8;1_"]


def test_ctrl_and_shift_going_down_first_keep_the_selection_for_the_copy(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    _asks_for_key_events(view, console)
    console.prints(b"selected 5521 ok")
    _until(lambda: view.term.row_text(0) == "selected 5521 ok")
    both = keys.Q_CTRL_L | keys.Q_SHIFT_L

    def ctrl() -> QKeyEvent:
        return _key(K.Key_Control, 0x11, 0x1D, native=keys.Q_CTRL_L, mods=CTRL)

    QGuiApplication.clipboard().clear()
    view.select_cells((0, 0), (0, 7))
    QApplication.sendEvent(view, ctrl())
    QApplication.sendEvent(view, _key(K.Key_Shift, 0x10, 0x2A, native=both, mods=CTRL | SHIFT))
    QApplication.sendEvent(view, _key(K.Key_C, 0x43, 0x2E, native=both, mods=CTRL | SHIFT))
    assert QGuiApplication.clipboard().text() == "selected"
    view.select_cells((0, 9), (0, 12))
    QApplication.sendEvent(view, ctrl())
    QApplication.sendEvent(view, _ctrl_c())
    assert QGuiApplication.clipboard().text() == "5521"
    assert [w.split(b";")[0] for w in console.written] == [b"\x1b[17", b"\x1b[16", b"\x1b[17"]


def test_ctrl_equals_and_ctrl_minus_change_the_text_size_and_send_nothing(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    picked: list[int] = []
    view.size_picked.connect(picked.append)
    size = view.point_size
    ctrl, ctrl_shift = keys.Q_CTRL_L, keys.Q_CTRL_L | keys.Q_SHIFT_L
    QApplication.sendEvent(view, _key(K.Key_Equal, 0xBB, 0x0D, native=ctrl, mods=CTRL))
    QApplication.sendEvent(view, _key(K.Key_Plus, 0xBB, 0x0D, native=ctrl_shift, mods=CTRL | SHIFT))
    QApplication.sendEvent(view, _key(K.Key_Minus, 0xBD, 0x0C, native=ctrl, mods=CTRL))
    assert picked == [size + 1, size + 2, size + 1]
    assert view.point_size == size + 1
    view.set_point_size(MAX_PT)
    QApplication.sendEvent(view, _key(K.Key_Equal, 0xBB, 0x0D, native=ctrl, mods=CTRL))
    assert view.point_size == MAX_PT and picked == [size + 1, size + 2, size + 1]
    assert console.written == []


def test_altgr_plus_types_its_tilde_and_leaves_the_text_size_alone(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    _asks_for_key_events(view, console)
    size = view.point_size
    altgr = keys.Q_CTRL_L | keys.Q_ALT_R
    QApplication.sendEvent(
        view, _key(K.Key_Plus, 0xBB, 0x1B, native=altgr, text="~", mods=CTRL | ALT)
    )
    assert view.point_size == size
    assert console.written == [b"\x1b[187;27;126;1;0;1_"]


def test_a_console_that_never_asks_for_key_events_gets_each_key_as_text(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    console.prints(b"Continue connecting (yes/no)? ")
    _until(lambda: "(yes/no)?" in view.term.row_text(0))
    typed = (
        (K.Key_Y, 0x59, 0x15, "y"),
        (K.Key_E, 0x45, 0x12, "e"),
        (K.Key_S, 0x53, 0x1F, "s"),
        (K.Key_Return, 0x0D, 0x1C, "\r"),
    )
    for key, vk, sc, ch in typed:
        QApplication.sendEvent(view, _key(key, vk, sc, text=ch))
        QApplication.sendEvent(view, _key(key, vk, sc, text=ch, press=False))
    QApplication.sendEvent(view, _ctrl_c())
    assert console.written == [b"y", b"e", b"s", b"\r", b"\x03"]


def test_keys_go_as_key_events_from_the_console_s_ask_on(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    QApplication.sendEvent(view, _key(K.Key_A, 0x41, 0x1E, text="a"))
    _asks_for_key_events(view, console)
    QApplication.sendEvent(view, _key(K.Key_A, 0x41, 0x1E, text="a"))
    assert console.written == [b"a", b"\x1b[65;30;97;1;0;1_"]


def test_a_paste_goes_in_brackets_when_the_program_asked_and_nothing_in_it_ends_them_early(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    console.prints(b"\x1b[?2004h$ ")
    _until(lambda: view.term.bracketed_paste)
    view.confirm_paste = _never_asked
    assert view.paste_text("echo one\necho \x1b[201~two\n")
    assert console.written == [b"\x1b[200~echo one\recho [201~two\r\x1b[201~"]


def test_without_brackets_text_with_a_line_break_asks_first(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    asked: list[tuple[list[str], str]] = []
    answers = deque([False, True])

    def answer(_parent: QWidget, lines: Sequence[str], host: str) -> bool:
        asked.append((list(lines), host))
        return answers.popleft()

    view.confirm_paste = answer
    assert not view.paste_text("ls\r\nrm notes.txt\n")
    assert console.written == []
    assert view.paste_text("ls\r\nrm notes.txt\n")
    assert console.written == [b"ls\rrm notes.txt\r"]
    assert view.paste_text("one line")
    assert console.written[-1] == b"one line"
    assert asked == [(["ls", "rm notes.txt"], "web-01")] * 2


def test_nothing_is_pasted_once_the_connection_has_ended(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    view.start(["ssh.exe"])
    console = consoles[-1]
    console.ends(0)
    _until(lambda: not view.running and console.closed)
    view.confirm_paste = _never_asked
    assert not view.paste_text("ls")
    assert console.written == []


def test_the_paste_question_shows_the_first_lines_and_cancel_is_the_default(
    qapp: QApplication,
) -> None:
    many = PasteQuestion(None, ["ls", "cd /srv", "rm notes.txt", "df -h", "exit"], "web-01")
    assert isinstance(many, Question)
    assert many.windowTitle() == "Paste"
    assert many.heading.text() == "<b>Paste 5 lines into web-01?</b>"
    assert many.text.text() == "Each line may run as a command."
    assert many.preview.toPlainText() == "ls\ncd /srv\nrm notes.txt"
    assert "…and 2 more lines" in [label.text() for label in many.findChildren(QLabel)]
    assert many.cancel.isDefault() and not many.action.isDefault()
    assert many.action.text() == "&Paste"
    one = PasteQuestion(None, ["ls"], "web-01")
    assert one.heading.text() == "<b>Paste 1 line into web-01?</b>"
    assert one.text.text() == "It may run as a command."
    assert not any("more line" in label.text() for label in one.findChildren(QLabel))
    assert one.preview.maximumHeight() < many.preview.maximumHeight()


def test_enter_on_an_ended_connection_connects_again(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    ended: list[object] = []
    started: list[bool] = []
    view.ended.connect(ended.append)
    view.started.connect(lambda: started.append(True))
    view.start(["ssh.exe", "--", "192.0.2.42"])
    first = consoles[-1]
    first.prints(b"Connection closed by remote host.\r\n")
    first.ends(255)
    _until(lambda: ended == [255])
    assert not view.running and view.exit_code == 255
    QApplication.sendEvent(view, _key(K.Key_Return, 0x0D, 0x1C, text="\r"))
    assert len(consoles) == 2 and consoles[-1].argv == first.argv
    assert view.running and started == [True, True]
    assert first.written == [] and consoles[-1].written == []


def test_a_connection_capypanel_closes_ends_grey_whichever_way_windows_reports_it(
    qapp: QApplication, consoles: list[FakeConsole]
) -> None:
    tab = TerminalTab(host="web-01")
    _shown(tab)
    tab.start(["ssh.exe"])
    console = consoles[-1]
    console.prints(b"$ ")
    tab.close_connection()
    _until(lambda: tab.ended)
    assert console.closed and not tab.running
    assert not tab.bar.error
    assert tab.bar.label.text() == "The connection to web-01 ended."


def test_reconnect_takes_the_strip_away_and_close_tab_asks_the_tool(
    qapp: QApplication, consoles: list[FakeConsole]
) -> None:
    tab = TerminalTab(host="web-01")
    _shown(tab)
    running: list[bool] = []
    closes: list[bool] = []
    tab.changed.connect(lambda: running.append(tab.running))
    tab.close_asked.connect(lambda: closes.append(True))
    tab.start(["ssh.exe"])
    consoles[-1].ends(0xC0000005)
    _until(lambda: tab.ended)
    assert tab.bar.error and "0xC0000005" in tab.bar.label.text()
    tab.bar.reconnect_button.click()
    assert not tab.ended and tab.running and len(consoles) == 2
    assert running == [True, False, True]
    consoles[-1].ends(0)
    _until(lambda: tab.ended)
    assert not tab.bar.error
    tab.bar.close_button.click()
    assert closes == [True]


def test_the_first_connection_hint_shows_while_ssh_exe_will_ask_and_each_start_checks_again(
    qapp: QApplication, consoles: list[FakeConsole]
) -> None:
    tab = TerminalTab(host="web-01")
    _shown(tab)
    checks: list[bool] = []
    known_now = threading.Event()

    def asks() -> bool:
        checks.append(True)
        if len(checks) < 3:
            return True
        known_now.wait(10)
        return False

    tab.asks_to_trust = asks
    tab.start(["ssh.exe"])
    _until(lambda: tab.hint.isVisible())
    assert tab.hint.label.text() == tab_module.trust_words()
    tab.hint.close_button.click()
    assert not tab.hint.isVisible() and tab.running
    consoles[-1].ends(255)
    _until(lambda: tab.ended)
    tab.bar.reconnect_button.click()
    _until(lambda: tab.hint.isVisible())
    consoles[-1].ends(0)
    _until(lambda: tab.ended)
    assert not tab.hint.isVisible()
    tab.bar.reconnect_button.click()
    check = tab._check
    assert check is not None
    answers: list[bool] = []
    check.answered.connect(lambda _number, asks: answers.append(asks))
    known_now.set()
    _until(lambda: answers == [False])
    QApplication.processEvents()
    assert not tab.hint.isVisible() and len(checks) == 3


def test_an_answer_that_comes_after_the_connection_ended_shows_no_hint(
    qapp: QApplication, consoles: list[FakeConsole]
) -> None:
    tab = TerminalTab(host="web-01")
    _shown(tab)
    go = threading.Event()
    tab.asks_to_trust = lambda: go.wait(10)
    tab.start(["ssh.exe"])
    check = tab._check
    assert check is not None
    answers: list[bool] = []
    check.answered.connect(lambda _number, asks: answers.append(asks))
    consoles[-1].ends(0)
    _until(lambda: tab.ended)
    go.set()
    _until(lambda: answers == [True])
    QApplication.processEvents()
    assert not tab.hint.isVisible() and tab.bar.isVisible()


def test_the_hint_s_icon_takes_the_accent_unless_it_wouldn_t_show_on_the_strip(
    qapp: QApplication, default_theme_after: None
) -> None:
    light = themes.Registry().find("capypanel-light")
    colors = light.colors
    for accent, drawn in (
        (colors["accent"], colors["accent"]),
        (colors["sel_solid"], colors["text"]),
    ):
        themes.apply(replace(light, colors={**colors, "accent": accent}))
        hint = tab_module.TrustHint()
        image = hint._icon.pixmap().toImage()
        pixels = (
            image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())
        )
        assert max(pixels, key=QColor.alpha).name() == drawn


BAD = b"\x1b[?5A"  # cursor up with "?": pyte's handler takes no such thing and raises


def test_a_server_s_bad_sequence_never_reaches_the_error_window_or_the_log(
    view: TerminalView,
    consoles: list[FakeConsole],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = TermStream(TermScreen(20, 2))
    stream.feed(BAD)
    assert stream.dropped == 1
    errors: list[object] = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: errors.append(a))
    monkeypatch.setattr(error_window, "report", lambda *a: errors.append(a))
    caplog.set_level(logging.DEBUG)
    view.start(["ssh.exe"])
    consoles[-1].prints(BAD + MARKER.encode() + b" after")
    _until(lambda: view.term.row_text(0) == f"{MARKER} after")
    view.grab()
    assert errors == []
    assert MARKER not in caplog.text


def test_a_flood_of_colours_and_characters_keeps_each_cache_within_its_limit(
    view: TerminalView, consoles: list[FakeConsole], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(view_module, "MAX_CACHED", 50)
    view.start(["ssh.exe"])
    last = chr(0x4E00 + 199)
    consoles[-1].prints(
        "".join(f"\x1b[38;2;{n};0;0;48;2;0;{n};0m{chr(0x4E00 + n)}" for n in range(200)).encode()
    )
    _until(lambda: any(last in row for row in view.term.screen_text()))
    view.grab()
    for cache in (view._colors, view._pairs, view._fit_cache):
        assert 0 < len(cache) <= 50


@pytest.mark.parametrize("key_events", [True, False], ids=["key events", "text"])
def test_typed_pasted_and_shown_text_never_reaches_the_log(
    view: TerminalView,
    consoles: list[FakeConsole],
    caplog: pytest.LogCaptureFixture,
    key_events: bool,
) -> None:
    caplog.set_level(logging.DEBUG)
    view.start(["ssh.exe"])
    console = consoles[-1]
    if key_events:
        _asks_for_key_events(view, console)
    for ch in MARKER:
        vk = ord(ch.upper())
        QApplication.sendEvent(view, _key(Qt.Key(vk), vk, 0, text=ch))
        QApplication.sendEvent(view, _key(Qt.Key(vk), vk, 0, text=ch, press=False))
    assert view.paste_text(MARKER)
    console.prints(MARKER.encode())
    _until(lambda: MARKER in view.term.row_text(0))
    view.grab()
    assert len(console.written) == (2 if key_events else 1) * len(MARKER) + 1
    assert MARKER not in caplog.text.casefold()
    assert all(isinstance(value, int | float) for value in view.stats.values())


_user32 = ctypes.WinDLL("user32")
_user32.VkKeyScanW.argtypes = (wt.WCHAR,)
_user32.VkKeyScanW.restype = ctypes.c_short
_user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT)
_user32.MapVirtualKeyW.restype = wt.UINT


def _typed(view: TerminalView, text: str) -> None:
    for ch in text:
        if ch == "\r":
            vk, shift, key = 0x0D, False, K.Key_Return
        else:
            scan = _user32.VkKeyScanW(ch)
            vk, shift, key = scan & 0xFF, bool(scan & 0x100), Qt.Key(ord(ch.upper()))
        sc = _user32.MapVirtualKeyW(vk, 0)
        native, mods = (keys.Q_SHIFT_L, SHIFT) if shift else (0, NONE)
        for press in (True, False):
            QApplication.sendEvent(
                view, _key(key, vk, sc, native=native, text=ch, mods=mods, press=press)
            )


def _all_rows(view: TerminalView) -> list[str]:
    return view.term.scrollback_text() + view.term.screen_text()


@pytest.fixture(params=["Windows' own", "carried"])
def cmd(
    qapp: QApplication, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TerminalView]:
    """cmd.exe on a real pseudo console: no AutoRun, and ">" for a prompt."""
    engine = conpty.carried_engine() if request.param == "carried" else conpty.WINDOWS
    assert engine is not None
    monkeypatch.setattr(conpty, "default_engine", lambda: engine)
    terminal = TerminalView(host="web-01")
    _shown(terminal)
    terminal.start([CMD, "/d"], env={**os.environ, "PROMPT": "$G"})
    _until(lambda: ">" in terminal.term.screen_text())
    yield terminal
    terminal.close_connection()


def test_typed_keys_reach_cmd_and_its_answer_is_drawn(cmd: TerminalView) -> None:
    _typed(cmd, "echo capy 42\r")
    _until(lambda: "capy 42" in cmd.term.screen_text())
    assert ">echo capy 42" in cmd.term.screen_text()
    cmd.grab()


def test_keys_as_text_reach_cmd_on_a_real_pseudo_console(cmd: TerminalView) -> None:
    cmd.term.win32_input = False
    _typed(cmd, "echo capy 43\r")
    _until(lambda: "capy 43" in cmd.term.screen_text())
    assert ">echo capy 43" in cmd.term.screen_text()


@pytest.mark.parametrize("cmd", ["carried"], indirect=True)
def test_the_carried_engine_asks_for_key_events_first_thing(cmd: TerminalView) -> None:
    assert cmd.session is not None and cmd.session.engine is conpty.carried_engine()
    _until(lambda: cmd.term.win32_input)
    assert cmd.term.regional_indicator_cells == 1


def test_the_screen_counts_half_a_flag_as_the_console_engine_does(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    narrow = replace(conpty.WINDOWS, name="like the carried one", regional_indicator_cells=1)
    made: list[FakeConsole] = []

    def start(*args: Any, **kwargs: Any) -> FakeConsole:
        made.append(FakeConsole(*args, engine=narrow, **kwargs))
        return made[-1]

    monkeypatch.setattr(view_module, "PseudoConsole", start)
    terminal = TerminalView(host="web-01")
    _shown(terminal)
    terminal.start(["ssh.exe", "--", "web-01"])
    made[-1].prints("[\U0001f1e7\U0001f1f7]".encode())
    _until(lambda: terminal.term.screen_text()[0] == "[\U0001f1e7\U0001f1f7]")
    assert terminal.term.cursor.x == 4  # 2 + 2: the flag's two halves, a cell each
    terminal.close_connection()


def test_enter_on_an_ended_cmd_runs_it_again(cmd: TerminalView) -> None:
    ended: list[object] = []
    cmd.ended.connect(ended.append)
    _typed(cmd, "exit 3\r")
    _until(lambda: ended == [3])
    _typed(cmd, "\r")
    _until(lambda: cmd.running and ">" in cmd.term.screen_text())


def test_a_long_pasted_line_reaches_the_program_whole(cmd: TerminalView) -> None:
    long = "0123456789" * 15
    assert len(long) > cmd.term.columns
    assert cmd.paste_text("echo " + long)
    _typed(cmd, "\r")
    _until(lambda: "".join(_all_rows(cmd)).count(long) >= 2)


def test_a_flood_lands_whole_and_in_order(cmd: TerminalView) -> None:
    assert cmd.paste_text("for /l %i in (1,1,3000) do @echo line %i")
    _typed(cmd, "\r")
    _until(lambda: "line 3000" in cmd.term.screen_text(), seconds=60)
    lines = [row for row in _all_rows(cmd) if row.startswith("line ")]
    assert lines == [f"line {i}" for i in range(1, 3001)]


LOADS_NOTHING_EARLY = """
import shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])  # tests/helpers: the suite's own Credential Manager
from fake_credman import FakeCredentialManager
from capypanel.core import credstore
credstore.PREFIX, credstore._advapi32 = "CapyPanelTest/", FakeCredentialManager()
import capypanel.ui.app
from capypanel.ui import selftest
from capypanel.ui.hosts_tool.tool import HostsTool
HostsTool._read_shown_facts = lambda self: None  # never the network
root = Path(tempfile.mkdtemp(dir=sys.argv[2]))
selftest._whole_window(root)  # every tool, theme and language, and every Settings page
shutil.rmtree(root)
late = ("capypanel.ui.ssh_tool.terminal", "capypanel.core.ssh.screen",
        "capypanel.core.ssh.conpty", "capypanel.vendor.pyte")
print(sorted(m for m in sys.modules if m.startswith(late)))
"""


def test_opening_every_tool_and_settings_page_loads_none_of_the_terminal(
    tmp_path: Path,
) -> None:
    helpers = Path(__file__).resolve().parent.parent / "helpers"
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    found = subprocess.run(  # noqa: S603 -- this Python, with a probe of our own
        [sys.executable, "-c", LOADS_NOTHING_EARLY, str(helpers), str(tmp_path)],
        capture_output=True, text=True, timeout=120, check=False, env=env,
    )  # fmt: skip
    assert found.returncode == 0, found.stderr[-2000:]
    assert found.stdout.strip().splitlines()[-1] == "[]"


OURS: list[int | str] = [*range(16), "default"]


def test_in_every_shipped_theme_the_16_and_the_defaults_read_on_each_other(
    default_theme_after: None,
) -> None:
    for theme in themes.Registry().all():
        themes.apply(theme)
        pal = palette.current()
        unreadable = [
            (fg, bg, bold, reverse, pair)
            for fg in OURS
            for bg in OURS
            for bold in (False, True)
            for reverse in (False, True)
            if (pair := pal.cell_colors(fg, bg, bold=bold, reverse=reverse))[0] != pair[1]
            and palette.contrast(*pair) < palette.READS
        ]
        assert unreadable == [], theme.id


def test_every_shipped_theme_gives_the_strip_its_grey_edge_after_a_normal_end(
    qapp: QApplication, default_theme_after: None
) -> None:
    for theme in themes.Registry().all():
        themes.apply(theme)
        offline = themes.status_color("offline")
        rule = f'QFrame#resultStrip[ended="true"] {{ border-left-color: {offline}; }}'
        assert rule in qapp.styleSheet(), theme.id


def test_a_terminal_follows_the_theme_unless_given_colours_of_its_own(
    qapp: QApplication, default_theme_after: None
) -> None:
    follows = TerminalView(host="web-01")
    given = palette.current()
    fixed = TerminalView(host="web-01", palette=given)
    for theme_id in ("capypanel-dark", "capypanel-light"):
        themes.apply(themes.Registry().find(theme_id))
        assert follows.term_palette.name == theme_id
        assert follows.term_palette.background == themes.current().colors["card"]
        assert fixed.term_palette is given


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_the_cursor_shows_on_the_terminal_with_any_accent(scheme: str, accent: str) -> None:
    roles = {**themes.TOKENS[scheme], **themes.NATIVE_TOKENS[scheme], "accent": accent}
    pal = palette.from_roles(f"windows-{scheme}", {**roles, "sel": accent}, scheme == "dark")
    assert palette.contrast(pal.cursor, pal.background) >= palette.SHOWS
    shows = palette.contrast(accent, roles["card"]) >= palette.SHOWS
    assert pal.cursor == (accent if shows else roles["text"])


def test_colours_from_the_256_or_24_bit_ones_are_drawn_as_asked(qapp: QApplication) -> None:
    pal = palette.current()
    assert pal.cell_colors(232, 233) == ("#080808", "#121212")  # unreadable, and on purpose
    assert pal.cell_colors("#010101", "#000000") == ("#010101", "#000000")
    assert pal.cell_colors(1, 232) == (pal.ansi[1], "#080808")
    assert pal.cell_colors("#000001", "default") == ("#000001", pal.background)


def test_bold_text_in_the_first_eight_takes_the_bright_ones(qapp: QApplication) -> None:
    pal = palette.current()
    assert pal.color(1, foreground=True, bold=True) == pal.ansi[9]
    assert pal.color(9, foreground=True, bold=True) == pal.ansi[9]
    assert pal.color(1, foreground=False, bold=True) == pal.back[1]
    assert pal.color(100, foreground=True, bold=True) == pal.color(100, foreground=True)


@pytest.mark.parametrize(
    ("code", "by_us", "error", "words"),
    [
        (0, False, False, "The connection to web-01 ended."),
        (130, False, False, "The connection to web-01 ended."),  # exit after Ctrl+C on tail -f
        (
            255,
            False,
            True,
            "The connection to web-01 ended with an error. ssh.exe's message is above.",
        ),
        (
            0xC0000005,
            False,
            True,
            "The connection to web-01 ended with an error (exit code 0xC0000005).",
        ),
        (0xC000013A, False, False, "The connection to web-01 ended."),
        (255, True, False, "The connection to web-01 ended."),  # CapyPanel closed it
    ],
)
def test_the_strip_after_an_end_is_red_with_a_cross_only_after_an_error(
    qapp: QApplication, code: int, by_us: bool, error: bool, words: str, no_browser: list[str]
) -> None:
    holder = QWidget()
    bar = EndedBar(holder)
    bar.show_end("web-01", code, by_us=by_us)
    assert bar.words() == words and bar.label.wordWrap()
    assert bar.label.text().startswith(words)
    assert ("What does this mean?" in bar.label.text()) == error
    if error:
        bar.label.linkActivated.emit("")
        assert no_browser == [help_links.url("ssh-when-a-connection-ends")]
    assert (bar.error, bar.property("failed"), bar.property("ended")) == (error, error, not error)
    assert bar.icon_name() == ("circle-x" if error else "plug-connected-x")
    assert bar.colour() == themes.status_color("stopped" if error else "offline")
    assert (bar.reconnect_button.text(), bar.close_button.text()) == ("&Reconnect", "Close &tab")
    assert bar.reconnect_button.isDefault()


# Consolas and Cascadia Mono from 8 to 20 pt at 100, 125 and 150 %, and two narrow cells.
CELLS = [(5, 10), (6, 13), (7, 15), (8, 15), (9, 19), (10, 19), (11, 23), (11, 24), (12, 25),
         (15, 32), (16, 31), (20, 40)]  # fmt: skip
CELL_IDS = [f"{w}x{h}" for w, h in CELLS]
BOX = [chr(o) for o in range(0x2500, 0x2580)]
BUILT_IN = [
    *BOX,
    *(chr(o) for o in range(0x2580, 0x25A0)),  # blocks
    *(chr(o) for o in range(0xE0A0, 0xE0A4)),  # Powerline's symbols
    *(chr(o) for o in range(0xE0B0, 0xE0C0)),  # and its shapes
]
DOUBLE_PIECES = {
    "═": 2, "║": 2, "╒": 1, "╓": 1, "╔": 2, "╕": 1, "╖": 1, "╗": 2, "╘": 1, "╙": 1,
    "╚": 2, "╛": 1, "╜": 1, "╝": 2, "╞": 1, "╟": 2, "╠": 3, "╡": 1, "╢": 2, "╣": 3,
    "╤": 2, "╥": 1, "╦": 3, "╧": 2, "╨": 1, "╩": 3, "╪": 1, "╫": 1, "╬": 4,
}  # fmt: skip
FIGURES = {
    "light grid": (["┌─┬─┐", "│ │ │", "├─┼─┤", "│ │ │", "└─┴─┘"], 1, 5),
    "heavy grid": (["┏━┳━┓", "┃ ┃ ┃", "┣━╋━┫", "┃ ┃ ┃", "┗━┻━┛"], 1, 5),
    "double grid": (["╔═╦═╗", "║ ║ ║", "╠═╬═╣", "║ ║ ║", "╚═╩═╝"], 5, 6),
    "heavy frame, light lines": (["┏━┯━┓", "┃ │ ┃", "┠─┼─┨", "┃ │ ┃", "┗━┷━┛"], 1, 5),
    "double frame, single lines": (["╔═╤═╗", "║ │ ║", "╟─┼─╢", "║ │ ║", "╚═╧═╝"], 2, 6),
    "double across, single down": (["╒═╤═╕", "│ │ │", "╞═╪═╡", "│ │ │", "╘═╧═╛"], 1, 9),
    "single across, double down": (["╓─╥─╖", "║ ║ ║", "╟─╫─╢", "║ ║ ║", "╙─╨─╜"], 1, 9),
    "rounded": (["╭─┬─╮", "│ │ │", "├─┼─┤", "│ │ │", "╰─┴─╯"], 1, 5),
}
ARMS = (glyphs.L, glyphs.R, glyphs.U, glyphs.D)


def _render(rows: Sequence[str], cw: int, ch: int, margin: int = 1) -> QImage:
    cols = max(len(row) for row in rows)
    img = QImage(
        (cols + 2 * margin) * cw, (len(rows) + 2 * margin) * ch, QImage.Format.Format_RGB32
    )
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    m, black = glyphs.Metrics(cw, ch), QColor(0, 0, 0)
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            if text != " ":
                glyphs.draw(p, text, (c + margin) * cw, (r + margin) * ch, m, black)
    p.end()
    return img


def _ink(img: QImage, level: int) -> list[list[bool]]:
    bits, per_line, w = bytes(img.constBits()), img.bytesPerLine(), img.width()
    return [[bits[y * per_line + 4 * x + 2] < level for x in range(w)] for y in range(img.height())]


def _count(mask: list[list[bool]], want: bool, *, eight: bool) -> int:
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if eight:
        steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    n = 0
    for y0 in range(h):
        for x0 in range(w):
            if seen[y0][x0] or mask[y0][x0] != want:
                continue
            n += 1
            seen[y0][x0] = True
            todo = deque([(x0, y0)])
            while todo:
                x, y = todo.popleft()
                for dx, dy in steps:
                    a, b = x + dx, y + dy
                    if 0 <= a < w and 0 <= b < h and not seen[b][a] and mask[b][a] == want:
                        seen[b][a] = True
                        todo.append((a, b))
    return n


def _edge(m: glyphs.Metrics, weight: int, horizontal: bool) -> set[int]:
    if weight == 0:
        return set()
    if weight in (1, 2):
        start, thick = m.line(weight, horizontal)
        return set(range(start, start + thick))
    base = m.cy if horizontal else m.cx
    first, second = base - m.double, base + m.double
    return set(range(first, first + m.light)) | set(range(second, second + m.light))


def _problems(text: str, cw: int, ch: int) -> list[str]:
    m = glyphs.Metrics(cw, ch)
    match glyphs.box_shape(text):
        case ("arms", arms):
            weights = {arm: arms.get(arm, 0) for arm in ARMS}
            level = 128
        case ("arc", ends):
            weights = {arm: int(arm in ends) for arm in ARMS}
            level = 250
        case _:
            return []
    img = _render([text], cw, ch, margin=0)
    mask = _ink(img, 128)
    edges = {
        glyphs.L: {y for y in range(ch) if mask[y][0]},
        glyphs.R: {y for y in range(ch) if mask[y][cw - 1]},
        glyphs.U: {x for x in range(cw) if mask[0][x]},
        glyphs.D: {x for x in range(cw) if mask[ch - 1][x]},
    }
    problems = []
    for arm, weight in weights.items():
        want = _edge(m, weight, arm in (glyphs.L, glyphs.R))
        if edges[arm] != want:
            problems.append(f"{arm} edge {sorted(edges[arm])} not {sorted(want)}")
    mask = _ink(img, level)
    pieces, want_pieces = _count(mask, True, eight=False), DOUBLE_PIECES.get(text, 1)
    if pieces != want_pieces:
        problems.append(f"{pieces} pieces, not {want_pieces}")
    ends = sum(0 if w == 0 else 2 if w == 3 else 1 for w in weights.values())
    regions = _count(mask, False, eight=True)
    if regions != 1 + ends - want_pieces:
        problems.append(f"{regions} regions, not {1 + ends - want_pieces}")
    return problems


@pytest.mark.parametrize(("cw", "ch"), CELLS, ids=CELL_IDS)
def test_line_characters_meet_their_neighbours_and_close_their_joins(
    qapp: QApplication, cw: int, ch: int
) -> None:
    wrong = {f"U+{ord(text):04X}": p for text in BOX if (p := _problems(text, cw, ch))}
    assert wrong == {}


@pytest.mark.parametrize(("cw", "ch"), CELLS, ids=CELL_IDS)
def test_boxes_drawn_from_them_enclose_what_they_should(
    qapp: QApplication, cw: int, ch: int
) -> None:
    for name, (rows, pieces, regions) in FIGURES.items():
        mask = _ink(_render(rows, cw, ch), 250)
        got = (_count(mask, True, eight=False), _count(mask, False, eight=True))
        assert got == (pieces, regions), name


@pytest.mark.parametrize(("cw", "ch"), CELLS, ids=CELL_IDS)
def test_each_character_stays_in_its_cell_and_blocks_leave_no_seam(
    qapp: QApplication, cw: int, ch: int
) -> None:
    for text in BUILT_IN:
        mask = _ink(_render([text], cw, ch), 255)  # any pixel not white
        outside = [
            (x, y)
            for y, row in enumerate(mask)
            for x, inked in enumerate(row)
            if inked and not (cw <= x < 2 * cw and ch <= y < 2 * ch)
        ]
        assert outside == [], f"U+{ord(text):04X}"
    for one, other in (("▀", "▄"), ("▌", "▐")):
        a, b = _ink(_render([one], cw, ch, 0), 255), _ink(_render([other], cw, ch, 0), 255)
        assert all(
            x != y
            for row_a, row_b in zip(a, b, strict=True)
            for x, y in zip(row_a, row_b, strict=True)
        )
    full = _ink(_render(["███", "███"], cw, ch, 0), 128)
    assert all(all(row) for row in full)


def _printed(view: TerminalView, consoles: list[FakeConsole], data: bytes) -> FakeConsole:
    view.start(["ssh.exe"])
    console = consoles[-1]
    console.prints(data)
    _until(lambda: not console.pending)
    view.settle()
    return console


def _enter(widget: QWidget, mods: Qt.KeyboardModifier = NONE) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, K.Key_Return, mods, "\r"))


def _rows_shown(view: TerminalView) -> list[str]:
    top = view.verticalScrollBar().value()
    return [view.term.row_text(r) for r in range(top, top + view.term.lines)]


def test_the_terminal_menu_finds_saves_and_clears_in_that_order(view: TerminalView) -> None:
    actions = view.menu().actions()
    assert [menus.label(a) for a in actions] == [
        "&Copy", "&Paste", "Select &all", "", "&Find…", "Save the &text…", "Clear &scrollback",
    ]  # fmt: skip
    assert actions[4].shortcut().toString() == "Ctrl+Shift+F"


def test_ctrl_shift_f_opens_find_with_the_words_selected_and_sends_nothing(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    console = _printed(view, consoles, b"disk sda1 92% full\r\n$ ")
    _asks_for_key_events(view, console)
    view.select_cells((0, 5), (0, 8))
    both = keys.Q_CTRL_L | keys.Q_SHIFT_L
    QApplication.sendEvent(view, _key(K.Key_F, 0x46, 0x21, native=both, mods=CTRL | SHIFT))
    bar = view.search_bar
    assert bar is not None and bar.isVisible()
    assert view.window().focusWidget() is bar.field
    assert bar.words == "sda1" and bar.count.text() == "1 of 1"
    assert console.written == []


def test_find_starts_at_the_newest_match_and_enter_goes_to_older_ones_in_turn(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    errors = {10: b"error ten", 50: b"error fifty", 95: b"error ninety-five"}
    text = b"".join(errors.get(n, b"line %d ok" % n) + b"\r\n" for n in range(100))
    console = _printed(view, consoles, text + b"$ ")
    view.open_search()
    bar = view.search_bar
    assert bar is not None
    bar.field.setText("ERROR")
    bar.flush()
    assert bar.count.text() == "3 of 3" and view.selected_text() == "error"
    assert "error ninety-five" in _rows_shown(view)
    QApplication.processEvents()
    assert bar.count.geometry().left() > bar.field.geometry().right()
    assert bar.count.width() >= bar.count.sizeHint().width()
    assert bar.geometry().right() < view.viewport().geometry().right()
    for count, words in (("2 of 3", "error fifty"), ("1 of 3", "error ten"), ("3 of 3", "nine")):
        _enter(bar.field)
        assert bar.count.text() == count
        assert any(words in row for row in _rows_shown(view))
    _enter(bar.field, SHIFT)
    assert bar.count.text() == "1 of 3"
    assert console.written == []


def test_find_can_match_case_and_says_when_nothing_matches(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    _printed(view, consoles, b"Error one\r\nerror two\r\n")
    view.open_search()
    bar = view.search_bar
    assert bar is not None
    bar.field.setText("Error")
    bar.flush()
    assert bar.count.text() == "2 of 2"
    bar.case.setChecked(True)
    assert bar.count.text() == "1 of 1"
    bar.field.setText("missing")
    bar.flush()
    assert bar.count.text() == "No matches"


def test_escape_closes_find_and_gives_the_keys_back_to_the_terminal(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    console = _printed(view, consoles, b"error\r\n")
    view.open_search()
    bar = view.search_bar
    assert bar is not None
    bar.field.setText("error")
    bar.flush()
    QApplication.sendEvent(bar.field, QKeyEvent(QEvent.Type.KeyPress, K.Key_Escape, NONE))
    assert not bar.isVisible()
    assert view.window().focusWidget() is view
    assert view._visible_matches(0) == {}
    assert console.written == []


def test_save_the_text_writes_each_line_whole_for_windows_and_remembers_the_folder(
    view: TerminalView, consoles: list[FakeConsole], tmp_path: Path
) -> None:
    long = "".join(chr(ord("a") + n % 26) for n in range(300))
    _printed(view, consoles, f"{long}\r\nsecond  \r\n$ ".encode())
    assert view.term.wrapped_at(0)
    target = tmp_path / "web-01.txt"
    suggested: list[str] = []
    remembered: list[str | None] = []
    saved: list[str] = []

    def ask(_parent: QWidget, _title: str, path: str) -> str:
        suggested.append(path)
        return str(target)

    def folder(chosen: str | None) -> str:
        remembered.append(chosen)
        return str(tmp_path)

    view.ask_save_path, view.save_folder = ask, folder
    view.text_saved.connect(saved.append)
    view.save_text()
    assert Path(suggested[0]).parent == tmp_path
    assert Path(suggested[0]).name.startswith("web-01 ") and suggested[0].endswith(".txt")
    assert target.read_bytes() == b"\xef\xbb\xbf" + f"{long}\r\nsecond\r\n$\r\n".encode()
    assert remembered == [None, str(tmp_path)]
    assert saved == [str(target)]


def test_a_file_that_can_t_be_saved_says_why_and_its_folder_isn_t_remembered(
    view: TerminalView,
    consoles: list[FakeConsole],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _printed(view, consoles, b"text\r\n")
    warned: list[tuple[str, str]] = []
    monkeypatch.setattr(
        help_links, "warning", lambda _p, _title, text, *, place: warned.append((text, place))
    )
    remembered: list[str | None] = []

    def folder(chosen: str | None) -> str:
        remembered.append(chosen)
        return ""

    view.save_folder = folder
    view.ask_save_path = lambda *_args: str(tmp_path / "gone" / "web-01.txt")
    view.save_text()
    assert len(warned) == 1 and "web-01.txt" in warned[0][0]
    assert warned[0][1] == "ssh-work-in-the-terminal"
    view.ask_save_path = lambda *_args: ""
    view.save_text()
    assert remembered == [None, None]


def test_a_narrower_terminal_rewraps_its_scrollback_once_the_resizing_stops(
    view: TerminalView, consoles: list[FakeConsole]
) -> None:
    lines = ["".join(chr(ord("a") + (n + i) % 26) for i in range(150)) for n in range(40)]
    _printed(view, consoles, "\r\n".join([*lines, "$ "]).encode())
    view.window().resize(500, 400)
    QApplication.processEvents()
    assert not view.term.scrollback_settled
    _until(lambda: view.term.scrollback_settled)
    columns = view.term.columns
    assert all(len(row) <= columns for row in view.term.scrollback_text())
    assert view.term.whole_text().split("\r\n")[:40] == lines
