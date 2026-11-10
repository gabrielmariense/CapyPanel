import json
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from capypanel.core.remote import inventory, run
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.run import Engine, Language, Problem, RunAs, RunError, Runner, Script

PS = Script("check", Language.POWERSHELL, b"Write-Output 'hello'")


class FakePc:
    """The PC's side, played by the test: what each way in does when asked to start a run."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.ids: list[str] = []  # each run's id, in the order the runner made them
        self.asked: list[Engine] = []
        self.commands: list[Sequence[str]] = []
        self.answers: dict[Engine, Callable[[], None]] = {}

    def starter(self, engine: Engine) -> run.Starter:
        def start(host: str, command: Sequence[str], account: Account | None) -> None:
            self.asked.append(engine)
            self.commands.append(command)
            self.answers.get(engine, self.ran)()

        return start

    def ran(self, code: int = 0, out: bytes = b"done\r\n", err: bytes = b"") -> None:
        run_id = self.ids.pop(0)
        (self.folder / f"{run_id}.run").write_bytes(b"")
        (self.folder / f"{run_id}.out").write_bytes(out)
        (self.folder / f"{run_id}.err").write_bytes(err)
        answer = {"code": code, "error": "", "oem": 850}
        (self.folder / f"{run_id}.json").write_text(json.dumps(answer), encoding="utf-8")


@pytest.fixture
def pc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakePc:
    fake = FakePc(tmp_path / "pc")
    real = run.secrets.token_hex

    def token(n: int) -> str:
        value = real(n)
        fake.ids.append(value)
        return value

    monkeypatch.setattr(run.secrets, "token_hex", token)
    return fake


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def runner(
    pc: FakePc,
    *,
    psexec: Path | None = Path("PsExec64.exe"),
    winrm: bool = True,
    log_file: Path | None = None,
    clock: Clock | None = None,
) -> Runner:
    clock = clock or Clock()
    return Runner(
        lambda: psexec,
        log_file,
        starters={engine: pc.starter(engine) for engine in Engine},
        folder_of=lambda host: pc.folder,
        listens=lambda host, port: winrm,
        reachable=lambda host: None,
        clock=clock,
        sleep=clock.sleep,
        remote_folder=str(pc.folder),
    )


def test_a_run_returns_the_script_s_exit_code_and_output(pc: FakePc) -> None:
    result = runner(pc).run("DESK-01", PS)
    assert (result.engine, result.exit_code, result.output) == (Engine.WINRM, 0, "done\n")
    assert result.worked


def test_nothing_is_left_on_the_pc_after_a_run(pc: FakePc) -> None:
    runner(pc).run("DESK-01", Script("big", Language.BATCH, b"@echo off\r\necho hi\r\n"))
    assert list(pc.folder.iterdir()) == []


def test_nothing_is_left_on_the_pc_when_the_run_fails_either(pc: FakePc) -> None:
    def wrapper_failed() -> None:
        run_id = pc.ids[0]
        (pc.folder / f"{run_id}.run").write_bytes(b"")
        answer = {"code": None, "error": "This command cannot be run", "oem": 850}
        (pc.folder / f"{run_id}.json").write_text(json.dumps(answer), encoding="utf-8")

    pc.answers[Engine.WINRM] = wrapper_failed
    with pytest.raises(RunError) as caught:
        runner(pc).run("DESK-01", Script("x", Language.BATCH, b"echo"))
    assert caught.value.problem is Problem.NOT_STARTED
    assert list(pc.folder.iterdir()) == []


def test_winrm_comes_first_then_wmi_then_psexec(pc: FakePc) -> None:
    def fails() -> None:
        raise run._NotThisWay("no")

    pc.answers = {Engine.WINRM: fails, Engine.WMI: fails}
    assert runner(pc).run("DESK-01", PS).engine is Engine.PSEXEC
    assert pc.asked == [Engine.WINRM, Engine.WMI, Engine.PSEXEC]


def test_winrm_is_skipped_on_a_pc_that_doesn_t_listen_for_it(pc: FakePc) -> None:
    assert runner(pc, winrm=False).run("DESK-01", PS).engine is Engine.WMI
    assert pc.asked == [Engine.WMI]


def test_the_way_in_that_worked_is_tried_first_next_time(pc: FakePc) -> None:
    def fails() -> None:
        raise run._NotThisWay("no")

    pc.answers = {Engine.WINRM: fails, Engine.WMI: fails}
    runs = runner(pc)
    runs.run("DESK-01", PS)
    pc.asked.clear()
    runs.run("desk-01", PS)  # names are the same PC whatever their case
    assert pc.asked == [Engine.PSEXEC]
    assert runs.way_in("DESK-01") is Engine.PSEXEC


def test_without_psexec_a_pc_wmi_can_t_reach_has_no_way_in(pc: FakePc) -> None:
    def unreachable() -> None:
        raise RemoteError(Reason.UNREACHABLE, 1722)

    pc.answers = {Engine.WMI: unreachable}
    with pytest.raises(RunError) as caught:
        runner(pc, psexec=None, winrm=False).run("DESK-01", PS)
    assert caught.value.problem is Problem.NO_WAY_IN
    assert [t.split(":")[0] for t in caught.value.tried] == ["WinRM", "WMI", "PsExec"]


@pytest.mark.parametrize("reason", [Reason.REJECTED, Reason.NOT_ADMIN])
def test_a_refused_account_stops_before_another_way_tries_it(pc: FakePc, reason: Reason) -> None:
    def refused() -> None:
        raise RemoteError(reason, 1326)

    pc.answers = {Engine.WINRM: refused}
    with pytest.raises(RemoteError):
        runner(pc).run("DESK-01", PS)
    assert pc.asked == [Engine.WINRM]  # one try: the same password again could lock the account


def test_a_run_that_starts_but_never_runs_is_reported_as_blocked(pc: FakePc) -> None:
    pc.answers = {engine: lambda: None for engine in Engine}  # started; nothing ever shows
    clock = Clock()
    with pytest.raises(RunError) as caught:
        runner(pc, clock=clock).run("DESK-01", PS)
    assert caught.value.problem is Problem.BLOCKED
    assert pc.asked == list(Engine)  # another way in may get past what stopped the first
    assert clock.now >= 3 * run.START_GRACE


def test_a_run_with_no_answer_in_time_says_so(pc: FakePc) -> None:
    def started_only() -> None:
        (pc.folder / f"{pc.ids[0]}.run").write_bytes(b"")

    pc.answers[Engine.WINRM] = started_only
    with pytest.raises(RunError) as caught:
        runner(pc).run("DESK-01", PS, timeout=120)
    assert caught.value.problem is Problem.TIMED_OUT
    assert caught.value.engine is Engine.WINRM


def test_the_pc_s_share_refusing_the_account_is_an_account_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(folder: Path) -> None:
        raise PermissionError(13, "Access is denied", None, 5)

    monkeypatch.setattr(run.winsec, "make_admins_only", refused)
    runs = Runner(lambda: None, folder_of=lambda host: tmp_path, reachable=lambda host: None)
    with pytest.raises(RemoteError) as caught:
        runs.run("DESK-01", PS)
    assert caught.value.reason is Reason.REJECTED


def test_leftovers_are_swept_once_old_but_nothing_else(pc: FakePc) -> None:
    pc.folder.mkdir()
    old, recent, theirs = "a" * 16 + ".out", "b" * 16 + ".json", "notes.txt"
    for name in (old, recent, theirs):
        (pc.folder / name).write_bytes(b"x")
    long_ago = time.time() - run.SWEEP_AGE - 60
    os.utime(pc.folder / old, (long_ago, long_ago))
    os.utime(pc.folder / theirs, (long_ago, long_ago))
    runner(pc).run("DESK-01", PS)
    assert sorted(p.name for p in pc.folder.iterdir()) == [recent, theirs]


def test_every_run_goes_in_the_run_log_without_the_password(pc: FakePc, tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "me.runs.log"
    runs = runner(pc, log_file=log_file)
    runs.run("DESK-01", PS, Account("EXAMPLE\\admin", "s3cret"))
    pc.answers[Engine.WINRM] = lambda: (_ for _ in ()).throw(RemoteError(Reason.REJECTED, 1326))
    with pytest.raises(RemoteError):
        runs.run("DESK-02", PS)
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert [line.split("\t")[1:] for line in lines] == [
        ["DESK-01", "check", "WinRM", "EXAMPLE\\admin", "exit 0"],
        [
            "DESK-02",
            "check",
            "-",
            "(your Windows account)",
            "failed: rejected (Windows error 1326)",
        ],
    ]
    assert "s3cret" not in log_file.read_text(encoding="utf-8")


def test_a_full_run_log_moves_aside(tmp_path: Path) -> None:
    log_file = tmp_path / "me.runs.log"
    log_file.write_text("x" * (run.LOG_SIZE + 1), encoding="utf-8")
    run.append_line(log_file, "new")
    assert log_file.read_text(encoding="utf-8") == "new\n"
    assert log_file.with_name("me.runs.log.1").stat().st_size == run.LOG_SIZE + 1


@pytest.mark.parametrize(
    ("data", "text"),
    [
        ("Concluído\r\n".encode("cp850"), "Concluído\n"),  # the console's code page
        ("Concluído\r\n".encode("utf-16-le"), "Concluído\n"),  # sfc, without a BOM
        ("﻿ok".encode("utf-16-le"), "ok"),
        ("Concluído".encode(), "Concluído"),
    ],
)
def test_output_is_read_in_whatever_the_program_wrote(data: bytes, text: str) -> None:
    assert run.decode_output(data, 850) == text


def test_powershell_errors_sent_as_xml_read_as_plain_text() -> None:
    errors = (
        "#< CLIXML\n"
        '<Objs Version="1.1.0.1"><Obj S="progress" RefId="0"></Obj>'
        '<S S="Error">Access is denied_x000D__x000A_</S><S S="Error">at line 2_x000D__x000A_</S>'
        "</Objs>"
    )
    assert run._plain(errors) == "Access is denied\nat line 2\n"
    assert run._plain("plain\n") == "plain\n"


def test_quoted_values_stay_exactly_as_they_are() -> None:
    assert run._ps_quote("it's ‘x’") == "'it''s ‘‘x’’'"


def test_a_big_powershell_script_goes_as_a_file_and_a_utf8_one_gets_its_bom(
    pc: FakePc, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "COMMAND_LIMIT", 100)
    copied: list[bytes] = []

    def copy_then_run() -> None:
        copied.extend(p.read_bytes() for p in pc.folder.glob("*.ps1"))
        pc.ran()

    pc.answers[Engine.WINRM] = copy_then_run
    runner(pc).run("DESK-01", Script("x", Language.POWERSHELL, "'Olá'".encode()))
    assert copied == [b"\xef\xbb\xbf" + "'Olá'".encode()]


# ---- the wrapper itself, run by this PC's own PowerShell instead of on another PC ----


def _local_runner(folder: Path) -> Runner:
    def start(host: str, command: Sequence[str], account: Account | None) -> None:
        subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)  # like WMI: no wait

    return Runner(
        lambda: None,
        starters={engine: start for engine in Engine},
        folder_of=lambda host: folder,
        listens=lambda host, port: True,
        reachable=lambda host: None,
        remote_folder=str(folder),
    )


def test_the_wrapper_runs_a_powershell_script_with_its_arguments(tmp_path: Path) -> None:
    code = b"param($a, $b)\nWrite-Output \"$a|$b\"\n[Console]::Error.WriteLine('careful')\nexit 3"
    script = Script("x", Language.POWERSHELL, code, ("DESK-01", 'it\'s "two" words'))
    result = _local_runner(tmp_path).run("DESK-01", script, timeout=60)
    assert result.exit_code == 3
    assert result.output == 'DESK-01|it\'s "two" words\n'
    assert result.errors == "careful\n"
    assert list(tmp_path.iterdir()) == []


def test_the_wrapper_runs_a_batch_file_with_its_arguments(tmp_path: Path) -> None:
    code = b"@echo off\r\necho %~1 and %~2\r\nexit /b 2\r\n"
    script = Script("x", Language.BATCH, code, ("DESK-01", "two words"))
    result = _local_runner(tmp_path).run("DESK-01", script, timeout=60)
    assert (result.exit_code, result.output) == (2, "DESK-01 and two words\n")


def test_the_wrapper_runs_a_big_script_from_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run, "COMMAND_LIMIT", 100)
    code = 'param($a)\nWrite-Output "Olá $a"'.encode()
    script = Script("x", Language.POWERSHELL, code, ("DESK-01",))
    result = _local_runner(tmp_path).run("DESK-01", script, timeout=60)
    assert (result.exit_code, result.output) == (0, "Olá DESK-01\n")


def test_a_second_start_of_the_same_run_does_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "pc"
    folder.mkdir()
    runs = _local_runner(folder)
    command = runs._command(folder, "c" * 16, PS)
    (folder / ("c" * 16 + ".run")).write_bytes(b"")  # the first start got there first
    subprocess.run(command, creationflags=subprocess.CREATE_NO_WINDOW, timeout=60)
    assert sorted(p.name for p in folder.iterdir()) == ["c" * 16 + ".run"]


# ---- Run as ----


def _wrapper_text(command: Sequence[str]) -> str:
    """The wrapper a command carries, unpacked: what the PC would run."""
    import base64
    import re
    import zlib

    loader = base64.b64decode(command[-1]).decode("utf-16-le")
    packed = re.search(r"FromBase64String\('([^']+)'\)", loader)
    assert packed is not None
    return zlib.decompress(base64.b64decode(packed[1]), -15).decode("utf-8")


def test_running_as_the_signed_in_person_needs_their_name(pc: FakePc) -> None:
    with pytest.raises(ValueError):
        runner(pc).run("DESK-01", PS, run_as=RunAs.USER)


def test_as_the_account_the_wrapper_starts_the_script_itself(tmp_path: Path) -> None:
    text = _wrapper_text(_local_runner(tmp_path)._command(tmp_path, "c" * 16, PS))
    assert "Start-Process" in text and "Schedule.Service" not in text


def test_as_the_signed_in_person_a_hidden_task_in_their_session_runs_it(tmp_path: Path) -> None:
    runs = _local_runner(tmp_path)
    script = Script("x", Language.BATCH, b"echo hi")
    text = _wrapper_text(runs._command(tmp_path, "c" * 16, script, RunAs.USER, "EXAMPLE\ana"))
    assert "'EXAMPLE\ana'" in text and "InteractiveToken" in text
    assert "wscript.exe" in text and "icacls.exe" in text  # hidden, and only this run's files
    assert "DeleteTask" in text


def test_the_run_log_says_who_it_ran_as(pc: FakePc, tmp_path: Path) -> None:
    log_file = tmp_path / "me.runs.log"
    runner(pc, log_file=log_file).run("DESK-01", PS, run_as=RunAs.SYSTEM)
    assert log_file.read_text(encoding="utf-8").split("\t")[4] == "(your Windows account) as SYSTEM"


@pytest.mark.skipif(
    not os.environ.get("GITHUB_ACTIONS"),
    reason="makes a scheduled task as SYSTEM: only on CI's throwaway machine",
)
def test_as_system_a_scheduled_task_runs_it(tmp_path: Path) -> None:
    script = Script("x", Language.POWERSHELL, b"Write-Output ([Environment]::UserName); exit 4")
    result = _local_runner(tmp_path).run("DESK-01", script, timeout=120, run_as=RunAs.SYSTEM)
    assert (result.exit_code, result.output.strip().upper()) == (4, "SYSTEM")


def test_winrm_is_skipped_when_powershell_isnt_used_on_this_pc(
    pc: FakePc, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WinRM starts a PowerShell on this PC: never with WMI directly pinned, nor once Windows
    refused to start it this session."""
    monkeypatch.setattr(inventory, "transport", inventory.DIRECT)
    assert runner(pc).run("DESK-01", PS).engine is Engine.WMI
    assert pc.asked == [Engine.WMI]
    monkeypatch.setattr(inventory, "transport", inventory.AUTO)
    monkeypatch.setattr(inventory, "powershell_blocked", True)
    pc.asked.clear()
    assert runner(pc).run("DESK-02", PS).engine is Engine.WMI
    monkeypatch.setattr(inventory, "powershell_blocked", False)
    pc.asked.clear()
    assert runner(pc).run("DESK-03", PS).engine is Engine.WINRM  # as before
