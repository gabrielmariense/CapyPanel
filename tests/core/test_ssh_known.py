import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from capypanel.core.ssh import known, launch
from capypanel.core.ssh.host import SshInfo


class FakeSsh:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.ssh = folder / "OpenSSH" / "ssh.exe"
        self.ssh.parent.mkdir()
        self.ssh.touch()
        self.keygen = self.ssh.with_name("ssh-keygen.exe")
        self.keygen.touch()
        self.users = folder / "Ana Maria" / ".ssh"
        self.users.mkdir(parents=True)
        self.settings = {
            "hostname": "192.0.2.40",
            "port": "22",
            "stricthostkeychecking": "ask",
            "userknownhostsfile": f"{self.users}/known_hosts {self.users}/known_hosts2",
            "globalknownhostsfile": r"__PROGRAMDATA__\ssh/ssh_known_hosts",
        }
        self.known: dict[str, set[str]] = {}
        self.runs: list[list[str]] = []
        self.ssh_code = 0
        self.keygen_code: int | None = None

    def known_hosts(self, name: str = "known_hosts", *names: str) -> Path:
        path = self.users / name
        path.touch()
        self.known[str(path)] = set(names)
        return path

    def run(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        argv = list(argv)
        self.runs.append(argv)
        assert kwargs["creationflags"] == 0x08000000 and kwargs["stdin"] == subprocess.DEVNULL
        if argv[0] == str(self.ssh):
            text = "".join(f"{key} {value}\n" for key, value in self.settings.items())
            return subprocess.CompletedProcess(argv, self.ssh_code, text.encode("utf-8"), b"")
        assert argv[0] == str(self.keygen) and argv[1] == "-F" and argv[3] == "-f"
        if self.keygen_code is not None:
            code = self.keygen_code
        else:
            code = 0 if argv[2] in self.known.get(argv[4], set()) else 1
        return subprocess.CompletedProcess(argv, code, b"", b"")

    def looked_up(self) -> list[tuple[str, str]]:
        return [(argv[2], argv[4]) for argv in self.runs if argv[0] == str(self.keygen)]


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeSsh:
    made = FakeSsh(tmp_path)
    monkeypatch.setattr(launch, "ssh_exe", lambda: made.ssh)
    monkeypatch.setattr(known.subprocess, "run", made.run)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    return made


def test_a_server_in_no_known_hosts_file_is_one_ssh_exe_asks_about(fake: FakeSsh) -> None:
    fake.known_hosts("known_hosts", "198.51.100.7")
    assert known.asks_to_trust("192.0.2.40", SshInfo())
    assert fake.runs[0] == [str(fake.ssh), "-G", "--", "192.0.2.40"]
    assert fake.looked_up() == [("192.0.2.40", str(fake.users / "known_hosts"))]


def test_a_server_already_known_gets_no_question(fake: FakeSsh) -> None:
    fake.known_hosts("known_hosts", "192.0.2.40")
    assert not known.asks_to_trust("192.0.2.40", SshInfo())


def test_every_known_hosts_file_counts_the_global_one_too(fake: FakeSsh) -> None:
    fake.known_hosts("known_hosts")
    fake.known_hosts("known_hosts2")
    shared = fake.folder / "ProgramData" / "ssh" / "ssh_known_hosts"
    shared.parent.mkdir(parents=True)
    shared.touch()
    fake.known[str(shared)] = {"192.0.2.40"}
    assert not known.asks_to_trust("192.0.2.40", SshInfo())
    names = [Path(path).name for _name, path in fake.looked_up()]
    assert names == ["known_hosts", "known_hosts2", "ssh_known_hosts"]


def test_no_known_hosts_file_yet_means_ssh_exe_asks(fake: FakeSsh) -> None:
    assert known.asks_to_trust("192.0.2.40", SshInfo())
    assert fake.looked_up() == []


def test_a_port_other_than_22_is_looked_up_as_ssh_exe_stores_it(fake: FakeSsh) -> None:
    fake.settings["port"] = "2222"
    fake.known_hosts("known_hosts", "[192.0.2.40]:2222")
    assert not known.asks_to_trust("192.0.2.40", SshInfo(port=2222, login="admin"))
    assert fake.runs[0] == [str(fake.ssh), "-G", "-p", "2222", "-l", "admin", "--", "192.0.2.40"]
    assert fake.looked_up()[0][0] == "[192.0.2.40]:2222"


def test_an_alias_from_ssh_config_is_looked_up_by_the_name_ssh_exe_stores(fake: FakeSsh) -> None:
    fake.settings["hostname"] = "srv-01.example.com"
    fake.known_hosts("known_hosts", "srv-01.example.com")
    assert not known.asks_to_trust("web", SshInfo())
    fake.settings.update({"port": "2222", "hostkeyalias": "web-alias"})
    fake.known_hosts("known_hosts", "web-alias")
    assert not known.asks_to_trust("web", SshInfo())
    assert fake.looked_up()[-1][0] == "web-alias"


@pytest.mark.parametrize("value", ["accept-new", "true", "false"])
def test_no_hint_when_ssh_exe_is_set_never_to_ask(fake: FakeSsh, value: str) -> None:
    fake.settings["stricthostkeychecking"] = value
    assert not known.asks_to_trust("192.0.2.40", SshInfo())
    assert fake.looked_up() == []


def test_no_hint_when_a_command_answers_for_known_hosts(fake: FakeSsh) -> None:
    fake.settings["knownhostscommand"] = r"C:\tools\hosts.cmd"
    assert not known.asks_to_trust("192.0.2.40", SshInfo())


def test_no_hint_when_it_can_t_tell(fake: FakeSsh, monkeypatch: pytest.MonkeyPatch) -> None:
    fake.known_hosts("known_hosts")
    fake.keygen_code = 255
    assert not known.asks_to_trust("192.0.2.40", SshInfo())
    fake.keygen_code = None
    fake.ssh_code = 255
    assert not known.asks_to_trust("192.0.2.40", SshInfo())
    fake.ssh_code = 0
    assert not known.asks_to_trust("-oProxyCommand=calc", SshInfo())
    fake.keygen.unlink()
    assert not known.asks_to_trust("192.0.2.40", SshInfo())

    def slow(argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(list(argv), known.TIMEOUT)

    monkeypatch.setattr(known.subprocess, "run", slow)
    assert not known.asks_to_trust("192.0.2.40", SshInfo())
    monkeypatch.setattr(launch, "ssh_exe", lambda: None)
    assert not known.asks_to_trust("192.0.2.40", SshInfo())


def test_a_space_in_a_profile_folder_doesn_t_split_its_known_hosts_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROGRAMDATA", r"D:\Data")
    settings = {
        "userknownhostsfile": r"C:\Users\Ana Maria/.ssh/known_hosts C:\Users\Ana Maria/.ssh/kh2",
        "globalknownhostsfile": r"__PROGRAMDATA__\ssh/ssh_known_hosts \\fs01\ssh\known_hosts",
    }
    files = [str(path) for path in known.known_files(settings)]
    assert files == [
        r"C:\Users\Ana Maria\.ssh\known_hosts",
        r"C:\Users\Ana Maria\.ssh\kh2",
        r"D:\Data\ssh\ssh_known_hosts",
        r"\\fs01\ssh\known_hosts",
    ]
    assert known.known_files({"userknownhostsfile": "none"}) == []


def test_ssh_exe_s_settings_are_read_one_per_line() -> None:
    settings = known.settings_of("User admin\nhostname 192.0.2.40\nport 22\n\nidentityfile a\n")
    assert settings == {
        "user": "admin",
        "hostname": "192.0.2.40",
        "port": "22",
        "identityfile": "a",
    }
    assert known.stored_name(settings) == "192.0.2.40"
    assert known.stored_name({"hostname": "2001:db8::5", "port": "2200"}) == "[2001:db8::5]:2200"
    assert known.stored_name({}) == ""
