"""The built-in scripts: the Scripts group, the questions, the answers in the result strip and the
Commands window, and their output. The run on the PC is replaced: nothing here reaches the
network or runs anything."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QPlainTextEdit

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import builtin
from capypanel.core.remote.access import Account
from capypanel.core.remote.run import Engine, Problem, RunError, RunResult, Script
from capypanel.ui.hosts_tool import command_windows, result_strip, runner
from capypanel.ui.hosts_tool.command_windows import OutputDialog
from capypanel.ui.hosts_tool.commands_window import CommandsWindow
from capypanel.ui.hosts_tool.runner import HostTarget

ACCEPT, REJECT = QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, office = HostList().add_group("Office")
    for name, address in [("PC-1", "192.0.2.1"), ("PC-2", "192.0.2.2")]:
        hl, _host = hl.add_host(name, office.id, address=address)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


class FakeRuns:
    """Stands in for the run layer: records each run and answers with `answer`."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, Script, Account | None, float]] = []
        self.answer: Callable[[], RunResult] = lambda: result(0, "done\n")

    def run(
        self, host: str, script: Script, account: Account | None = None, timeout: float = 0
    ) -> RunResult:
        self.runs.append((host, script, account, timeout))
        return self.answer()


def result(code: int, output: str = "", errors: str = "") -> RunResult:
    return RunResult(Engine.WMI, code, output, errors, 1.0)


@pytest.fixture
def runs(window: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> FakeRuns:
    fake = FakeRuns()
    monkeypatch.setattr(window.hosts.runner, "scripts", fake)
    return fake


def _select(win: CapyWindow, name: str) -> HostTarget:
    assert win.hosts.document is not None
    host = next(h for h in win.hosts.document.hosts.hosts if h.name == name)
    win.hosts.table.select_ids([host.id])
    target = win.hosts.selected_target()
    assert target is not None
    return target


def _settle(win: CapyWindow) -> None:
    deadline = time.monotonic() + 10  # a deadline, not a count: threads can be slow
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not win.hosts.runner.busy():
            QApplication.processEvents()
            return
    pytest.fail("a script never finished")


def _answer(monkeypatch: pytest.MonkeyPatch, answer: Callable[[QDialog], Any]) -> list[QDialog]:
    opened: list[QDialog] = []

    def run(dialog: QDialog) -> Any:
        opened.append(dialog)
        return answer(dialog)

    for module in (runner, command_windows, result_strip):
        monkeypatch.setattr(module, "run_modal", run)
    return opened


def _run(win: CapyWindow, command_id: str, name: str = "PC-1") -> None:
    win.hosts.runner.run(command_id, _select(win, name), win.hosts.show_outcome)
    _settle(win)


def _commands(win: CapyWindow) -> CommandsWindow:
    commands = win.hosts._commands_window  # pyright: ignore[reportPrivateUsage]
    assert isinstance(commands, CommandsWindow)
    return commands


def _shown(commands: CommandsWindow) -> list[str]:
    return [r.command.id for r in commands.rows if not r.isHidden()]


def test_the_menus_list_no_scripts_but_open_the_scripts_tab(window: CapyWindow) -> None:
    _select(window, "PC-1")
    menu = QMenu()
    window.hosts._add_command_menus(menu)
    names = [a.text().replace("&", "") if a.text() else "—" for a in menu.actions()]
    assert names[-2:] == ["—", "Run a script…"] and "Scripts" not in names
    menu.actions()[-1].trigger()
    commands = _commands(window)
    assert commands.showing_scripts()
    assert _shown(commands) == ["gpupdate", "dns", "clock", "clean-temp", "repair"]
    assert commands.picked() is not None and commands.picked().id == "gpupdate"  # type: ignore[union-attr]
    commands.close()


def test_scripts_stay_out_of_the_commands_tab_even_in_a_search(window: CapyWindow) -> None:
    window.hosts.open_commands(_select(window, "PC-1"))
    commands = _commands(window)
    assert not commands.showing_scripts()
    assert "dns" not in _shown(commands) and "c-share" in _shown(commands)
    commands.search.setText("dns")
    assert _shown(commands) == []
    commands.tabs.setCurrentIndex(1)
    assert _shown(commands) == ["dns"]
    commands.close()


def test_a_script_that_worked_says_so_and_keeps_its_output_to_read(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[str] = []
    monkeypatch.setattr(window.hosts, "say", said.append)
    runs.answer = lambda: result(0, "Computer Policy update has completed successfully.\n")
    _run(window, "gpupdate")
    host, script, _account, timeout = runs.runs[0]
    assert (host, script.name, timeout) == ("192.0.2.1", "Update group policy", 600.0)
    assert said[0].startswith("Update group policy is running on PC-1 since ")
    strip = window.hosts.result_strip
    assert strip.text() == "Group policy updated on PC-1."
    assert strip.output_button.isVisibleTo(window.hosts)
    assert not strip._timer.isActive()  # there's output to read: it stays until closed
    opened = _answer(monkeypatch, lambda _d: ACCEPT)
    strip.output_button.click()
    assert isinstance(opened[0], OutputDialog)
    assert "has completed successfully" in opened[0].text.toPlainText()


def test_a_script_that_ended_with_an_error_code_says_so_in_red(
    window: CapyWindow, runs: FakeRuns
) -> None:
    runs.answer = lambda: result(1, "", "The time service has not been started.\n")
    _run(window, "clock")
    strip = window.hosts.result_strip
    assert strip.property("failed") is True
    assert strip.text() == (
        "Couldn't run <b>Sync the clock</b> on PC-1: it ended with code 1. Its output says why."
    )
    assert strip.output_button.isVisibleTo(window.hosts)


def test_a_blocked_run_says_security_software_may_have_stopped_it(
    window: CapyWindow, runs: FakeRuns
) -> None:
    def blocked() -> RunResult:
        raise RunError(Problem.BLOCKED, tried=["WMI: started, but never ran"])

    runs.answer = blocked
    _run(window, "dns")
    strip = window.hosts.result_strip
    assert strip.property("failed") is True
    assert "Security software on the PC may have stopped it" in strip.text()
    assert strip._output == "WMI: started, but never ran"


@pytest.mark.parametrize("command_id", ["repair", "clean-temp"])
def test_scripts_that_disturb_the_pc_ask_first(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch, command_id: str
) -> None:
    asked = _answer(monkeypatch, lambda _d: REJECT)
    _run(window, command_id)
    assert runs.runs == [] and len(asked) == 1
    _answer(monkeypatch, lambda _d: ACCEPT)
    _run(window, command_id)
    assert len(runs.runs) == 1


def test_repair_gets_two_hours(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer(monkeypatch, lambda _d: ACCEPT)
    _run(window, "repair")
    assert runs.runs[0][3] == builtin.REPAIR_TIMEOUT


def test_clean_temporary_files_says_how_much_it_freed(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer(monkeypatch, lambda _d: ACCEPT)
    runs.answer = lambda: result(0, "CAPYPANEL-CLEAN freed=536870912 files=3 left=1\n")
    _run(window, "clean-temp")
    strip = window.hosts.result_strip
    assert strip.text() == "Freed 512 MB on PC-1: 3 files deleted. 1 file in use stayed."
    assert not strip.output_button.isVisibleTo(window.hosts)  # nothing else to read


def test_a_script_still_running_isn_t_started_twice(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[str] = []
    monkeypatch.setattr(window.hosts, "say", said.append)
    target = _select(window, "PC-1")
    window.hosts.runner.run("dns", target, window.hosts.show_outcome)
    window.hosts.runner.run("dns", target, window.hosts.show_outcome)  # before the first ends
    _settle(window)
    assert len(runs.runs) == 1
    assert "Refresh DNS is still running on PC-1." in said


def test_the_commands_window_shows_a_script_s_output(window: CapyWindow, runs: FakeRuns) -> None:
    runs.answer = lambda: result(0, "Windows IP Configuration\nSuccessfully flushed.\n")
    window.hosts.open_commands(_select(window, "PC-1"), scripts=True)
    commands = _commands(window)
    row = next(r for r in commands.rows if r.command.id == "dns")
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    boxes = commands.results.findChildren(QPlainTextEdit)
    assert [b.toPlainText() for b in boxes] == ["Windows IP Configuration\nSuccessfully flushed."]
    commands.close()


def test_built_in_scripts_are_the_scripts_group() -> None:
    from capypanel.core.hosts import commands as host_commands

    group = [c.id for c in host_commands.COMMANDS if c.group is host_commands.Group.SCRIPTS]
    assert sorted(group) == sorted(builtin.BUILT_IN)
    assert all(host_commands.command(i).need is host_commands.Need.RUN for i in group)
