import subprocess
from pathlib import Path

import pytest

from capypanel.core.ssh import launch
from capypanel.core.ssh.host import SshInfo

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


@pytest.mark.parametrize("address", ["srv-01", "192.0.2.40", "2001:db8::40", "srv.corp.example"])
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


def test_connect_starts_ssh_exe_in_a_console_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    launch.connect("srv-01", SshInfo(login="root"))
    [(argv, kw)] = started
    assert argv == [str(EXE), "-l", "root", "--", "srv-01"]
    assert kw["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    assert "stdout" not in kw  # the console shows it to the person; CapyPanel reads nothing


def test_nothing_starts_for_an_address_it_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[object] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: started.append(a))
    with pytest.raises(ValueError):
        launch.connect("-oProxyCommand=calc", SshInfo())
    assert started == []
