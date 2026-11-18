import json
from dataclasses import replace
from pathlib import Path

import pytest

from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.ssh.host import DEFAULT_PORT, SshInfo, info_of, is_login, with_info


def _list_with(info: SshInfo) -> HostList:
    hosts, host = HostList().add_host("srv-01", NO_GROUP, address="192.0.2.30")
    return hosts.update_host(with_info(host, info))


def test_details_round_trip_through_the_list_file(tmp_path: Path) -> None:
    info = SshInfo(port=2222, login="admin")
    path = tmp_path / "ssh.json"
    listfile.save(path, _list_with(info), expected=None)
    [host] = listfile.load(path).hosts.hosts
    assert info_of(host) == info


def test_the_file_is_a_plain_host_list_with_one_extra_key(tmp_path: Path) -> None:
    path = tmp_path / "ssh.json"
    listfile.save(path, _list_with(SshInfo(login="root")), expected=None)
    [entry] = json.loads(path.read_text(encoding="utf-8"))["hosts"]
    assert entry["address"] == "192.0.2.30"
    assert entry["ssh"] == {"login": "root"}  # port 22, the default, left out


def test_a_host_without_details_uses_port_22_and_ssh_exes_own_login() -> None:
    [host] = HostList().add_host("switch-01", NO_GROUP)[0].hosts
    assert info_of(host) == SshInfo(port=DEFAULT_PORT, login="")
    assert "ssh" not in with_info(host, SshInfo()).extra


def test_odd_values_are_read_as_the_defaults_and_kept_as_found() -> None:
    _hosts, host = HostList().add_host("srv", NO_GROUP)
    odd = {"port": "twenty-two", "login": "-oProxyCommand=calc", "keepalive": 30}
    host = replace(host, extra={"ssh": odd})
    info = info_of(host)
    assert (info.port, info.login) == (DEFAULT_PORT, "")
    assert with_info(host, info).extra["ssh"] == odd  # saved back untouched


@pytest.mark.parametrize("port", [0, 65536, -22, True, 22.0])
def test_a_port_out_of_range_or_not_a_whole_number_is_odd(port: object) -> None:
    _hosts, host = HostList().add_host("srv", NO_GROUP)
    assert info_of(replace(host, extra={"ssh": {"port": port}})).port == DEFAULT_PORT


def test_a_new_value_replaces_an_odd_one() -> None:
    _hosts, host = HostList().add_host("srv", NO_GROUP)
    host = replace(host, extra={"ssh": {"port": "x"}})
    edited = with_info(host, SshInfo(port=2200, extra=info_of(host).extra))
    assert edited.extra["ssh"] == {"port": 2200}


@pytest.mark.parametrize(
    "login", ["root", "admin@corp.example", "EXAMPLE\\user", "ana.souza", "svc$"]
)
def test_a_login_ssh_exe_can_take(login: str) -> None:
    assert is_login(login)


@pytest.mark.parametrize("char", "\"&'();<>`{|}")
def test_a_login_with_a_character_ssh_exe_9_5_refuses_is_refused(char: str) -> None:
    # Windows' own ssh.exe 9.5 refuses these in a user name; an older one passes them on to a
    # ProxyCommand that names the user (%r), which runs in a shell. Read from a file, such a
    # login is odd: ssh.exe's own default then, and the value kept as found.
    assert not is_login(f"root{char}calc")
    _hosts, host = HostList().add_host("srv", NO_GROUP)
    host = replace(host, extra={"ssh": {"login": f"root{char}calc"}})
    assert info_of(host).login == ""
    assert with_info(host, info_of(host)).extra["ssh"] == {"login": f"root{char}calc"}


@pytest.mark.parametrize("login", ["", "-l", "two words", "tab\there", "x" * 101, "nul\x00"])
def test_a_login_ssh_exe_would_misread_is_refused(login: str) -> None:
    # A leading "-" would reach ssh.exe as an option, from a list file anyone could edit.
    assert not is_login(login)
