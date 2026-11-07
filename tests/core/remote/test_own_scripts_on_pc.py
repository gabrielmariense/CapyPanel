"""Files on the PC (.onpc): reading the path, and the launcher, run here with PowerShell on files
in a temporary folder; nothing reaches the network."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from capypanel.core.remote import own_scripts
from capypanel.core.remote.own_scripts import Approval, PcProblem, State
from capypanel.core.remote.run import RunAs


@pytest.mark.parametrize(
    ("text", "path"),
    [
        (b"C:\\ProgramData\\Scripts\\printers.cmd", "C:\\ProgramData\\Scripts\\printers.cmd"),
        (b'# the printers\r\n\r\n"%ProgramData%\\Fix it.PS1"\r\n', "%ProgramData%\\Fix it.PS1"),
        (b"\xef\xbb\xbfD:\\Tools\\a.bat", "D:\\Tools\\a.bat"),
        (b"\\\\FS01\\share\\a.cmd", ""),  # a share, not the PC
        (b"C:\\Tools\\setup.exe", ""),
        (b"printers.cmd", ""),
        (b"", ""),
    ],
)
def test_the_path_on_the_pc(text: bytes, path: str) -> None:
    assert own_scripts.pc_path(text) == path


def test_a_onpc_file_is_listed_and_one_with_no_path_says_so(tmp_path: Path) -> None:
    (tmp_path / "Printers.onpc").write_bytes(b"C:\\Scripts\\printers.cmd")
    (tmp_path / "Broken.onpc").write_bytes(b"just words")
    found = {s.name: s for s in own_scripts.scan(tmp_path, {})}
    assert found["Printers"].state is State.NEW
    assert found["Printers"].on_pc == "C:\\Scripts\\printers.cmd"
    assert found["Broken"].state is State.NO_PATH


def _ready(tmp_path: Path, target: Path) -> own_scripts.OwnScript:
    pointer = tmp_path / "Run it.onpc"
    pointer.write_bytes(str(target).encode())
    digest = hashlib.sha256(pointer.read_bytes()).hexdigest()
    found = own_scripts.read(pointer, Approval(digest, risky=False, arguments='"a b"'))
    assert found.ready
    return found


def _launch(script: own_scripts.OwnScript, run_as: RunAs, tmp_path: Path) -> tuple[int, str]:
    """The launcher as the run layer sends it, run here: the host name and arguments after it."""
    sent = own_scripts.to_script(script, "PC-1", run_as)
    launcher = tmp_path / "launch.ps1"
    launcher.write_bytes(b"\xef\xbb\xbf" + sent.code)
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(launcher), *sent.arguments],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    return done.returncode, done.stdout


def _target(tmp_path: Path) -> Path:
    folder = tmp_path / "pc"
    folder.mkdir()
    target = folder / "printers.cmd"
    target.write_bytes(b"@echo off\r\necho host=%1 then=%2\r\nexit /b 3\r\n")
    return target


def test_the_launcher_runs_the_pc_s_file_with_its_arguments(tmp_path: Path) -> None:
    script = _ready(tmp_path, _target(tmp_path))
    code, output = _launch(script, RunAs.SYSTEM, tmp_path)
    assert 'host=PC-1 then="a b"' in output
    assert code == 3  # the file's own exit code


def test_a_file_every_user_can_change_doesn_t_run_as_admin_or_system(tmp_path: Path) -> None:
    target = _target(tmp_path)
    subprocess.run(["icacls", str(target), "/grant", "*S-1-5-11:M"], check=True,
                   capture_output=True)  # fmt: skip
    script = _ready(tmp_path, target)
    for run_as in (RunAs.SYSTEM, RunAs.ACCOUNT):
        code, output = _launch(script, run_as, tmp_path)
        assert code == 1 and own_scripts.pc_problem(output) is PcProblem.OPEN
        assert "host=" not in output
    code, output = _launch(script, RunAs.USER, tmp_path)  # the person runs only what they could
    assert "host=PC-1" in output


def test_a_folder_every_user_can_empty_counts_too(tmp_path: Path) -> None:
    target = _target(tmp_path)
    subprocess.run(["icacls", str(target.parent), "/grant", "*S-1-1-0:(DC)"], check=True,
                   capture_output=True)  # fmt: skip
    code, output = _launch(_ready(tmp_path, target), RunAs.SYSTEM, tmp_path)
    assert own_scripts.pc_problem(output) is PcProblem.OPEN


def test_a_missing_file_says_so(tmp_path: Path) -> None:
    script = _ready(tmp_path, tmp_path / "nowhere" / "printers.cmd")
    code, output = _launch(script, RunAs.SYSTEM, tmp_path)
    assert code == 1 and own_scripts.pc_problem(output) is PcProblem.MISSING
