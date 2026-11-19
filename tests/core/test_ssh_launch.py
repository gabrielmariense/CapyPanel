import os
import subprocess
import sys
from pathlib import Path

import pytest

from capypanel.core import i18n
from capypanel.core.ssh import launch
from capypanel.core.ssh.host import SshInfo
from capypanel.core.ssh.launch import Running
from capypanel.core.updates import NO_SPLASH

EXE = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")


def test_the_default_port_and_an_empty_login_are_left_to_ssh_exe() -> None:
    assert launch.command_line(EXE, "srv-01", SshInfo()) == [str(EXE), "--", "srv-01"]


def test_the_port_and_login_go_before_the_end_of_options() -> None:
    argv = launch.command_line(EXE, "192.0.2.40", SshInfo(port=2222, login="EXAMPLE\\user"))
    assert argv == [str(EXE), "-p", "2222", "-l", "EXAMPLE\\user", "--", "192.0.2.40"]


@pytest.mark.parametrize(
    "address", ["", "-oProxyCommand=calc", "two words", "tab\there", "nul\x00", "x" * 254]
)
def test_an_address_ssh_exe_would_misread_is_refused(address: str) -> None:
    assert not launch.is_destination(address)
    with pytest.raises(ValueError):
        launch.command_line(EXE, address, SshInfo())


@pytest.mark.parametrize("info", [SshInfo(login="-oProxyCommand=calc"), SshInfo(port=0)])
def test_a_login_or_port_ssh_exe_would_misread_is_refused(info: SshInfo) -> None:
    # SshInfo straight from code: info_of() never makes these, but the last check is here.
    with pytest.raises(ValueError):
        launch.command_line(EXE, "srv-01", info)


@pytest.mark.parametrize("char", "\"$&'(),;<>\\`{|}")
def test_an_address_with_a_character_ssh_exe_9_5_refuses_is_refused(char: str) -> None:
    # Windows' own ssh.exe 9.5 refuses these in a host name; an older one (Windows 10's 8.1)
    # passes them on to a ProxyCommand that names the host (%h), which runs in a shell.
    assert not launch.is_destination(f"srv{char}calc")
    with pytest.raises(ValueError):
        launch.command_line(EXE, f"srv{char}calc", SshInfo())


@pytest.mark.parametrize(
    "address",
    ["srv-01", "192.0.2.40", "2001:db8::40", "srv.corp.example", "user@srv-01", "fe80::1%3"],
)
def test_names_and_addresses_ssh_exe_takes(address: str) -> None:
    assert launch.is_destination(address)


def test_ssh_exe_is_windows_own_never_one_found_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "ssh.exe").touch()
    monkeypatch.setenv("PATH", str(elsewhere))
    monkeypatch.setenv("SYSTEMROOT", str(tmp_path / "Windows"))
    assert launch.ssh_exe() is None  # not installed: the one on PATH doesn't count
    own = tmp_path / "Windows" / "System32" / "OpenSSH" / "ssh.exe"
    own.parent.mkdir(parents=True)
    own.touch()
    assert launch.ssh_exe() == own


def test_connect_says_when_ssh_exe_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "ssh_exe", lambda: None)
    with pytest.raises(launch.SshMissing):
        launch.connect("srv-01", SshInfo())


def test_connect_starts_the_holder_with_ssh_exe_s_command_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    monkeypatch.setattr(i18n, "language", lambda: "pt_BR")
    launch.connect("192.0.2.41", SshInfo(login="root"), "nas-01")
    [(argv, kw)] = started
    assert argv == [
        *launch.own_start(), "--ssh-holder", "--lang=pt_BR", "--host=nas-01",
        "--", str(EXE), "-l", "root", "--", "192.0.2.41",
    ]  # fmt: skip
    # No console of CapyPanel's, nor a new process group (it would start ignoring Ctrl+C):
    # the holder opens its own window.
    assert kw["creationflags"] == subprocess.DETACHED_PROCESS
    assert "stdout" not in kw and "stdin" not in kw  # CapyPanel reads and types nothing
    env = kw["env"]
    assert isinstance(env, dict) and env[NO_SPLASH] == "1"


def test_without_a_name_the_window_calls_the_host_by_its_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    launch.connect("srv-01", SshInfo())
    assert "--host=srv-01" in started[0]


def test_capypanel_starts_itself_by_its_exe_or_from_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert launch.own_start() == [sys.executable, "-m", "capypanel"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert launch.own_start() == [sys.executable]


def test_open_windows_are_this_exe_s_other_copies_in_this_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exe = tmp_path / "CapyPanel" / "CapyPanel.exe"
    other = tmp_path / "Elsewhere" / "CapyPanel.exe"
    for path in (exe, other):
        path.parent.mkdir()
        path.touch()
    me = os.getpid()
    running = [
        Running(me, str(exe), 1),  # CapyPanel itself
        Running(101, str(exe), 1),  # a holder
        Running(102, str(exe).upper(), 1),  # a holder, its path as Windows may spell it
        Running(103, str(exe), 2),  # another person's session
        Running(104, str(other), 1),  # another copy's: its files aren't the ones replaced
        Running(105, "", 1),  # Windows wouldn't say
    ]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(launch, "_running", lambda name: running if name == exe.name else [])
    monkeypatch.setattr(launch, "_session", lambda pid: 1)
    assert launch.open_windows() == 2


def test_from_source_no_window_holds_files_an_update_replaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launch, "_running", lambda name: pytest.fail("never looked"))
    assert launch.open_windows() == 0


def test_windows_list_of_processes_has_this_one() -> None:
    # The real list, read only: this test's own process is in it, with its path and session.
    me = [r for r in launch._running(Path(sys.executable).name) if r.pid == os.getpid()]
    if not me:  # a venv's python.exe starts the real one: look for that one instead
        exe = Path(launch._image_path(os.getpid()))
        me = [r for r in launch._running(exe.name) if r.pid == os.getpid()]
    [found] = me
    assert Path(found.path).is_file() and found.session == launch._session(os.getpid())


def test_nothing_starts_for_an_address_it_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[object] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(ValueError):
        launch.connect("-oProxyCommand=calc", SshInfo())
    assert started == []
