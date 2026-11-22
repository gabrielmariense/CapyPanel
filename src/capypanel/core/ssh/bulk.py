from collections.abc import Iterable, Mapping

from capypanel.core.hosts import bulk
from capypanel.core.hosts.bulk import ImportRow, Parsed, Plan, Verdict
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.core.ssh.host import DEFAULT_PORT, SshInfo, is_login, is_port, with_info

PORT, LOGIN = "ssh port", "ssh login"
# Never "port", "user" or "login" alone: a list of PCs may have them for a switch port or the
# person at the desk.
MORE: Mapping[str, frozenset[str]] = {
    PORT: frozenset({"ssh port", "porta ssh"}),
    LOGIN: frozenset(
        {"ssh login", "login ssh", "log in as", "entrar como", "ssh user", "usuário ssh"}
    ),
}


def parse(text: str, *, file: bool = False) -> Parsed:
    return bulk.parse(text, file=file, more=MORE)


def problem(row: ImportRow) -> str | None:
    cells = dict(row.more)
    port, login = cells.get(PORT, "").strip(), cells.get(LOGIN, "").strip()
    if port and port_of(port) is None:
        return _("Not an SSH port: type a number from 1 to 65535")
    if login and not is_login(login):
        return _("Not a name ssh.exe can log in as: no spaces, quotes or characters such as "
                 "; & |, and it can't start with “-”")  # fmt: skip
    return None


def plan(host_list: HostList, rows: Iterable[ImportRow], default_group: str) -> Plan:
    planned = bulk.plan(host_list, rows, default_group, problem=problem)
    known = {h.id for h in host_list.hosts}
    added = [h for h in planned.result.hosts if h.id not in known]
    adds = [i.row for i in planned.items if i.verdict is Verdict.ADD]
    result = planned.result
    for host, row in zip(added, adds, strict=True):
        info = info_of_row(row)
        if info != SshInfo():
            result = result.update_host(with_info(host, info))
    return Plan(planned.items, planned.new_groups, result)


def info_of_row(row: ImportRow) -> SshInfo:
    cells = dict(row.more)
    port = port_of(cells.get(PORT, "").strip())
    return SshInfo(port=port or DEFAULT_PORT, login=cells.get(LOGIN, "").strip())


def port_of(text: str) -> int | None:
    try:
        number = int(text)
    except ValueError:
        return None
    return number if is_port(number) else None


def fields(info: SshInfo) -> dict[str, str]:
    return {PORT: "" if info.port == DEFAULT_PORT else str(info.port), LOGIN: info.login}
