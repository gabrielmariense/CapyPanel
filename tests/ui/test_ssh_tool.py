import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMenu, QTreeWidgetItem
from test_printers_tool import FakeShell  # the same pretend shell as Printers' tests

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.remote.status import PortState
from capypanel.core.ssh import launch
from capypanel.core.ssh.host import SshInfo, info_of, with_info
from capypanel.core.ssh.launch import connect as real_connect  # before no_ssh stands in for it
from capypanel.core.ssh.launch import tab_command as real_tab_command
from capypanel.ui import menus
from capypanel.ui.list_workspace.panels import ROLE_NOTHING
from capypanel.ui.settings.pages import AutoStatusPage, SettingRow
from capypanel.ui.ssh_tool import refresh
from capypanel.ui.ssh_tool import tool as tool_module
from capypanel.ui.ssh_tool.dialog import SshHostDialog
from capypanel.ui.ssh_tool.table import ROLE_QUIET
from capypanel.ui.ssh_tool.tool import SshTool


@pytest.fixture
def shell(tmp_path: Path) -> FakeShell:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return FakeShell(settings.resolve_paths(tmp_path))


def _host(hl: HostList, name: str, group: str, address: str = "", **info: Any) -> HostList:
    hl, host = hl.add_host(name, group, address=address)
    return hl.update_host(with_info(host, SshInfo(**info)))


@pytest.fixture
def servers(tmp_path: Path) -> Path:
    hl, racks = HostList().add_group("Racks")
    hl = _host(hl, "core-sw-01", racks.id, "192.0.2.40", login="admin")
    hl = _host(hl, "nas-01", racks.id, "192.0.2.41", port=2222, login="root")
    hl = _host(hl, "web-01", NO_GROUP, "198.51.100.42")
    path = tmp_path / "servers.json"
    listfile.save(path, hl, expected=None, kind="ssh")
    return path


@pytest.fixture
def ssh(qapp: QApplication, shell: FakeShell, servers: Path) -> Iterator[SshTool]:
    tool = SshTool(shell)
    assert tool.open_list(servers)
    yield tool
    for tab in tool.connections():  # its cmd.exe ends now, not when Qt gets round to it
        tab.close_connection()
    tool.close()
    tool.deleteLater()


def _rows(tool: SshTool) -> dict[str, list[str]]:
    table, found = tool.table, {}
    for i in range(table.topLevelItemCount()):
        row = table.topLevelItem(i)
        if row is not None:
            found[row.text(0)] = [row.text(c) for c in range(table.columnCount())]
    return found


def _row(tool: SshTool, name: str) -> QTreeWidgetItem:
    for i in range(tool.table.topLevelItemCount()):
        row = tool.table.topLevelItem(i)
        if row is not None and row.text(0) == name:
            return row
    raise AssertionError(f"no row {name}")


def _select(tool: SshTool, *names: str) -> None:
    tool.table.clearSelection()
    for i in range(tool.table.topLevelItemCount()):
        row = tool.table.topLevelItem(i)
        if row is not None and row.text(0) in names:
            row.setSelected(True)


def _wait(tool: SshTool) -> None:
    deadline = time.monotonic() + 10  # a deadline, not a count: threads can be slow
    while tool._run is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert tool._run is None


def test_the_table_shows_name_address_log_in_as_status_and_tags(ssh: SshTool) -> None:
    table = ssh.table
    header = table.headerItem()
    shown = [header.text(i) for i in range(table.columnCount()) if not table.isColumnHidden(i)]
    assert shown == ["Name", "Address", "Log in as", "Status", "Tags"]  # Port hidden at first
    rows = _rows(ssh)
    assert rows["nas-01"] == ["nas-01", "192.0.2.41", "2222", "root", "Not checked", ""]
    assert rows["web-01"][table.PORT] == "22" and rows["web-01"][table.LOGIN] == ""
    first = table.topLevelItem(0)
    assert first is not None and first.data(table.STATUS, ROLE_NOTHING)  # sorts last
    assert ssh.nav.everything.topLevelItem(0).text(0).startswith("All hosts")  # type: ignore[union-attr]
    assert ssh.search.placeholderText() == "Search name, address, log in as, status, tags, notes"


def test_it_is_the_fourth_tool_on_the_rail_with_ctrl_4(qapp: QApplication, tmp_path: Path) -> None:
    from capywindow import CapyWindow

    (tmp_path / settings.PORTABLE_MARKER).touch()
    window = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    try:
        assert list(window.tools) == ["hosts", "printers", "profiles", "ssh"]
        tool = window.tools["ssh"]
        assert (tool.tool_name(), tool.ICON) == ("SSH", "terminal-2")
        assert window.show_tool("ssh") and window.shown_tool() is tool
        [ctrl_4] = [a for a in window.actions() if a.shortcut().toString() == "Ctrl+4"]
        assert ctrl_4.data() == "ssh"
    finally:
        window.close()


def test_refresh_checks_only_the_ssh_port_of_every_host_shown(
    ssh: SshTool, shell: FakeShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[str, int]] = []
    answers = {
        "192.0.2.40": (PortState.OPEN, "192.0.2.40"),
        "192.0.2.41": (PortState.CLOSED, "192.0.2.41"),
        "198.51.100.42": (PortState.NO_ANSWER, None),
    }

    def answer(host: str, port: int) -> tuple[PortState, str | None]:
        asked.append((host, port))
        return answers[host]

    monkeypatch.setattr(refresh, "port_state", answer)
    ssh.commands.refresh_shown.trigger()
    _wait(ssh)
    assert sorted(asked) == [("192.0.2.40", 22), ("192.0.2.41", 2222), ("198.51.100.42", 22)]
    rows, table = _rows(ssh), ssh.table
    assert [rows[n][table.STATUS] for n in ("core-sw-01", "nas-01", "web-01")] == [
        "Online", "Port closed", "Offline",
    ]  # fmt: skip
    closed = _row(ssh, "nas-01")
    tip = closed.toolTip(table.STATUS)
    assert tip.startswith("Checked ")
    assert tip.endswith(
        "Answered at 192.0.2.41, but port 2222 is closed: ssh.exe would fail with "
        "“Connection refused”."
    )
    assert closed.data(table.STATUS, ROLE_QUIET)  # only Online reads at full strength
    assert shell.messages[-1] == "Checked 3 hosts."
    assert "1 online" in ssh.status_label.text()


def test_a_host_with_no_usable_address_is_skipped(
    ssh: SshTool, shell: FakeShell, servers: Path
) -> None:
    doc = ssh.document
    assert doc is not None
    hl, _host_added = doc.hosts.add_host("two words", NO_GROUP)  # no address, nor a PC name
    assert ssh._commit(hl)
    ssh.commands.refresh_shown.trigger()
    _wait(ssh)
    assert "1 host has no address and was skipped." in shell.messages
    assert _rows(ssh)["two words"][ssh.table.STATUS] == "Not checked"


def test_connect_hands_ssh_exe_the_address_port_and_login(
    ssh: SshTool, no_ssh: list[tuple[str, object]]
) -> None:
    _select(ssh, "nas-01")
    assert ssh.commands.connect_host.isEnabled()
    ssh.commands.connect_host.trigger()
    assert no_ssh == [("192.0.2.41", SshInfo(port=2222, login="root"))]
    ssh.activate_selected()  # a double-click, or Enter in the table
    assert len(no_ssh) == 2
    _select(ssh, "core-sw-01", "web-01")
    ssh.details.connect_clicked.emit()
    assert [address for address, _info in no_ssh[2:]] == ["192.0.2.40", "198.51.100.42"]


def test_the_right_click_menu_starts_with_connect_in_bold(ssh: SshTool) -> None:
    _select(ssh, "nas-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    words = [menus.label(a) for a in menu.actions() if not a.isSeparator()]  # no shortcut room
    assert words[:3] == ["&Connect", "Connect in a separate &window", "&Refresh host"]
    assert menu.defaultAction() is ssh.commands.connect_host
    assert menu.toolTipsVisible()
    tip = ssh.commands.connect_window.toolTip()
    assert tip == "Opens ssh.exe in a window of its own, outside CapyPanel"
    _select(ssh, "nas-01", "web-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    assert menus.label(ssh.commands.refresh_selected) == "&Refresh 2 hosts"


def test_a_server_typed_in_the_search_is_offered_and_connected_at_once(
    ssh: SshTool, no_ssh: list[tuple[str, object]]
) -> None:
    [offer] = ssh.typed_offer("db-07", ())
    assert offer.text() == "Connect to db-07"  # no ellipsis: nothing opens before it connects
    offer.trigger()
    assert no_ssh == [("db-07", SshInfo())]  # port 22, and ssh.exe's own login
    assert ssh.typed_offer("-oProxyCommand=calc", ()) == []  # never an option for ssh.exe
    assert ssh.typed_offer("nas-01", ssh.document.hosts.hosts) == []  # type: ignore[union-attr]


def test_without_ssh_exe_it_says_where_to_add_it(
    ssh: SshTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*_args: object) -> None:
        raise launch.SshMissing

    warned: list[str] = []
    monkeypatch.setattr(launch, "connect", missing)
    monkeypatch.setattr(launch, "tab_command", missing)
    monkeypatch.setattr(
        tool_module.QMessageBox, "warning", lambda _parent, _title, text: warned.append(text)
    )
    _select(ssh, "core-sw-01", "web-01")
    ssh.connect_selected()  # in tabs
    ssh.connect_selected(window=True)
    words = (
        "Windows' SSH client (ssh.exe) isn't installed on this PC. To add it, search Start for "
        "“Optional features” and add “OpenSSH Client”. Adding it needs an administrator."
    )
    assert warned == [words, words]  # once each time, not once per host
    assert ssh.connections() == []


def test_the_separate_window_is_told_the_host_s_name(
    ssh: SshTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []
    monkeypatch.setattr(launch, "connect", lambda _address, _info, name="": names.append(name))
    _select(ssh, "web-01")
    ssh.commands.connect_window.trigger()
    assert names == ["web-01"]  # its words say "The connection to web-01 ended…"
    assert ssh.connections() == []  # a window, not a tab


def test_an_address_ssh_exe_would_read_as_an_option_is_never_handed_over(
    ssh: SshTool, shell: FakeShell, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A list file edited by hand: the real checks run before anything starts, in a tab or in a
    # separate window.
    started: list[object] = []
    monkeypatch.setattr(launch, "connect", real_connect)
    monkeypatch.setattr(launch, "tab_command", real_tab_command)
    monkeypatch.setattr(launch, "ssh_exe", lambda: Path("C:/Windows/System32/OpenSSH/ssh.exe"))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: started.append(a))
    doc = ssh.document
    assert doc is not None
    nas = next(h for h in doc.hosts.hosts if h.name == "nas-01")
    assert ssh._commit(doc.hosts.update_host(replace(nas, address="-oProxyCommand=calc")))
    _select(ssh, "nas-01")
    for window in (False, True):
        shell.messages.clear()
        ssh.connect_selected(window=window)
        assert shell.messages == [
            "Can't connect to “nas-01”: its address or Log in as has a space or starts with “-”."
        ]
    assert started == [] and ssh.connections() == []


def test_adding_a_host_saves_its_port_and_login(
    ssh: SshTool, servers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, SshHostDialog)
        assert dialog.windowTitle() == "Add host"
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).text() == "Add"
        assert dialog.port.value() == 22
        assert dialog.login.placeholderText().startswith("Empty: your SSH config")
        dialog.name.setText("backup-01")
        dialog.address.setText("192.0.2.45")
        dialog.port.setValue(2200)
        dialog.login.setText("EXAMPLE\\user")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", fill)
    ssh.add_item()
    saved = {h.name: h for h in listfile.load(servers, "ssh").hosts.hosts}
    assert info_of(saved["backup-01"]) == SshInfo(port=2200, login="EXAMPLE\\user")
    assert ssh.table.selected_ids() == [saved["backup-01"].id]


def _accepts(validator: QValidator, text: str) -> bool:
    state = cast(tuple[QValidator.State, str, int], validator.validate(text, 0))[0]
    return state == QValidator.State.Acceptable


def test_the_fields_take_no_space_nor_a_leading_dash(qapp: QApplication) -> None:
    dialog = SshHostDialog(None, HostList())
    for field in (dialog.address, dialog.login):
        validator = field.validator()
        assert validator is not None
        assert not any(_accepts(validator, bad) for bad in ("-l", "two words", " root"))
        assert _accepts(validator, "root")
    dialog.deleteLater()


def test_editing_the_address_forgets_the_last_check(
    ssh: SshTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(refresh, "port_state", lambda h, _p: (PortState.OPEN, h))
    ssh.commands.refresh_shown.trigger()
    _wait(ssh)
    assert _rows(ssh)["web-01"][ssh.table.STATUS] == "Online"

    def move(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, SshHostDialog)
        dialog.address.setText("198.51.100.43")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", move)
    doc = ssh.document
    assert doc is not None
    ssh.edit_item(next(h for h in doc.hosts.hosts if h.name == "web-01"))
    assert _rows(ssh)["web-01"][ssh.table.STATUS] == "Not checked"  # about the old address
    assert _rows(ssh)["nas-01"][ssh.table.STATUS] == "Online"


def test_details_show_the_status_connect_and_the_connection(ssh: SshTool) -> None:
    _select(ssh, "nas-01")
    details = ssh.details
    assert list(details.buttons) == ["connect", "refresh"]
    assert details.buttons["connect"].isEnabled()
    assert details.shown_value("address") == "192.0.2.41"
    assert details.shown_value("port") == "2222"
    assert details.shown_value("login") == "root"
    assert details.shown_value("group") == "Racks"


def test_refresh_status_by_itself_is_off_until_picked_and_warns_about_fail2ban(
    ssh: SshTool,
) -> None:
    group = ssh.settings_group()
    [(page_id, page)] = group.build()
    assert page_id == "ssh" and isinstance(page, AutoStatusPage)
    assert page.auto_every.currentText() == "Off"
    assert ssh.auto_status() == (False, 5) and not ssh._auto_timer.isActive()
    [row] = [
        r for r in page.findChildren(SettingRow) if r.name.text() == "Refresh status &by itself"
    ]
    assert row.description.text().startswith("Only the SSH port, so nothing logs in.")
    assert "fail2ban" in row.description.text()
    page.pick_every(15)
    assert ssh.prefs["auto_status"] == {"on": True, "minutes": 15}
    assert ssh._auto_timer.isActive() and ssh._auto_timer.interval() == 15 * 60_000
    page.pick_every(0)
    assert ssh.auto_status() == (False, 15) and not ssh._auto_timer.isActive()
