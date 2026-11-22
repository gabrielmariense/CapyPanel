import json
from dataclasses import replace
from pathlib import Path

import pytest

from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, Group, HostList
from capypanel.core.ssh.host import (
    DEFAULT_PORT,
    SshInfo,
    connect_info,
    group_login,
    group_login_of,
    info_of,
    is_login,
    login_of,
    logins_in,
    with_group_login,
    with_info,
    with_login,
)


def _list_with(info: SshInfo) -> HostList:
    hosts, host = HostList().add_host("srv-01", NO_GROUP, address="192.0.2.30")
    return hosts.update_host(with_info(host, info))


def _pis() -> tuple[HostList, Group, Group]:
    hl, pis = HostList().add_group("Pis")
    hl, kitchen = hl.add_group("Kitchen", pis.id)
    hl = with_group_login(hl, pis.id, "pi")
    hl, _pi01 = hl.add_host("pi-01", kitchen.id, address="192.0.2.51")
    hl, pi02 = hl.add_host("pi-02", kitchen.id, address="192.0.2.52")
    hl = hl.update_host(with_info(pi02, SshInfo(port=2222, login="EXAMPLE\\user")))
    hl, _desk = hl.add_host("desk-01", NO_GROUP, address="198.51.100.10")
    return hl, pis, kitchen


def _named(hl: HostList, name: str) -> tuple[str, str | None]:
    login, source = login_of(hl, next(h for h in hl.hosts if h.name == name))
    return login, source.name if source is not None else None


def test_a_host_without_a_name_of_its_own_logs_in_as_its_nearest_group_says() -> None:
    hl, pis, kitchen = _pis()
    assert _named(hl, "pi-01") == ("pi", "Pis")
    assert _named(hl, "pi-02") == ("EXAMPLE\\user", None)
    assert _named(hl, "desk-01") == ("", None)
    hl = with_group_login(hl, kitchen.id, "admin")
    assert _named(hl, "pi-01") == ("admin", "Kitchen")
    assert group_login_of(hl, pis.id)[0] == "pi"
    pi02 = next(h for h in hl.hosts if h.name == "pi-02")
    assert connect_info(hl, pi02) == SshInfo(port=2222, login="EXAMPLE\\user")
    pi01 = next(h for h in hl.hosts if h.name == "pi-01")
    assert connect_info(hl, pi01) == SshInfo(port=DEFAULT_PORT, login="admin")
    assert info_of(pi01).login == ""


def test_a_group_s_name_round_trips_through_the_list_file_beside_what_else_it_has(
    tmp_path: Path,
) -> None:
    hl, pis, _kitchen = _pis()
    odd = {"login": "pi", "keepalive": 30}
    hl = replace(hl, groups=tuple(replace(g, extra={"ssh": odd}) if g.id == pis.id else g
                                  for g in hl.groups))  # fmt: skip
    path = tmp_path / "pis.json"
    listfile.save(path, hl, expected=None)
    [entry] = [g for g in json.loads(path.read_text(encoding="utf-8"))["groups"]
               if g["name"] == "Pis"]  # fmt: skip
    assert entry["ssh"] == odd
    loaded = listfile.load(path).hosts
    assert group_login(loaded.groups[0]) == "pi"
    renamed = with_group_login(loaded, pis.id, "ubuntu")
    assert renamed.groups[0].extra["ssh"] == {"keepalive": 30, "login": "ubuntu"}
    cleared = with_group_login(renamed, pis.id, "")
    assert cleared.groups[0].extra["ssh"] == {"keepalive": 30}
    plain, plain_pis, _kitchen = _pis()
    assert "ssh" not in with_group_login(plain, plain_pis.id, "").groups[0].extra


def test_an_odd_group_name_is_read_as_none_and_a_new_one_replaces_it() -> None:
    hl, pis, _kitchen = _pis()
    for odd in ({"login": "-oProxyCommand=calc"}, {"login": 7}, "pi", ["pi"]):
        bad = replace(hl, groups=(replace(hl.groups[0], extra={"ssh": odd}), *hl.groups[1:]))
        assert group_login(bad.groups[0]) == ""
        assert _named(bad, "pi-01") == ("", None)
        fixed = with_group_login(bad, pis.id, "pi")
        assert group_login(fixed.groups[0]) == "pi"


def test_a_loop_of_parents_in_a_hand_edited_file_ends() -> None:
    hl = HostList(groups=(Group("a", "A", parent="b"), Group("b", "B", parent="a")))
    assert group_login_of(hl, "a") == ("", None)
    looped = with_group_login(hl, "b", "root")
    assert group_login_of(looped, "a")[0] == "root"


def test_with_login_sets_or_clears_only_the_host_s_own_name() -> None:
    hl, _pis_group, _kitchen = _pis()
    pi02 = next(h for h in hl.hosts if h.name == "pi-02")
    assert info_of(with_login(pi02, "pi")) == SshInfo(port=2222, login="pi")
    assert info_of(with_login(pi02, "")) == SshInfo(port=2222)


def test_the_pickers_offer_every_name_the_list_uses_once_a_to_z() -> None:
    hl, _pis_group, kitchen = _pis()
    hl = with_group_login(hl, kitchen.id, "Admin")
    desk = next(h for h in hl.hosts if h.name == "desk-01")
    hl = hl.update_host(with_login(desk, "pi"))
    assert logins_in(hl) == ["Admin", "EXAMPLE\\user", "pi"]
    assert logins_in(HostList()) == []


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
    assert entry["ssh"] == {"login": "root"}


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
    assert with_info(host, info).extra["ssh"] == odd


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
    # ssh.exe 9.5 refuses these; an older one passes them to a ProxyCommand's shell (%r).
    assert not is_login(f"root{char}calc")
    _hosts, host = HostList().add_host("srv", NO_GROUP)
    host = replace(host, extra={"ssh": {"login": f"root{char}calc"}})
    assert info_of(host).login == ""
    assert with_info(host, info_of(host)).extra["ssh"] == {"login": f"root{char}calc"}


@pytest.mark.parametrize("login", ["", "-l", "two words", "tab\there", "x" * 101, "nul\x00"])
def test_a_login_ssh_exe_would_misread_is_refused(login: str) -> None:
    # A leading "-" would reach ssh.exe as an option, from a list file anyone could edit.
    assert not is_login(login)
