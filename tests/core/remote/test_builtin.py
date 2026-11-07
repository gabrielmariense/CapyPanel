"""The built-in scripts. Their PowerShell runs here for real only where it's harmless: the output
helper with cmd's echo, and Clean temporary files on a test folder instead of the PC's Temp
folders. The others (gpupdate, ipconfig, w32tm, DISM, sfc) change the PC, so they're only read."""

import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from capypanel.core.remote import builtin
from capypanel.core.remote.access import Account
from capypanel.core.remote.run import Engine, Language, Runner, RunResult, Script


def _run_here(folder: Path, code: str) -> RunResult:
    """Runs `code` through the real wrapper with this PC's own PowerShell, in `folder`."""

    def start(host: str, command: Sequence[str], account: Account | None) -> None:
        subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)

    runs = Runner(
        lambda: None,
        starters={engine: start for engine in Engine},
        folder_of=lambda host: folder,
        listens=lambda host, port: True,
        reachable=lambda host: None,
        remote_folder=str(folder),
    )
    return runs.run("DESK-01", Script("test", Language.POWERSHELL, code.encode()), timeout=60)


def test_output_keeps_each_line_s_last_state_without_progress_bars(tmp_path: Path) -> None:
    said = tmp_path / "said.txt"  # what DISM and sfc write: a bar, a line redrawn with \r
    said.write_bytes(b"[====10.0%====]\r\nVerifying 5 percent\rVerifying all\r\ndone\r\n")
    code = builtin._RUN + f"Run cmd.exe '/c', 'type {said}& exit /b 3'\nexit $LASTEXITCODE\n"
    result = _run_here(tmp_path / "run", code)
    assert result.exit_code == 3
    assert result.output.splitlines() == ["Verifying all", "done"]


def test_clean_deletes_old_temporary_files_only(tmp_path: Path) -> None:
    temp, ours, elsewhere = tmp_path / "Temp", tmp_path / "Temp" / "CapyPanel", tmp_path / "x"
    for folder in (temp / "sub", ours, elsewhere):
        folder.mkdir(parents=True)
    old = time.time() - 3 * 24 * 60 * 60
    files = {
        "old": temp / "old.tmp", "deep": temp / "sub" / "old.log", "new": temp / "new.tmp",
        "ours": ours / ("a" * 16 + ".out"), "elsewhere": elsewhere / "keep.txt",
    }  # fmt: skip
    for name, file in files.items():
        file.write_bytes(b"x" * 100)
        if name != "new":
            os.utime(file, (old, old))
    link = temp / "link"  # a junction to a folder outside Temp: never followed
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(elsewhere)], check=True,
                   capture_output=True)  # fmt: skip
    code = builtin._CLEAN
    start = code.index("$ours = ")
    end = code.index("$script:freed")
    code = code[:start] + f"$ours = '{ours}'\n$roots = @('{temp}')\n" + code[end:]
    result = _run_here(tmp_path / "run", code)
    found, rest = builtin.cleaned(result.output)
    assert found == builtin.Cleaned(freed=200, files=2, left=0)
    assert rest == ""
    assert sorted(n for n, f in files.items() if f.exists()) == ["elsewhere", "new", "ours"]
    assert (temp / "sub").is_dir()  # emptied, but made just now: it may be in use


def test_cleaned_reads_its_line_and_leaves_the_rest() -> None:
    output = "warning: one\nCAPYPANEL-CLEAN freed=10 files=2 left=1\n"
    assert builtin.cleaned(output) == (builtin.Cleaned(10, 2, 1), "warning: one")
    assert builtin.cleaned("nothing") == (None, "nothing")


def test_every_built_in_script_is_powershell_that_ends_with_its_exit_code() -> None:
    for command_id, built in builtin.BUILT_IN.items():
        code = built.script.code.decode()
        assert built.script.language is Language.POWERSHELL
        assert (
            command_id == "clean-temp"
            or code.rstrip().endswith("exit $LASTEXITCODE")
            or ("exit $sfc" in code)
        )
