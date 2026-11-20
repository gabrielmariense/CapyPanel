import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QKeySequence, QValidator
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMenu, QTreeWidgetItem
from test_printers_tool import FakeShell  # the same pretend shell as Printers' tests

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.remote.status import PortState
from capypanel.core.ssh import launch
from capypanel.core.ssh.host import SshInfo, group_login, info_of, with_info
from capypanel.core.ssh.launch import connect as real_connect  # before no_ssh stands in for it
from capypanel.core.ssh.launch import tab_command as real_tab_command
from capypanel.ui import menus
from capypanel.ui.list_workspace.panels import ROLE_NOTHING
from capypanel.ui.settings.pages import AutoStatusOnlyPage, SettingRow
from capypanel.ui.ssh_tool import refresh
from capypanel.ui.ssh_tool import tool as tool_module
from capypanel.ui.ssh_tool.dialog import LoginDialog, SshHostDialog
from capypanel.ui.ssh_tool.table import ROLE_QUIET
from capypanel.ui.ssh_tool.tool import SshTool
from capypanel.ui.themes import engine as themes

if TYPE_CHECKING:
    from capywindow import CapyWindow


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
    listfile.save(path, hl, expected=None)  # a host list: SSH shows Hosts' lists
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


def test_a_tool_built_alone_takes_its_toolbar_with_it(shell: FakeShell) -> None:
    tool = SshTool(shell)
    toolbar = tool.toolbar
    tool.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(toolbar)  # at once: a theme switch can come next


@pytest.fixture
def capy(qapp: QApplication, tmp_path: Path) -> Iterator["CapyWindow"]:
    """The whole window on a host list with a PC and a server: SSH shows Hosts' open list."""
    from capywindow import CapyWindow

    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, desks = HostList().add_group("Front desks")
    hl, _desk = hl.add_host("DESK-01", desks.id, address="192.0.2.11")
    hl, racks = hl.add_group("Racks")
    hl = _host(hl, "nas-01", racks.id, "192.0.2.41", port=2222, login="root")
    listfile.save(tmp_path / "clinic.json", hl, expected=None)
    window = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    assert window.hosts.open_list(tmp_path / "clinic.json")
    yield window
    window.close()


def _ssh(window: "CapyWindow") -> SshTool:
    tool = window.tools["ssh"]
    assert isinstance(tool, SshTool)
    return tool


def test_ssh_shows_the_list_open_in_hosts_and_an_edit_in_either_shows_in_both(
    capy: "CapyWindow", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from capypanel.ui.hosts import HostDialog
    from capypanel.ui.hosts_tool import tool as hosts_module

    ssh = _ssh(capy)
    assert ssh.document is capy.hosts.document and _rows(ssh) == {}  # behind Hosts: waits
    assert capy.show_tool("ssh") and set(_rows(ssh)) == {"DESK-01", "nas-01"}

    def add(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, SshHostDialog)
        dialog.name.setText("backup-01")
        dialog.address.setText("192.0.2.45")
        dialog.login.setText("admin")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", add)
    ssh.add_item()
    assert capy.show_tool("hosts")
    table = capy.hosts.table
    rows = (table.topLevelItem(i) for i in range(table.topLevelItemCount()))
    shown = {row.text(0) for row in rows if row is not None}
    assert shown == {"DESK-01", "nas-01", "backup-01"}  # Hosts' table, once it's shown

    def rename(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, HostDialog)
        dialog.name.setText("nas-02")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(hosts_module, "run_modal", rename)
    doc = capy.hosts.document
    assert doc is not None
    capy.hosts.edit_item(next(h for h in doc.hosts.hosts if h.name == "nas-01"))
    assert set(_rows(ssh)) == {"DESK-01", "nas-01", "backup-01"}  # behind Hosts: not refilled
    assert capy.show_tool("ssh")
    assert set(_rows(ssh)) == {"DESK-01", "nas-02", "backup-01"}  # SSH's table, once shown
    saved = {h.name: h for h in listfile.load(tmp_path / "clinic.json").hosts.hosts}
    assert info_of(saved["nas-02"]) == SshInfo(port=2222, login="root")  # Hosts kept them
    assert info_of(saved["backup-01"]) == SshInfo(login="admin")


def test_a_list_picked_or_made_in_ssh_opens_in_hosts_and_profile_cleanup(
    capy: "CapyWindow", tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from capypanel.ui.list_workspace import workspace
    from capypanel.ui.profiles_tool.tool import ProfilesTool

    ssh = _ssh(capy)
    assert ssh.document is capy.hosts.document  # else picking a host list asks, and waits
    assert capy.show_tool("ssh")  # its dropdown is picked from SSH itself
    servers, racks = HostList().add_group("Racks")
    servers = _host(servers, "core-sw-01", racks.id, "192.0.2.40")
    listfile.save(tmp_path / "servers.json", servers, expected=None)
    ssh.pick_list(tmp_path / "servers.json")
    doc = capy.hosts.document
    assert doc is not None and doc.path == tmp_path / "servers.json"
    assert ssh.document is doc and set(_rows(ssh)) == {"core-sw-01"}
    assert ssh.list_choices() == capy.hosts.list_choices()  # one dropdown's lists
    profiles = capy.tools["profiles"]
    assert isinstance(profiles, ProfilesTool) and profiles.list_picker.text() == "servers"
    made = tmp_path / "linux.json"
    monkeypatch.setattr(workspace, "ask_new_list", lambda *_a, **_k: made)
    ssh.new_list()  # New list… in SSH's dropdown makes a host list
    doc = capy.hosts.document
    assert doc is not None and doc.path == made and ssh.document is doc
    assert listfile.load(made).hosts.hosts == ()


def test_ssh_keeps_no_lists_of_its_own(capy: "CapyWindow", monkeypatch: pytest.MonkeyPatch) -> None:
    places = capy.paths.lists("ssh")
    assert not places.shared_dir.exists() and not places.user_dir.exists()
    opened: list[str | None] = []
    monkeypatch.setattr(capy, "open_settings", lambda page=None: opened.append(page))
    ssh = _ssh(capy)
    menu = ssh.list_picker.menu()
    menu.aboutToShow.emit()
    [manage] = [a for a in menu.actions() if a.text() == "&Manage host lists…"]
    manage.trigger()
    assert opened == ["hosts"]


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
    assert words[:3] == ["&Connect", "Connect in a separate &window", "Re&fresh host"]
    assert menu.defaultAction() is ssh.commands.connect_host
    assert menu.toolTipsVisible()
    tip = ssh.commands.connect_window.toolTip()
    assert tip == "Opens ssh.exe in a window of its own, outside CapyPanel"
    _select(ssh, "nas-01", "web-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    assert menus.label(ssh.commands.refresh_selected) == "Re&fresh 2 hosts"


def test_connect_s_key_reads_enter_in_the_host_menu(ssh: SshTool) -> None:
    themes.apply(themes.DEFAULT_THEME)  # its watcher keeps the room in every menu
    _select(ssh, "nas-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    connect = ssh.commands.connect_host
    assert connect in menu.actions() and connect.shortcut() == QKeySequence("Return")
    _name, tab, room = connect.text().partition("\t")
    assert tab and room and not room.strip()  # Qt draws blanks there, never "Return"
    assert menus.shortcut_text(connect) == "Enter"


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
    ssh: SshTool, monkeypatch: pytest.MonkeyPatch, help_boxes: list[tuple[str, str]]
) -> None:
    def missing(*_args: object) -> None:
        raise launch.SshMissing

    monkeypatch.setattr(launch, "connect", missing)
    monkeypatch.setattr(launch, "tab_command", missing)
    _select(ssh, "core-sw-01", "web-01")
    ssh.connect_selected()  # in tabs
    ssh.connect_selected(window=True)
    words = (
        "Windows' SSH client (ssh.exe) isn't installed on this PC. To add it, search Start for "
        "“Optional features” and add “OpenSSH Client”. Adding it needs an administrator."
    )
    box = (words, "ssh-not-installed")
    assert help_boxes == [box, box]  # once each time, not once per host
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


@pytest.mark.parametrize("address", ["-oProxyCommand=calc", "srv;calc", "srv&calc"])
def test_an_address_ssh_exe_would_misread_is_never_handed_over(
    ssh: SshTool, shell: FakeShell, monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    # A list file edited by hand: the real checks run before anything starts, in a tab or in a
    # separate window. A leading "-" is an option; ; and & would reach a ProxyCommand's shell.
    started: list[object] = []
    monkeypatch.setattr(launch, "connect", real_connect)
    monkeypatch.setattr(launch, "tab_command", real_tab_command)
    monkeypatch.setattr(launch, "ssh_exe", lambda: Path("C:/Windows/System32/OpenSSH/ssh.exe"))
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: started.append(a))
    doc = ssh.document
    assert doc is not None
    nas = next(h for h in doc.hosts.hosts if h.name == "nas-01")
    assert ssh._commit(doc.hosts.update_host(replace(nas, address=address)))
    _select(ssh, "nas-01")
    for window in (False, True):
        shell.messages.clear()
        ssh.connect_selected(window=window)
        assert shell.messages == [
            "Can't connect to “nas-01”: its address or Log in as has a space, starts with “-”, "
            "or has a character such as ; & | or quotes."
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
    saved = {h.name: h for h in listfile.load(servers).hosts.hosts}  # a host list
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


def test_the_fields_take_none_of_the_characters_ssh_exe_refuses(qapp: QApplication) -> None:
    # Windows' own ssh.exe 9.5 refuses them; an older one would pass them on to a ProxyCommand
    # that names the host or the user, in a shell. A key that would type one does nothing.
    dialog = SshHostDialog(None, HostList())
    address, login = dialog.address.validator(), dialog.login.validator()
    assert address is not None and login is not None
    assert not any(_accepts(address, f"srv{c}x") for c in "\"$&'(),;<>\\`{|}")
    assert not any(_accepts(login, f"us{c}er") for c in "\"&'();<>`{|}")
    assert all(_accepts(address, ok) for ok in ("srv-01", "user@srv-01", "fe80::1%3"))
    assert all(_accepts(login, ok) for ok in ("EXAMPLE\\user", "admin@corp.example", "svc$"))
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
    assert details.login_button is not None and details.login_button.value_text() == "root"
    assert details.shown_value("group") == "Racks"


def _items(menu: QMenu) -> list[tuple[str, bool]]:
    """Each item's words and tick, "-" for a line."""
    return [("-", False) if a.isSeparator() else (menus.label(a), a.isChecked())
            for a in menu.actions()]  # fmt: skip


def _pick(menu: QMenu, words: str) -> None:
    [action] = [a for a in menu.actions() if menus.label(a) == words]
    assert action.isEnabled()
    action.trigger()


def _submenu(menu: QMenu, words: str) -> QMenu:
    [found] = [a.menu() for a in menu.actions() if menus.label(a) == words]
    assert isinstance(found, QMenu)
    return found


def _saved_logins(path: Path) -> dict[str, str]:
    hosts = listfile.load(path).hosts
    names = {h.name: info_of(h).login for h in hosts.hosts}
    return names | {g.name: group_login(g) for g in hosts.groups}


NONE = "None: your SSH config, then your Windows user name"


def test_details_log_in_as_is_a_picker_of_the_names_the_list_uses(
    ssh: SshTool, servers: Path
) -> None:
    _select(ssh, "nas-01")
    picker = ssh.details.login_button
    assert picker is not None and picker.marks == ("pin",)  # its own name, as Hosts pins one
    assert picker.toolTip() == "Only this host"
    menu = ssh.details.login_menu
    menu.aboutToShow.emit()  # what a click on the picker fills it with
    assert _items(menu) == [
        (NONE, False), ("-", False), ("admin", False), ("root", True), ("-", False),
        ("&Another name…", False),
    ]  # fmt: skip
    _pick(menu, "admin")
    assert _saved_logins(servers)["nas-01"] == "admin"
    picker = ssh.details.login_button
    assert picker is not None and picker.value_text() == "admin"  # Details shows it at once
    menu.aboutToShow.emit()
    _pick(menu, NONE)
    assert _saved_logins(servers)["nas-01"] == ""
    picker = ssh.details.login_button
    assert picker is not None and (picker.value_text(), picker.marks) == ("—", ())
    assert picker.toolTip() == "Empty: your SSH config, then your Windows user name"
    assert _rows(ssh)["nas-01"][ssh.table.LOGIN] == ""


def test_the_host_menu_s_log_in_as_sets_every_host_picked(
    ssh: SshTool, servers: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _select(ssh, "core-sw-01", "web-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    logins = _submenu(menu, "&Log in as")
    # One has admin, the other none: neither is ticked.
    assert _items(logins) == [
        (NONE, False), ("-", False), ("admin", False), ("root", False), ("-", False),
        ("&Another name…", False),
    ]  # fmt: skip
    _pick(logins, "root")
    saved = _saved_logins(servers)
    assert (saved["core-sw-01"], saved["web-01"], saved["nas-01"]) == ("root", "root", "root")

    def another(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, LoginDialog) and dialog.windowTitle() == "Log in as"
        assert dialog.about.text() == "2 hosts selected"
        assert dialog.login.text() == "root"  # what both have now
        assert dialog.login.placeholderText().startswith("Empty: your SSH config")
        assert not _accepts(cast(QValidator, dialog.login.validator()), "-oProxyCommand=calc")
        dialog.login.setText("EXAMPLE\\user")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", another)
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    _pick(_submenu(menu, "&Log in as"), "&Another name…")
    saved = _saved_logins(servers)
    assert (saved["core-sw-01"], saved["web-01"]) == ("EXAMPLE\\user", "EXAMPLE\\user")


def test_a_group_s_log_in_as_is_taken_by_its_hosts_without_a_name_of_their_own(
    ssh: SshTool, servers: Path, monkeypatch: pytest.MonkeyPatch, no_ssh: list[tuple[str, object]]
) -> None:
    doc = ssh.document
    assert doc is not None
    [racks] = doc.hosts.groups

    def pi(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, LoginDialog)
        assert dialog.about.text() == (
            "Hosts in “Racks” without a name of their own log in with this one."
        )
        assert dialog.login.text() == ""
        dialog.login.setText("pi")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", pi)
    menu = QMenu()
    ssh.fill_group_menu(menu, racks)
    _pick(_submenu(menu, "&Log in as"), "&Another name…")
    assert _saved_logins(servers)["Racks"] == "pi"
    core = next(h for h in ssh.document.hosts.hosts if h.name == "core-sw-01")  # type: ignore[union-attr]
    ssh.set_hosts_login([core.id], "")  # follows Racks now
    rows = _rows(ssh)
    assert (rows["core-sw-01"][ssh.table.LOGIN], rows["nas-01"][ssh.table.LOGIN]) == ("pi", "root")
    assert rows["web-01"][ssh.table.LOGIN] == ""  # in no group
    _select(ssh, "core-sw-01")
    picker = ssh.details.login_button
    assert picker is not None and (picker.value_text(), picker.marks) == ("pi", ())
    assert picker.toolTip() == "From group “Racks”: pi"
    ssh.details.login_menu.aboutToShow.emit()
    assert _items(ssh.details.login_menu)[0] == ("From group “Racks”: pi", True)
    ssh.commands.connect_host.trigger()
    assert no_ssh == [("192.0.2.40", SshInfo(login="pi"))]  # the group's name reaches ssh.exe
    menu = QMenu()
    now = ssh.document.hosts.group(racks.id)  # type: ignore[union-attr]  # as the menu reads it
    assert now is not None
    ssh.fill_group_menu(menu, now)
    assert _items(_submenu(menu, "&Log in as"))[:4] == [
        (NONE, False), ("-", False), ("pi", True), ("root", False)
    ]  # fmt: skip


def test_log_in_as_has_a_section_of_its_own_in_both_menus(ssh: SshTool) -> None:
    _select(ssh, "nas-01", "web-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    words = [menus.label(a) if not a.isSeparator() else "-" for a in menu.actions()]
    at = words.index("&Log in as")
    assert words[at - 2 : at + 3] == ["Re&fresh 2 hosts", "-", "&Log in as", "-", "Co&py"]
    doc = ssh.document
    assert doc is not None
    menu = QMenu()
    ssh.fill_group_menu(menu, doc.hosts.groups[0])
    words = [menus.label(a) if not a.isSeparator() else "-" for a in menu.actions()]
    assert words == ["-", "&Log in as", "-", "Re&fresh group"]


def test_the_edit_window_s_hint_says_what_an_empty_log_in_as_takes(ssh: SshTool) -> None:
    doc = ssh.document
    assert doc is not None
    [racks] = doc.hosts.groups
    ssh.set_group_login(racks.id, "pi")
    hosts = ssh.document.hosts  # type: ignore[union-attr]
    dialog = SshHostDialog(None, hosts, next(h for h in hosts.hosts if h.name == "web-01"))
    assert dialog.login.placeholderText().startswith("Empty: your SSH config")
    dialog.group.setCurrentIndex(dialog.group.findData(racks.id))  # moving it into Racks
    assert dialog.login.placeholderText() == "From group “Racks”: pi"
    dialog.deleteLater()


def test_log_in_as_is_greyed_on_a_list_that_can_t_be_saved(
    ssh: SshTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ssh, "_writable", lambda: None)  # read-only: Connect still works
    _select(ssh, "nas-01")
    menu = QMenu()
    ssh.fill_item_menu(menu, ssh.selected_items())
    logins = _submenu(menu, "&Log in as")
    assert logins.actions() and not any(a.isEnabled() for a in logins.actions())
    assert ssh.commands.connect_host.isEnabled()


def test_refresh_status_by_itself_is_off_until_picked_and_warns_about_fail2ban(
    ssh: SshTool,
) -> None:
    group = ssh.settings_group()
    [(page_id, page)] = group.build()
    assert page_id == "ssh" and isinstance(page, AutoStatusOnlyPage)  # its lists are Hosts'
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
