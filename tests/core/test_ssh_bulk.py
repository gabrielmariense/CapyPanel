import pytest

from capypanel.core.hosts.bulk import Verdict
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.ssh import bulk
from capypanel.core.ssh.host import KEY, SshInfo, info_of, with_info


@pytest.mark.parametrize(
    "header",
    [
        "name,address,ssh port,ssh login",
        "Name,Address,SSH port,Log in as",
        "nome,endereço,Porta SSH,Entrar como",
        "name,address,ssh_port,ssh_login",
        "name,address,SSH Port,login ssh",
    ],
)
def test_the_two_ssh_columns_are_read_in_either_language(header: str) -> None:
    parsed = bulk.parse(f"{header}\nnas-01,192.0.2.41,2222,root\n")
    assert parsed.ignored == ()
    assert dict(parsed.rows[0].more) == {bulk.PORT: "2222", bulk.LOGIN: "root"}


def test_port_user_or_login_alone_stay_ignored_columns() -> None:
    parsed = bulk.parse("name,address,port,user,login\nDESK-01,192.0.2.11,Gi1/0/24,ana,ana\n")
    assert parsed.ignored == ("port", "user", "login")
    assert parsed.rows[0].more == ()


def test_new_hosts_come_with_their_port_and_log_in_as() -> None:
    hl, racks = HostList().add_group("Racks")
    text = (
        "name,address,group,ssh port,ssh login\n"
        "nas-01,192.0.2.41,Racks,2222,root\n"
        "web-01,198.51.100.42,,,deploy\n"
        "DESK-01,192.0.2.11,,,\n"
    )
    plan = bulk.plan(hl, bulk.parse(text).rows, NO_GROUP)
    assert [item.verdict for item in plan.items] == [Verdict.ADD] * 3
    hosts = {host.name: host for host in plan.result.hosts}
    assert hosts["nas-01"].group == racks.id
    assert info_of(hosts["nas-01"]) == SshInfo(port=2222, login="root")
    assert info_of(hosts["web-01"]) == SshInfo(login="deploy")
    assert KEY not in hosts["DESK-01"].extra


@pytest.mark.parametrize(
    ("port", "login", "reason"),
    [
        ("0", "", "Not an SSH port: type a number from 1 to 65535"),
        ("65536", "", "Not an SSH port: type a number from 1 to 65535"),
        ("Gi1/0/24", "", "Not an SSH port: type a number from 1 to 65535"),
        ("", "-oProxyCommand=calc", "Not a name ssh.exe can log in as"),
        ("", "two words", "Not a name ssh.exe can log in as"),
    ],
)
def test_a_port_or_name_ssh_exe_can_t_take_keeps_the_row_out(
    port: str, login: str, reason: str
) -> None:
    rows = bulk.parse(f"name,address,ssh port,ssh login\nsrv-01,192.0.2.40,{port},{login}\n").rows
    plan = bulk.plan(HostList(), rows, NO_GROUP)
    assert plan.items[0].verdict is Verdict.BAD
    assert plan.items[0].reason.startswith(reason)
    assert plan.result.hosts == ()


def test_a_host_already_in_the_list_is_skipped_and_left_as_it_was() -> None:
    hl, host = HostList().add_host("nas-01", NO_GROUP, address="192.0.2.41")
    hl = hl.update_host(with_info(host, SshInfo(port=2200)))
    text = "name,address,ssh port,ssh login\nnas-01,192.0.2.41,2222,root\n"
    plan = bulk.plan(hl, bulk.parse(text).rows, NO_GROUP)
    assert plan.items[0].verdict is Verdict.SKIP
    assert info_of(plan.result.hosts[0]) == SshInfo(port=2200)


def test_a_report_writes_what_an_import_reads_back() -> None:
    assert bulk.fields(SshInfo()) == {bulk.PORT: "", bulk.LOGIN: ""}
    assert bulk.fields(SshInfo(port=2222, login="root")) == {bulk.PORT: "2222", bulk.LOGIN: "root"}
    assert bulk.port_of(" 22 ") == 22 and bulk.port_of("22.0") is None
