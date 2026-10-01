from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu, QMessageBox

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.tools.connect import Credential
from capypanel.ui import connect as connect_ui
from capypanel.ui.connect import CredentialDialog, ManualConnectDialog, Request
from capypanel.ui.hosts import HostDialog
from capypanel.ui.main_window.window import MainWindow

Launch = tuple[str, str, int | None, Credential | None, tuple[str, ...]]


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Launch]:
    """Records launches instead of starting programs; every viewer counts as installed."""
    calls: list[Launch] = []

    def fake_launch(
        tool: Any, exe: Path, target: Any, credential: Any = None, options: Any = ()
    ) -> None:
        calls.append((tool.id, target.address, target.port, credential, tuple(options)))

    monkeypatch.setattr(connect_ui, "launch", fake_launch)
    monkeypatch.setattr(connect_ui.detect, "find_executable", lambda tool: Path("viewer.exe"))
    # Every server asks for an account unless a test says otherwise; nothing touches the network.
    monkeypatch.setattr(connect_ui.rfb, "security_types", lambda *a, **k: (17, 117, 113))
    return calls


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, offices = HostList().add_group("Offices")
    hl, pis = hl.add_group("Pis")
    hl = hl.set_group_profile(offices.id, "ultravnc-account-securevnc")
    hl = hl.set_group_profile(pis.id, "realvnc-account")
    hl, _a = hl.add_host("PC-A", offices.id, address="10.0.0.1")
    hl, _b = hl.add_host("PC-B", offices.id)
    hl, _p = hl.add_host("PI-1", pis.id, address="10.0.1.1")
    hl, _w = hl.add_host("Ward 2A - Desk", pis.id)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(path)]})
    yield win
    win.close()


def _select(win: MainWindow, *names: str) -> None:
    ids = [h.id for h in win.document.hosts.hosts if h.name in names] if win.document else []
    win.table.select_ids(ids)


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
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []
    _answer_with(monkeypatch, "ana", "domain-pass", asked)
    _select(window, "PC-A")
    window.connect_selected()
    _select(window, "PC-B")
    window.connect_selected()
    assert len(asked) == 1  # same profile: remembered for the rest of the session
    _answer_with(monkeypatch, "pi", "pi-pass", asked)
    _select(window, "PI-1")
    window.connect_selected()
    assert len(asked) == 2  # another profile asks for its own
    domain, pi = Credential("ana", "domain-pass"), Credential("pi", "pi-pass")
    assert launched == [
        ("ultravnc", "10.0.0.1", None, domain, ("securevnc",)),
        ("ultravnc", "PC-B", None, domain, ("securevnc",)),  # a computer name is its address
        ("realvnc", "10.0.1.1", None, pi, ()),
    ]
    window.forget_passwords()
    assert not window.connector.credentials


def test_hosts_with_different_profiles_open_together(
    window: MainWindow, launched: list[Launch]
) -> None:
    window.connector.credentials.remember("ultravnc-account-securevnc", Credential("ana", "x"))
    window.connector.credentials.remember("realvnc-account", Credential("pi", "y"))
    _select(window, "PC-A", "PI-1")
    window.connect_selected()
    assert sorted(call[0] for call in launched) == ["realvnc", "ultravnc"]


def test_a_host_without_a_usable_address_is_not_sent_to_the_viewer(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box.text()) or 0)
    _select(window, "Ward 2A - Desk")
    window.connect_selected()
    assert launched == [] and "Ward 2A - Desk" in shown[0]
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    window.connector.credentials.remember("realvnc-account", Credential("pi", "y"))
    _select(window, "Ward 2A - Desk", "PI-1")
    window.connect_selected()
    assert [call[1] for call in launched] == ["10.0.1.1"]  # the other one still opens
    assert "skipped" in shown[-1]


def test_cancelling_the_password_starts_nothing(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CredentialDialog, "exec", lambda dialog: 0)
    _select(window, "PC-A")
    window.connect_selected()
    assert launched == [] and not window.connector.credentials


def test_a_profile_this_pc_lacks_is_reported(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    started = window.connector.connect([Request("PC-X", connect_ui.Target("x"), "from-elsewhere")])
    assert started == 0 and launched == []
    assert "from-elsewhere" in shown[0] and "PC-X" in shown[0]


def test_many_hosts_at_once_are_confirmed_first(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    window.connector.credentials.remember("ultravnc-password", Credential("", "x"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    requests = [Request(f"PC-{n}", connect_ui.Target(f"PC-{n}")) for n in range(6)]
    assert window.connector.connect(requests) == 0 and launched == []
    assert window.connector.connect(requests[:5]) == 5  # up to five: no question


def test_password_prompt_asks_for_a_user_only_for_account_profiles(window: MainWindow) -> None:
    connector = window.connector
    password_only = CredentialDialog(
        None, connector.resolve("ultravnc-password"), "PC-A", on_command_line=True
    )
    assert not password_only.wants_user
    ok = password_only.buttons.button(QDialogButtonBox.StandardButton.Ok)
    password_only.password.setText("x")
    assert ok.isEnabled()
    account = CredentialDialog(
        None, connector.resolve("realvnc-account"), "PI-1", on_command_line=False
    )
    ok = account.buttons.button(QDialogButtonBox.StandardButton.Ok)
    account.password.setText("x")
    assert not ok.isEnabled()  # the user is needed too
    account.user.setText("pi")
    assert ok.isEnabled() and account.credential() == Credential("pi", "x")


def test_the_host_dialog_offers_following_the_group_or_a_profile(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None
    host = next(h for h in doc.hosts.hosts if h.name == "PI-1")
    picker = window._profile_picker(doc.hosts)  # pyright: ignore[reportPrivateUsage]
    dialog = HostDialog(None, doc.hosts, host, profiles=picker)
    assert dialog.profile.currentData() == ""  # follows its group
    assert "Pis" in dialog.profile.itemText(0) and "RealVNC" in dialog.profile.itemText(0)
    offices = dialog.group.findText("Offices")
    dialog.group.setCurrentIndex(offices)
    assert "SecureVNC" in dialog.profile.itemText(0)  # follows the newly chosen group
    dialog.profile.setCurrentIndex(dialog.profile.findData("realvnc-password"))
    assert dialog.values().profile == "realvnc-password"


def test_the_profile_menu_sets_several_hosts_at_once(window: MainWindow) -> None:
    _select(window, "PC-A", "PC-B")
    menu = QMenu()
    hosts = window._selected_hosts()  # pyright: ignore[reportPrivateUsage]
    ids = [h.id for h in hosts]
    window._add_profile_menu(  # pyright: ignore[reportPrivateUsage]
        menu, {h.profile for h in hosts}, "follow", lambda p: window.set_hosts_profile(ids, p)
    )
    submenu = menu.actions()[0].menu()
    assert isinstance(submenu, QMenu)
    items = {a.text(): a for a in submenu.actions() if not a.isSeparator()}
    assert items["follow"].isChecked()  # neither host has its own profile
    pick = next(a for text, a in items.items() if text.startswith("RealVNC Viewer — password"))
    pick.trigger()
    doc = window.document
    assert doc is not None
    assert {h.profile for h in doc.hosts.hosts if h.name in ("PC-A", "PC-B")} == {
        "realvnc-password"
    }


def test_details_say_where_the_profile_comes_from(window: MainWindow) -> None:
    _select(window, "PI-1")
    shown = window.details.shown_value("connection")
    assert "RealVNC Viewer — user and password" in shown and "Pis" in shown


def test_manual_connection_uses_the_chosen_profile(
    window: MainWindow, launched: list[Launch]
) -> None:
    dialog = ManualConnectDialog(None, window.connector.choices(), "realvnc-password")
    dialog.address.setText(" 10.9.9.9 ")
    assert dialog.port.text() == "Default"
    request = dialog.request()
    assert request == Request("10.9.9.9", connect_ui.Target("10.9.9.9", None), "realvnc-password")
    dialog.port.setValue(5901)
    assert dialog.request().target.port == 5901


def test_copy_address_and_name(window: MainWindow) -> None:
    _select(window, "PC-A", "PC-B")
    window.commands.copy_address.trigger()
    assert sorted(QGuiApplication.clipboard().text().split("\n")) == ["10.0.0.1", "PC-B"]
    window.commands.copy_name.trigger()
    assert sorted(QGuiApplication.clipboard().text().split("\n")) == ["PC-A", "PC-B"]


def test_connect_commands_follow_the_selection(window: MainWindow) -> None:
    a = window.commands
    _select(window)
    assert not a.connect_vnc.isEnabled() and not a.copy_address.isEnabled()
    assert a.manual_connect.isEnabled()
    _select(window, "PC-A")
    assert a.connect_vnc.isEnabled() and a.copy_name.isEnabled()
    # Enter connects only from the host table, never while typing somewhere else.
    assert a.connect_vnc.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert a.connect_vnc in window.table.actions()


def test_a_windows_password_is_never_sent_to_a_server_that_wants_a_vnc_password(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
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
    window.connect_selected()
    assert sorted(probed) == [("10.0.0.1", 5900), ("PC-B", 5900)]
    assert [call[1] for call in launched] == ["PC-B"]  # only the one that asks for an account
    assert "PC-A" in shown[0] and "VNC password" in shown[0]
    _select(window, "PC-A")
    launched.clear()
    asked.clear()
    window.connect_selected()
    assert launched == [] and asked == []  # refused before even asking for a password


def test_when_the_server_cannot_be_asked_the_viewer_still_opens(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(*_args: object, **_kwargs: object) -> tuple[int, ...]:
        raise connect_ui.rfb.ProbeError("timed out")

    monkeypatch.setattr(connect_ui.rfb, "security_types", unreachable)
    window.connector.credentials.remember("ultravnc-account-securevnc", Credential("ana", "x"))
    _select(window, "PC-A")
    window.connect_selected()
    assert [call[1] for call in launched] == ["10.0.0.1"]  # the viewer reports what's wrong


def test_password_only_profiles_never_check_and_vnc_passwords_stop_at_8(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    def must_not_probe(*_args: object, **_kwargs: object) -> tuple[int, ...]:
        raise AssertionError("password-only profiles connect without a check")

    monkeypatch.setattr(connect_ui.rfb, "security_types", must_not_probe)
    window.connector.credentials.remember("ultravnc-password", Credential("", "x"))
    assert window.connector.connect([Request("PC-Z", connect_ui.Target("PC-Z"))]) == 1
    vnc = CredentialDialog(
        None, window.connector.resolve("ultravnc-password"), "PC-Z", on_command_line=True
    )
    vnc.password.setText("123456789012")
    assert vnc.password.text() == "12345678"
    account = CredentialDialog(
        None, window.connector.resolve("ultravnc-account"), "PC-Z", on_command_line=True
    )
    account.password.setText("x" * 10_000)
    account.user.setText("u" * 10_000)
    assert len(account.password.text()) == 256 and len(account.user.text()) == 256
