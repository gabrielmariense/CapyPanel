"""Your own scripts: the scripts folder in Settings, the Scripts tab's Your scripts, Review…, the
risk question, Run as and the checks before a run. The run on the PC is replaced: nothing here
reaches the network or runs anything."""

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import own_scripts
from capypanel.core.remote.access import Account
from capypanel.core.remote.own_scripts import State
from capypanel.core.remote.run import Engine, RunAs, RunResult, Script
from capypanel.core.remote.sessions import Session
from capypanel.ui.hosts_tool import command_windows, commands_window, runner
from capypanel.ui.hosts_tool.commands_window import CommandRow, CommandsWindow
from capypanel.ui.hosts_tool.runner import HostTarget
from capypanel.ui.hosts_tool.script_review import ReviewDialog

ACCEPT, REJECT = QDialog.DialogCode.Accepted, QDialog.DialogCode.Rejected


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, office = HostList().add_group("Office")
    hl, _host = hl.add_host("PC-1", office.id, address="192.0.2.1")
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


@pytest.fixture
def folder(window: CapyWindow, tmp_path: Path) -> Path:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "Reset printers.ps1").write_text('param($PC) Write-Output "hi $PC"\n')
    (scripts / "Fix.cmd").write_text("@echo off\r\necho fixed\r\n")
    window.hosts.own_scripts.set_folder(scripts)
    _settle(window)
    return scripts


class FakeRuns:
    def __init__(self) -> None:
        self.runs: list[tuple[str, Script, RunAs, str]] = []
        self.answer: Callable[[], RunResult] = lambda: RunResult(Engine.WMI, 0, "ok\n", "", 1.0)

    def run(
        self,
        host: str,
        script: Script,
        account: Account | None = None,
        timeout: float = 0,
        run_as: RunAs = RunAs.ACCOUNT,
        user: str = "",
    ) -> RunResult:
        self.runs.append((host, script, run_as, user))
        return self.answer()


@pytest.fixture
def runs(window: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> FakeRuns:
    fake = FakeRuns()
    monkeypatch.setattr(window.hosts.runner, "scripts", fake)
    return fake


def _settle(win: CapyWindow) -> None:
    for _ in range(500):
        QApplication.processEvents()
        if not win.hosts.runner.busy() and not win.hosts.own_scripts.scanning:
            QApplication.processEvents()
            return
    pytest.fail("never finished")


def _answer(monkeypatch: pytest.MonkeyPatch, answer: Callable[[QDialog], Any]) -> list[QDialog]:
    opened: list[QDialog] = []

    def run(dialog: QDialog) -> Any:
        opened.append(dialog)
        return answer(dialog)

    for module in (runner, command_windows, commands_window):
        monkeypatch.setattr(module, "run_modal", run)
    return opened


def _target(win: CapyWindow) -> HostTarget:
    assert win.hosts.document is not None
    host = win.hosts.document.hosts.hosts[0]
    win.hosts.table.select_ids([host.id])
    target = win.hosts.selected_target()
    assert target is not None
    return target


def _open(win: CapyWindow) -> CommandsWindow:
    win.hosts.open_commands(_target(win), scripts=True)
    commands = win.hosts._commands_window  # pyright: ignore[reportPrivateUsage]
    assert isinstance(commands, CommandsWindow)
    return commands


def _row(commands: CommandsWindow, name: str) -> CommandRow:
    return next(r for r in commands.rows if r.script is not None and r.script.name == name)


def _approve(risky: bool, arguments: str = "", run_as: RunAs = RunAs.ACCOUNT,
             locked: bool = False) -> Callable[[QDialog], Any]:  # fmt: skip
    def answer(dialog: QDialog) -> Any:
        assert isinstance(dialog, ReviewDialog)
        assert not dialog.approve.isEnabled()  # the risk question has no default
        (dialog.risky if risky else dialog.safe).setChecked(True)
        dialog.arguments.setText(arguments)
        dialog.run_as.setCurrentIndex(dialog.run_as.findData(run_as))
        dialog.locked.setChecked(locked)
        assert dialog.approve.isEnabled()
        return ACCEPT

    return answer


def test_no_folder_says_where_to_choose_one(window: CapyWindow) -> None:
    commands = _open(window)
    assert "Settings › Hosts › General" in commands._own_hint.text()  # pyright: ignore[reportPrivateUsage]
    assert not [r for r in commands.rows if r.script is not None]


def test_new_scripts_show_under_your_scripts_and_need_a_review(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    shown = [r.command.name for r in commands.rows if not r.isHidden() and r.script]
    assert shown == ["Fix", "Reset printers"]
    row = _row(commands, "Fix")
    assert "new, review before use" in row.name.text()
    opened = _answer(monkeypatch, lambda _d: REJECT)
    commands.pick(row)
    commands.run(row.command)  # Run is Review… until it's approved
    assert isinstance(opened[0], ReviewDialog)
    assert "echo fixed" in opened[0].code.toPlainText()
    assert runs.runs == []


def test_an_approved_script_runs_with_the_host_and_its_arguments(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(False, '-Queue "Front desk"'))
    commands.review(_row(commands, "Reset printers").script)  # type: ignore[arg-type]
    _settle(window)
    row = _row(commands, "Reset printers")
    assert row.script is not None and row.script.ready
    assert not row.command.risky
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    [(host, script, run_as, _user)] = runs.runs
    assert host == "192.0.2.1" and run_as is RunAs.ACCOUNT
    assert script.arguments == ("PC-1", "-Queue", "Front desk")
    assert script.code == (folder / "Reset printers.ps1").read_bytes()
    outcomes = commands._outcomes  # pyright: ignore[reportPrivateUsage]
    outcome = outcomes[(_target(window).key, row.command.id)]
    assert "finished on" in outcome.text and outcome.output == "ok"


def test_a_risky_script_asks_before_every_run(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(True))
    commands.review(_row(commands, "Fix").script)  # type: ignore[arg-type]
    _settle(window)
    row = _row(commands, "Fix")
    assert row.command.risky
    asked = _answer(monkeypatch, lambda _d: REJECT)
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    assert len(asked) == 1 and runs.runs == []


def test_a_script_changed_after_approval_doesn_t_run(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(False))
    commands.review(_row(commands, "Fix").script)  # type: ignore[arg-type]
    _settle(window)
    row = _row(commands, "Fix")
    (folder / "Fix.cmd").write_text("@echo off\r\nformat C:\r\n")  # after the scan
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    assert runs.runs == []
    again = _row(commands, "Fix")
    assert again.script is not None and again.script.state is State.CHANGED


def test_run_as_the_signed_in_person_names_them(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(False, run_as=RunAs.USER, locked=True))
    commands.review(_row(commands, "Fix").script)  # type: ignore[arg-type]
    _settle(window)
    row = _row(commands, "Fix")
    assert row.run_as is not None and not row.run_as.isEnabled()  # locked
    target = _target(window)
    ana = Session("ana", "EXAMPLE", "console", "active", None, session_id=1)
    window.hosts.keep_users(target.key, (ana,), None)
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    [(_host, _script, run_as, user)] = runs.runs
    assert run_as is RunAs.USER and user == "EXAMPLE\\ana"


def test_no_one_signed_in_means_no_run_as_them(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(False, run_as=RunAs.USER))
    commands.review(_row(commands, "Fix").script)  # type: ignore[arg-type]
    _settle(window)
    window.hosts.keep_users(_target(window).key, (), None)
    row = _row(commands, "Fix")
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    assert runs.runs == []


def test_an_unlocked_choice_can_change_for_one_run(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window)
    _answer(monkeypatch, _approve(False))
    commands.review(_row(commands, "Fix").script)  # type: ignore[arg-type]
    _settle(window)
    row = _row(commands, "Fix")
    assert row.run_as is not None and row.run_as.isEnabled()
    row.run_as.setCurrentIndex(row.run_as.findData(RunAs.SYSTEM))
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    assert runs.runs[0][2] is RunAs.SYSTEM


def test_a_file_every_user_can_change_can_t_be_approved(
    window: CapyWindow, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["icacls", str(folder / "Fix.cmd"), "/grant", "*S-1-5-11:M"], check=True,
                   capture_output=True)  # fmt: skip
    window.hosts.own_scripts.rescan()
    _settle(window)
    commands = _open(window)
    row = _row(commands, "Fix")
    assert "every user can change it" in row.name.text()
    opened = _answer(monkeypatch, lambda _d: REJECT)
    commands.run(row.command)
    dialog = opened[0]
    assert isinstance(dialog, ReviewDialog)
    dialog.safe.setChecked(True)
    assert not dialog.approve.isEnabled()


def test_an_open_quote_blocks_approving(window: CapyWindow, folder: Path) -> None:
    script = window.hosts.own_scripts.scripts[0]
    dialog = ReviewDialog(None, script)
    dialog.safe.setChecked(True)
    dialog.arguments.setText('-Name "Front')
    assert not dialog.approve.isEnabled() and not dialog.problem.isHidden()


def test_approvals_are_kept_in_the_settings(window: CapyWindow, folder: Path) -> None:
    from capypanel.core.remote.own_scripts import Approval

    script = window.hosts.own_scripts.scripts[0]
    window.hosts.own_scripts.approve(script, Approval(script.digest, True, "-X"))
    _settle(window)
    kept = window.hosts.prefs["script_approvals"]
    assert kept["fix.cmd"]["risky"] is True and kept["fix.cmd"]["sha256"] == script.digest
    assert window.hosts.own_scripts.scripts[0].ready


def test_the_commands_tab_shows_none_of_your_scripts(window: CapyWindow, folder: Path) -> None:
    commands = _open(window)
    commands.tabs.setCurrentIndex(0)
    assert not [r for r in commands.rows if r.script is not None and not r.isHidden()]


def test_a_file_on_the_pc_runs_through_a_launcher_and_says_when_it_was_refused(
    window: CapyWindow, folder: Path, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    (folder / "PC printers.onpc").write_bytes(b"%ProgramData%\\Scripts\\printers.cmd\r\n")
    window.hosts.own_scripts.rescan()
    _settle(window)
    commands = _open(window)
    read: list[tuple[str, str]] = []

    def pc_copy(host: str, on_pc: str, _account: object) -> bytes:
        read.append((host, on_pc))
        return b"@echo off\r\necho front desk printers\r\n"

    monkeypatch.setattr(own_scripts, "read_pc_copy", pc_copy)
    opened = _answer(monkeypatch, _approve(False, run_as=RunAs.SYSTEM))
    commands.review(_row(commands, "PC printers").script)  # type: ignore[arg-type]
    _settle(window)
    assert read == [("192.0.2.1", "%ProgramData%\\Scripts\\printers.cmd")]
    review = opened[0]
    assert isinstance(review, ReviewDialog)
    assert "front desk printers" in review.code.toPlainText()  # the PC's copy, to read
    _settle(window)
    row = _row(commands, "PC printers")
    assert row.script is not None and row.script.approval is not None
    reviewed = own_scripts.fingerprint(b"@echo off\r\necho front desk printers\r\n")
    assert row.script.approval.pc_digest == reviewed
    assert "%ProgramData%" in row.about.text()
    runs.answer = lambda: RunResult(Engine.WMI, 1, "CAPYPANEL-ONPC open\n", "", 1.0)
    commands.pick(row)
    commands.run(row.command)
    _settle(window)
    [(_host, script, run_as, _user)] = runs.runs
    assert run_as is RunAs.SYSTEM and b"printers.cmd" in script.code
    assert reviewed.encode() in script.code  # the launcher knows the reviewed copy
    assert script.arguments == ("PC-1",)
    outcomes = commands._outcomes  # pyright: ignore[reportPrivateUsage]
    outcome = outcomes[(_target(window).key, row.command.id)]
    assert outcome.failed and "every user of that PC can change" in outcome.text
