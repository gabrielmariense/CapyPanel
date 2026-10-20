import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu, QMessageBox, QToolButton

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.tools.connect import Credential, Target
from capypanel.core.tools.profiles import ConnectionProfile
from capypanel.ui import connect as connect_ui
from capypanel.ui.connect import CredentialDialog, ManualConnectDialog, Request
from capypanel.ui.hosts import HostDialog
from capypanel.ui.hosts_tool.settings import HostsSettings
from capypanel.ui.hosts_tool.table import HostTable
from capypanel.ui.list_workspace import workspace as workspace_module
from capypanel.ui.menus import label

Launch = tuple[str, str, int | None, Credential | None, tuple[str, ...]]


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Launch]:
    """Records launches instead of starting programs; every viewer counts as installed."""
    calls: list[Launch] = []

    def fake_launch(
        tool: Any, exe: Path, target: Any, credential: Any = None, options: Any = (),
        settings: Any = None,
    ) -> None:  # fmt: skip
        calls.append((tool.id, target.address, target.port, credential, tuple(options)))

    monkeypatch.setattr(connect_ui, "launch", fake_launch)
    monkeypatch.setattr(connect_ui.detect, "find_executable", lambda tool: Path("viewer.exe"))
    # Every server asks for an account unless a test says otherwise; nothing touches the network.
    monkeypatch.setattr(connect_ui.rfb, "security_types", lambda *a, **k: (17, 117, 113))
    return calls


SHARED_PROFILES = (
    ("ultravnc", "UltraVNC", "ultravnc", "account", []),
    ("offices", "Offices (SecureVNC)", "ultravnc", "account", ["securevnc"]),
    ("vnc-password", "VNC password", "ultravnc", "password", []),
    ("pis", "Pis", "realvnc", "account", []),
    ("pis-password", "Pis (password)", "realvnc", "password", []),
)


@pytest.fixture
def window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    folder = paths.profiles_dir
    folder.mkdir(parents=True)
    for pid, name, tool, login, options in SHARED_PROFILES:
        data = {"schema": 1, "id": pid, "name": name, "tool": tool, "login": login,
                "options": options}  # fmt: skip
        (folder / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")
    hl, offices = HostList().add_group("Offices")
    hl, pis = hl.add_group("Pis")
    hl = hl.set_group_profile(offices.id, "offices")
    hl = hl.set_group_profile(pis.id, "pis")
    hl, _a = hl.add_host("PC-A", offices.id, address="10.0.0.1")
    hl, _b = hl.add_host("PC-B", offices.id)
    hl, _p = hl.add_host("PI-1", pis.id, address="10.0.1.1")
    hl, _w = hl.add_host("Ward 2A - Desk", pis.id)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(paths, {"schema": 1, "recent_lists": [str(path)]})
    yield win
    win.close()


def _select(win: CapyWindow, *names: str) -> None:
    doc = win.hosts.document
    ids = [h.id for h in doc.hosts.hosts if h.name in names] if doc else []
    win.hosts.table.select_ids(ids)


def _answer_with(
    monkeypatch: pytest.MonkeyPatch, user: str, password: str, asked: list[str]
) -> None:
    def answer(dialog: CredentialDialog) -> int:
        asked.append(dialog.windowTitle())
        dialog.user.setText(user)
        dialog.password.setText(password)
        return 1  # Accepted

    monkeypatch.setattr(CredentialDialog, "exec", answer)


def test_each_profile_asks_once_and_keeps_its_own_password(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    _answer_with(monkeypatch, "ana", "domain-pass", asked)
    _select(window, "PC-A")
    window.hosts.connect_selected()
    _select(window, "PC-B")
    window.hosts.connect_selected()
    assert len(asked) == 1  # same profile: remembered for the rest of the session
    _answer_with(monkeypatch, "pi", "pi-pass", asked)
    _select(window, "PI-1")
    window.hosts.connect_selected()
    assert len(asked) == 2  # another profile asks for its own
    domain, pi = Credential("ana", "domain-pass"), Credential("pi", "pi-pass")
    assert launched == [
        ("ultravnc", "10.0.0.1", None, domain, ("securevnc",)),
        ("ultravnc", "PC-B", None, domain, ("securevnc",)),  # a computer name is its address
        ("realvnc", "10.0.1.1", None, pi, ()),
    ]
    window.hosts.forget_passwords()
    assert not window.hosts.connector.credentials


def test_hosts_with_different_profiles_open_together(
    window: CapyWindow, launched: list[Launch]
) -> None:
    window.hosts.connector.credentials.remember("offices", Credential("ana", "x"))
    window.hosts.connector.credentials.remember("pis", Credential("pi", "y"))
    _select(window, "PC-A", "PI-1")
    window.hosts.connect_selected()
    assert sorted(call[0] for call in launched) == ["realvnc", "ultravnc"]


def test_a_host_without_a_usable_address_is_not_sent_to_the_viewer(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()) or 0)
    _select(window, "Ward 2A - Desk")
    window.hosts.connect_selected()
    assert launched == [] and "Ward 2A - Desk" in shown[0]
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    window.hosts.connector.credentials.remember("pis", Credential("pi", "y"))
    _select(window, "Ward 2A - Desk", "PI-1")
    window.hosts.connect_selected()
    assert [call[1] for call in launched] == ["10.0.1.1"]  # the other one still opens
    assert "skipped" in shown[-1]


def test_cancelling_the_password_starts_nothing(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CredentialDialog, "exec", lambda dialog: 0)
    _select(window, "PC-A")
    window.hosts.connect_selected()
    assert launched == [] and not window.hosts.connector.credentials


def test_a_profile_this_pc_lacks_is_reported(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    started = window.hosts.connector.connect(
        [Request("PC-X", connect_ui.Target("x"), "from-elsewhere")]
    )
    assert started == 0 and launched == []
    assert "from-elsewhere" in shown[0] and "PC-X" in shown[0]


def test_many_hosts_at_once_are_confirmed_first(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.connector.credentials.remember("ultravnc", Credential("ana", "x"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    requests = [Request(f"PC-{n}", connect_ui.Target(f"PC-{n}")) for n in range(6)]
    assert window.hosts.connector.connect(requests) == 0 and launched == []
    assert window.hosts.connector.connect(requests[:5]) == 5  # up to five: no question


def test_password_prompt_asks_for_a_user_only_for_account_profiles(window: CapyWindow) -> None:
    connector = window.hosts.connector
    password_only = CredentialDialog(
        None, connector.resolve("vnc-password"), "PC-A", on_command_line=True
    )
    assert not password_only.wants_user
    ok = password_only.buttons.button(QDialogButtonBox.StandardButton.Ok)
    password_only.password.setText("x")
    assert ok.isEnabled()
    account = CredentialDialog(None, connector.resolve("pis"), "PI-1", on_command_line=False)
    ok = account.buttons.button(QDialogButtonBox.StandardButton.Ok)
    account.password.setText("x")
    assert not ok.isEnabled()  # the user is needed too
    account.user.setText("pi")
    assert ok.isEnabled() and account.credential() == Credential("pi", "x")


def test_the_host_dialog_offers_following_the_group_or_a_profile(window: CapyWindow) -> None:
    doc = window.hosts.document
    assert doc is not None
    host = next(h for h in doc.hosts.hosts if h.name == "PI-1")
    picker = window.hosts._profile_picker(doc.hosts)  # pyright: ignore[reportPrivateUsage]
    dialog = HostDialog(None, doc.hosts, host, profiles=picker)
    assert dialog.profile.currentData() == ""  # follows its group
    assert dialog.profile.itemText(0) == "From group “Pis”: Pis"
    offices = dialog.group.findText("Offices")
    dialog.group.setCurrentIndex(offices)
    assert "SecureVNC" in dialog.profile.itemText(0)  # follows the newly chosen group
    dialog.profile.setCurrentIndex(dialog.profile.findData("pis-password"))
    assert dialog.values().profile == "pis-password"


def _set_profile(window: CapyWindow, name: str, profile: str) -> None:
    doc = window.hosts.document
    assert doc is not None
    host = next(h for h in doc.hosts.hosts if h.name == name)
    window.hosts._commit(doc.hosts.set_hosts_profile([host.id], profile))  # pyright: ignore[reportPrivateUsage]


def test_details_show_the_profile_s_name(window: CapyWindow) -> None:
    _select(window, "PI-1")
    assert window.hosts.details.shown_value("profile") == "Pis"  # the group's, named plainly


def test_manual_connection_uses_the_chosen_profile(
    window: CapyWindow, launched: list[Launch]
) -> None:
    dialog = ManualConnectDialog(None, window.hosts.connector.choices(), "pis-password")
    dialog.address.setText(" 10.9.9.9 ")
    assert dialog.port.text() == "Default"
    request = dialog.request()
    assert request == Request("10.9.9.9", connect_ui.Target("10.9.9.9", None), "pis-password")
    dialog.port.setValue(5901)
    assert dialog.request().target.port == 5901


def test_copy_lists_every_column_shown_wherever_the_menu_opens(window: CapyWindow) -> None:
    _select(window, "PC-A", "PC-B")
    window.hosts.commands.copy_address.trigger()  # Ctrl+Shift+C
    assert sorted(QGuiApplication.clipboard().text().split("\n")) == ["10.0.0.1", "PC-B"]
    window.hosts.table.setColumnHidden(HostTable.COLUMNS.index("tags"), True)
    menu = QMenu()
    window.hosts.add_copy_menu(menu)  # pyright: ignore[reportPrivateUsage]
    copy = menu.actions()[0].menu()
    assert isinstance(copy, QMenu)
    items = [label(a) for a in copy.actions()]
    assert items == ["Name", "Status", "User", "&Address"]  # Tags is hidden: not offered
    assert copy.actions()[3] is window.hosts.commands.copy_address  # its shortcut shows
    copy.actions()[0].trigger()
    assert sorted(QGuiApplication.clipboard().text().split("\n")) == ["PC-A", "PC-B"]


def test_connect_commands_follow_the_selection(window: CapyWindow) -> None:
    a = window.hosts.commands
    _select(window)
    assert not a.connect_host.isEnabled() and not a.copy_address.isEnabled()
    assert a.manual_connect.isEnabled()
    _select(window, "PC-A")
    assert a.connect_host.isEnabled() and a.copy_address.isEnabled()
    # Enter connects only from the host table, never while typing somewhere else.
    assert a.connect_host.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert a.connect_host in window.hosts.table.actions()


def test_a_windows_password_is_never_sent_to_a_server_that_wants_a_vnc_password(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    offered = {"10.0.0.1": (17, 117, 2), "PC-B": (17, 117, 113)}
    probed: list[tuple[str, int]] = []

    def fake_probe(address: str, port: int, timeout: float = 3.0) -> tuple[int, ...]:
        probed.append((address, port))
        return offered[address]

    monkeypatch.setattr(connect_ui.rfb, "security_types", fake_probe)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    asked: list[str] = []
    _answer_with(monkeypatch, "ana", "domain-pass", asked)
    _select(window, "PC-A", "PC-B")
    window.hosts.connect_selected()
    assert sorted(probed) == [("10.0.0.1", 5900), ("PC-B", 5900)]
    assert [call[1] for call in launched] == ["PC-B"]  # only the one that asks for an account
    assert "PC-A" in shown[0] and "user and password" in shown[0]
    _select(window, "PC-A")
    launched.clear()
    asked.clear()
    window.hosts.connect_selected()
    assert launched == [] and asked == []  # refused before even asking for a password


def test_when_the_server_cannot_be_asked_the_viewer_still_opens(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*_args: object, **_kwargs: object) -> tuple[int, ...]:
        raise connect_ui.rfb.ProbeError("timed out")

    monkeypatch.setattr(connect_ui.rfb, "security_types", unreachable)
    window.hosts.connector.credentials.remember("offices", Credential("ana", "x"))
    _select(window, "PC-A")
    window.hosts.connect_selected()
    assert [call[1] for call in launched] == ["10.0.0.1"]  # the viewer reports what's wrong


def test_password_only_profiles_never_check_and_vnc_passwords_stop_at_8(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_probe(*_args: object, **_kwargs: object) -> tuple[int, ...]:
        raise AssertionError("password-only profiles connect without a check")

    monkeypatch.setattr(connect_ui.rfb, "security_types", must_not_probe)
    window.hosts.connector.credentials.remember("vnc-password", Credential("", "x"))
    target = connect_ui.Target("PC-Z")
    assert window.hosts.connector.connect([Request("PC-Z", target, "vnc-password")]) == 1
    vnc = CredentialDialog(
        None, window.hosts.connector.resolve("vnc-password"), "PC-Z", on_command_line=True
    )
    vnc.password.setText("123456789012")
    assert vnc.password.text() == "12345678"
    account = CredentialDialog(
        None, window.hosts.connector.resolve("ultravnc"), "PC-Z", on_command_line=True
    )
    account.password.setText("x" * 10_000)
    account.user.setText("u" * 10_000)
    assert len(account.password.text()) == 256 and len(account.user.text()) == 256


def test_hosts_with_no_profile_anywhere_use_the_shared_default(
    window: CapyWindow, launched: list[Launch]
) -> None:
    window.hosts.connector.catalogs.profiles.set_default("pis-password")
    window.hosts.connector.credentials.remember("pis-password", Credential("", "x"))
    assert window.hosts.connector.connect([Request("PI-9", connect_ui.Target("10.0.1.9"))]) == 1
    assert launched[0][0] == "realvnc"


def test_the_default_profile_chosen_in_settings_is_saved_for_everyone(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    page = dialog.group(HostsSettings).connections.profiles
    page.default.setCurrentIndex(page.default.findData("pis"))
    assert window.hosts.connector.catalogs.profiles.default_id() == "pis"
    assert window.hosts.connector.default_profile() == "pis"


def test_profile_rows_never_overlap(window: CapyWindow) -> None:
    # Like the page list once did: rows kept positions from before the theme's padding arrived.
    window.show()
    for theme in ("paper", "capypanel-dark"):
        window.set_theme(theme)
        dialog = window.settings_dialog()
        dialog.show_page("connections")
        dialog.show()
        QApplication.processEvents()
        rows = dialog.group(HostsSettings).connections.profiles.list
        top, below = rows.topLevelItem(0), rows.topLevelItem(1)
        assert top is not None and below is not None
        first, second = rows.visualItemRect(top), rows.visualItemRect(below)
        assert second.top() >= first.bottom(), theme
        dialog.close()


def test_a_missing_viewer_offers_to_open_settings(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(window, "open_settings", lambda page=None: opened.append(page or ""))
    monkeypatch.setattr(connect_ui.detect, "find_executable", lambda tool: None)

    def click_settings(box: QMessageBox) -> int:
        button = next(b for b in box.buttons() if b.text() == "Open &Settings")
        button.click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", click_settings)
    window.hosts.connector.credentials.remember("offices", Credential("ana", "x"))
    _select(window, "PC-A")
    window.hosts.connect_selected()
    assert opened == ["connections"]


def test_a_host_s_own_unavailable_profile_shows_checked_in_the_menu(window: CapyWindow) -> None:
    _set_profile(window, "PC-A", "gone-elsewhere")
    menu = QMenu()
    window.hosts._add_profile_menu(  # pyright: ignore[reportPrivateUsage]
        menu, {"gone-elsewhere"}, "follow", lambda p: None
    )
    submenu = menu.actions()[0].menu()
    assert isinstance(submenu, QMenu)
    checked = [label(a) for a in submenu.actions() if a.isChecked()]
    assert checked == ["gone-elsewhere (not available on this PC)"]


def test_a_profile_this_pc_lacks_falls_back_to_the_group_s(
    window: CapyWindow, launched: list[Launch]
) -> None:
    _set_profile(window, "PC-A", "gone-elsewhere")
    _select(window, "PC-A")
    assert window.hosts.details.shown_value("profile") == "Offices (SecureVNC)"
    window.hosts.connector.credentials.remember("offices", Credential("ana", "x"))
    window.hosts.connect_selected()
    assert launched[0][0] == "ultravnc" and launched[0][4] == ("securevnc",)


def test_a_profile_with_a_settings_file_hands_it_to_the_viewer(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    store = window.hosts.connector.catalogs.profiles
    offices = store.find("offices")
    assert offices is not None
    store.save(replace(offices, settings_file="offices.vnc"), b"[options]\r\nviewonly=1\r\n")
    given: list[Path | None] = []
    monkeypatch.setattr(connect_ui, "launch", lambda *args: given.append(args[5]))
    _answer_with(monkeypatch, "ana", "pw", [])
    _select(window, "PC-A")
    window.hosts.connect_selected()
    assert given == [store.folder / "offices.vnc"]


def test_remote_desktop_opens_without_asking_for_a_password(
    window: CapyWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = window.hosts.connector.catalogs.profiles
    store.save(ConnectionProfile("desk", "mstsc", "none", ("admin",), name="Desk"))
    monkeypatch.setattr(CredentialDialog, "exec", lambda _self: pytest.fail("asked for a password"))
    started = window.hosts.connector.connect([Request("PC-A", Target("10.0.0.1"), "desk")])
    assert started == 1
    assert launched == [("mstsc", "10.0.0.1", None, None, ("admin",))]


def _menu_on(monkeypatch: pytest.MonkeyPatch, show: Any) -> list[str]:
    """The texts of the menu `show` opens, without opening it."""
    seen: list[str] = []

    class Recorded(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            seen.extend(label(a) for a in self.actions() if a.text())

    monkeypatch.setattr(workspace_module, "QMenu", Recorded)
    show()
    return seen


def _items(tree: Any) -> list[Any]:
    found, stack = [], [tree.invisibleRootItem()]
    while stack:
        item = stack.pop()
        for i in range(item.childCount()):
            found.append(item.child(i))
            stack.append(item.child(i))
    return found


def test_right_click_acts_on_what_is_under_the_mouse(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.show()
    QApplication.processEvents()
    groups = window.hosts.nav.groups
    offices = next(i for i in _items(groups) if i.text(0).startswith("Offices"))
    pis = next(i for i in _items(groups) if i.text(0).startswith("Pis"))
    groups.setCurrentItem(pis)  # picked earlier
    empty = groups.viewport().rect().bottomLeft() + QPoint(5, -5)
    assert _menu_on(monkeypatch, lambda: window.hosts._group_menu(empty)) == [
        "Add &group…", "&Manage groups…"
    ]  # fmt: skip
    texts = _menu_on(
        monkeypatch, lambda: window.hosts._group_menu(groups.visualItemRect(offices).center())
    )
    assert "&Edit selected…" in texts  # the group under the mouse, which is now picked
    assert window.hosts.nav.selected_group_id() == offices.data(0, Qt.ItemDataRole.UserRole + 1)
    table_empty = window.hosts.table.viewport().rect().bottomLeft() + QPoint(5, -5)
    assert _menu_on(monkeypatch, lambda: window.hosts._item_menu(table_empty)) == [
        "Add &host…", "Add &group…"
    ]  # fmt: skip
    window.close()


def test_connect_is_a_dropdown_that_works_with_no_host_selected(window: CapyWindow) -> None:
    _select(window)  # nothing selected
    button = window.hosts.toolbar.connect_button
    assert button.isEnabled()  # its menu has Manual connection, which needs no host
    assert button.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup  # like the others
    window.hosts._fill_connect_menu()  # pyright: ignore[reportPrivateUsage]
    first = window.hosts.toolbar.connect_menu.actions()[0]
    assert first is window.hosts.commands.connect_host and not first.isEnabled()
