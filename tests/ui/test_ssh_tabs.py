"""The SSH tool's connections as tabs (topic-027): each opens in a tab of its own named after its
server, in front; an open one asks before it closes, and quitting asks once for all of them;
the text size is kept for every tab and after a restart, and nothing else of a connection is.
The pseudo console is a stand-in the test drives (tests/helpers/fake_console.py), except in the
last test, where Windows' own cmd.exe stands in for ssh.exe (tests/ui/conftest.py)."""

import json
import time
from collections import deque
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fake_console import FakeConsole
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget
from test_printers_tool import FakeShell  # the same pretend shell as Printers' tests

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.ssh.host import SshInfo, with_info
from capypanel.ui import menus
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.ssh_tool import tool as tool_module
from capypanel.ui.ssh_tool.terminal import keys
from capypanel.ui.ssh_tool.terminal import view as view_module
from capypanel.ui.ssh_tool.tool import POINTS, SshTool
from capypanel.ui.tab_strip import PINNED


@pytest.fixture
def shell(tmp_path: Path) -> FakeShell:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return FakeShell(settings.resolve_paths(tmp_path))


@pytest.fixture
def servers(tmp_path: Path) -> Path:
    hl, racks = HostList().add_group("Racks")
    for name, address in (("core-sw-01", "192.0.2.40"), ("nas-01", "192.0.2.41")):
        hl, host = hl.add_host(name, racks.id, address=address)
        hl = hl.update_host(with_info(host, SshInfo(login="admin")))
    hl, _web = hl.add_host("web-01", NO_GROUP, address="198.51.100.42")
    path = tmp_path / "servers.json"
    listfile.save(path, hl, expected=None, kind="ssh")
    return path


@pytest.fixture
def consoles(monkeypatch: pytest.MonkeyPatch) -> list[FakeConsole]:
    """Every pseudo console a tab starts, each a stand-in the test drives."""
    made: list[FakeConsole] = []

    def start(*args: Any, **kwargs: Any) -> FakeConsole:
        made.append(FakeConsole(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(view_module, "PseudoConsole", start)
    return made


class Answers:
    """Stands in for the SSH tool's run_modal: keeps each question's words and gives the answers
    queued, Cancel once none is left."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, str]] = []  # title, question, action
        self.queued: deque[bool] = deque()

    def __call__(self, dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, Question)
        self.asked.append((dialog.windowTitle(), dialog.heading.text(), dialog.action.text()))
        yes = self.queued.popleft() if self.queued else False
        return QDialog.DialogCode.Accepted if yes else QDialog.DialogCode.Rejected


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> Answers:
    answering = Answers()
    monkeypatch.setattr(tool_module, "run_modal", answering)
    return answering


def _closed_after(tool: SshTool) -> None:
    for tab in tool.connections():
        tab.close_connection()
    tool.close()
    tool.deleteLater()


@pytest.fixture
def ssh(
    qapp: QApplication, shell: FakeShell, servers: Path, consoles: list[FakeConsole]
) -> Iterator[SshTool]:
    tool = SshTool(shell)
    assert tool.open_list(servers)
    yield tool
    _closed_after(tool)


def _select(tool: SshTool, *names: str) -> None:
    tool.table.clearSelection()
    for i in range(tool.table.topLevelItemCount()):
        row = tool.table.topLevelItem(i)
        if row is not None and row.text(0) in names:
            row.setSelected(True)


def _connect(tool: SshTool, *names: str) -> None:
    _select(tool, *names)
    tool.commands.connect_host.trigger()


def _names(tool: SshTool) -> list[str]:
    return [tool.tabs.bar.tabText(i) for i in range(tool.tabs.bar.count())]


def _until(test: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds  # a deadline, not a count: threads can be slow
    while not test():
        assert time.monotonic() < deadline, "timed out"
        QApplication.processEvents()
        time.sleep(0.005)


def _ended(tool: SshTool, console: FakeConsole, code: int) -> None:
    """The program on `console` ends by itself, and its tab shows it."""
    console.ends(code)
    tab = next(t for t in tool.connections() if t.view.session is console)
    _until(lambda: tab.ended)


def test_each_connection_opens_in_front_in_a_tab_named_after_its_server(
    ssh: SshTool, consoles: list[FakeConsole], no_ssh: list[tuple[str, object]]
) -> None:
    _connect(ssh, "nas-01")
    assert no_ssh == [("192.0.2.41", SshInfo(login="admin"))]
    assert _names(ssh) == ["nas-01"] and ssh.tabs.current() == "connection-1"
    assert ssh.pages.currentWidget() is ssh.connections()[0]
    assert len(consoles) == 1 and consoles[0].running
    _connect(ssh, "nas-01")  # the same server again: a tab of its own
    assert _names(ssh) == ["nas-01", "nas-01 (2)"] and ssh.tabs.current() == "connection-2"


def test_several_selected_open_a_tab_each_with_the_first_in_front(ssh: SshTool) -> None:
    _connect(ssh, "core-sw-01", "nas-01", "web-01")
    assert sorted(_names(ssh)) == ["core-sw-01", "nas-01", "web-01"]
    assert ssh.tabs.current() == ssh.tabs.tab_keys()[0]


def test_a_number_a_closed_tab_freed_is_used_again(
    ssh: SshTool, consoles: list[FakeConsole], answers: Answers
) -> None:
    for _ in range(3):
        _connect(ssh, "nas-01")
    assert _names(ssh) == ["nas-01", "nas-01 (2)", "nas-01 (3)"]
    _ended(ssh, consoles[1], 0)
    assert ssh.close_tab("connection-2")
    assert answers.asked == []  # an ended connection closes without asking
    _connect(ssh, "nas-01")
    assert _names(ssh) == ["nas-01", "nas-01 (3)", "nas-01 (2)"]


def test_closing_an_open_connection_asks_and_cancel_keeps_it(
    ssh: SshTool, consoles: list[FakeConsole], answers: Answers
) -> None:
    _connect(ssh, "nas-01")
    assert not ssh.close_tab("connection-1")  # Cancel
    assert answers.asked == [("Close", "<b>Close the connection to nas-01?</b>", "&Close")]
    assert ssh.tabs.tab_keys() == ["connection-1"] and not consoles[0].closed
    answers.queued.append(True)
    assert ssh.close_tab("connection-1")
    assert ssh.tabs.tab_keys() == [] and consoles[0].closed
    assert ssh.tabs.current() == PINNED and ssh.pages.currentWidget() is ssh.inner
    assert not ssh.close_tab(PINNED)  # the list's tab never closes


def test_closing_the_tab_in_front_brings_its_left_neighbour_forward(
    ssh: SshTool, consoles: list[FakeConsole], answers: Answers
) -> None:
    _connect(ssh, "core-sw-01")
    _connect(ssh, "nas-01")
    _connect(ssh, "web-01")
    ssh.switch("connection-2")
    _ended(ssh, consoles[1], 0)
    assert ssh.close_tab("connection-2")
    assert ssh.tabs.current() == "connection-1"


def test_ctrl_shift_w_closes_the_tab_in_front_and_ctrl_tab_goes_round(
    ssh: SshTool, answers: Answers
) -> None:
    _connect(ssh, "core-sw-01")
    _connect(ssh, "nas-01")
    shortcuts = {s.key().toString(): s for s in ssh.findChildren(QShortcut)}
    for keys_ in ("Ctrl+Tab", "Ctrl+Shift+Tab", "Ctrl+Shift+W"):
        assert shortcuts[keys_].context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert ssh.tabs.current() == "connection-2"
    shortcuts["Ctrl+Tab"].activated.emit()
    assert ssh.tabs.current() == PINNED  # round to the list
    shortcuts["Ctrl+Tab"].activated.emit()
    assert ssh.tabs.current() == "connection-1"
    shortcuts["Ctrl+Shift+Tab"].activated.emit()
    assert ssh.tabs.current() == PINNED
    shortcuts["Ctrl+Shift+Tab"].activated.emit()
    assert ssh.tabs.current() == "connection-2"
    answers.queued.append(True)
    shortcuts["Ctrl+Shift+W"].activated.emit()
    assert ssh.tabs.tab_keys() == ["connection-1"] and ssh.tabs.current() == "connection-1"
    assert QKeySequence("Ctrl+W") not in [s.key() for s in ssh.findChildren(QShortcut)]


def test_quitting_with_connections_open_asks_once_and_closes_them(
    ssh: SshTool, consoles: list[FakeConsole], answers: Answers
) -> None:
    _connect(ssh, "core-sw-01", "nas-01", "web-01")
    _ended(ssh, consoles[2], 0)
    window = QWidget()
    assert not ssh.quit_question(window)  # Cancel: CapyPanel stays open
    assert answers.asked == [
        ("Quit CapyPanel", "<b>Quit CapyPanel with 2 connections open?</b>", "&Quit")
    ]
    assert not consoles[0].closed and not consoles[1].closed
    answers.queued.append(True)
    assert ssh.quit_question(window)
    assert all(console.closed for console in consoles)
    assert ssh.quit_question(window) and len(answers.asked) == 2  # none open: no question


def test_the_text_size_is_kept_for_every_tab_and_after_a_restart(
    ssh: SshTool, shell: FakeShell, servers: Path, consoles: list[FakeConsole]
) -> None:
    _connect(ssh, "core-sw-01", "nas-01")
    first, second = ssh.connections()
    size = first.view.point_size
    bigger = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Equal,
        Qt.KeyboardModifier.ControlModifier,
        0x0D,
        0xBB,
        keys.Q_CTRL_L,
    )
    QApplication.sendEvent(first.view, bigger)
    assert first.view.point_size == second.view.point_size == size + 1
    assert ssh.prefs[POINTS] == size + 1
    again = SshTool(shell)  # CapyPanel started again
    try:
        assert again.open_list(servers)
        assert again.terminal_points() == size + 1
        _connect(again, "web-01")
        assert again.connections()[0].view.point_size == size + 1
    finally:
        _closed_after(again)


def test_nothing_of_a_connection_outlives_capypanel(
    ssh: SshTool, shell: FakeShell, servers: Path
) -> None:
    _connect(ssh, "nas-01", "web-01")
    ssh.save_state()
    saved = json.dumps(shell.prefs)
    assert "192.0.2.41" not in saved and "nas-01" not in saved and "connection-" not in saved
    again = SshTool(shell)
    try:
        assert again.open_list(servers)
        assert again.connections() == [] and again.tabs.tab_keys() == []
        assert again.tabs.current() == PINNED
    finally:
        _closed_after(again)


def test_the_tab_menu_reconnects_an_ended_one_and_closes_others_with_one_question(
    ssh: SshTool,
    consoles: list[FakeConsole],
    answers: Answers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _connect(ssh, "core-sw-01")
    _connect(ssh, "nas-01")
    _connect(ssh, "web-01")
    _ended(ssh, consoles[1], 255)
    shown: list[QMenu] = []
    monkeypatch.setattr(tool_module, "popup", lambda menu, _where: shown.append(menu))

    def menu_of(key: str) -> list[tuple[str, bool]]:
        ssh.tab_menu(key, QPoint())
        return [(menus.label(a), a.isEnabled()) for a in shown[-1].actions() if not a.isSeparator()]

    assert menu_of("connection-1") == [
        ("Reconnect", False),  # it's open; no access keys, as in Profile cleanup's tab menu
        ("Close", True),
        ("Close the others", True),
        ("Close the ended ones", True),
    ]
    assert menu_of("connection-2")[0] == ("Reconnect", True)  # it has ended
    shown[-1].actions()[0].trigger()
    assert len(consoles) == 4 and ssh.connections()[1].running
    assert ("Close the ended ones", False) in menu_of("connection-2")
    answers.queued.append(True)
    others = next(a for a in shown[-1].actions() if menus.label(a) == "Close the others")
    others.trigger()
    assert answers.asked == [("Close", "<b>Close 2 open connections?</b>", "&Close")]
    assert _names(ssh) == ["nas-01"]


def test_a_tab_s_mark_says_whether_it_is_open_or_how_it_ended(
    ssh: SshTool, consoles: list[FakeConsole]
) -> None:
    _connect(ssh, "core-sw-01")
    _connect(ssh, "nas-01")
    bar = ssh.tabs.bar
    assert [bar.tabToolTip(i) for i in range(2)] == ["Connection open", "Connection open"]
    assert not bar.tabIcon(0).isNull()
    _ended(ssh, consoles[0], 255)
    _ended(ssh, consoles[1], 0)
    assert [bar.tabToolTip(i) for i in range(2)] == ["Ended with an error", "Ended"]
    assert ssh.tabs.pinned.tabText(0) == "Hosts (3)"
    more = ssh.tabs.more.menu()
    more.aboutToShow.emit()
    assert [a.text() for a in more.actions()] == ["Hosts (3)", "core-sw-01", "nas-01"]
    assert [a.isChecked() for a in more.actions()] == [False, False, True]


def test_connect_runs_the_program_in_its_tab_and_closing_the_tab_ends_it(
    qapp: QApplication, shell: FakeShell, servers: Path, answers: Answers
) -> None:
    """The real pseudo console, with Windows' own cmd.exe standing in for ssh.exe."""
    tool = SshTool(shell)
    try:
        assert tool.open_list(servers)
        _connect(tool, "web-01")
        tab = tool.connections()[0]
        _until(lambda: any(row.endswith(">") for row in tab.view.term.screen_text()))
        session = tab.view.session
        assert session is not None and session.running
        answers.queued.append(True)
        assert tool.close_tab("connection-1")
        assert len(answers.asked) == 1 and not session.running
    finally:
        _closed_after(tool)
