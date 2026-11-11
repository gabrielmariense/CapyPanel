import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from capypanel.core import credstore, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.accounts import Link, Scope
from capypanel.core.hosts.model import HostList
from capypanel.core.remote.access import Account
from capypanel.core.tools.connect import Credential
from capypanel.ui import connect as connect_ui
from capypanel.ui.checks import AccountDialog
from capypanel.ui.connect import CredentialDialog
from capypanel.ui.hosts_tool.settings import HostsSettings
from capypanel.ui.settings.connections import ProfilesSection


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Credential | None]:
    """The credential each launch got; no program starts and nothing touches the network."""
    calls: list[Credential | None] = []

    def fake_launch(tool: Any, exe: Any, target: Any, credential: Any = None, *_a: Any) -> None:
        calls.append(credential)

    monkeypatch.setattr(connect_ui, "launch", fake_launch)
    monkeypatch.setattr(connect_ui.detect, "find_executable", lambda tool: Path("viewer.exe"))
    monkeypatch.setattr(connect_ui.rfb, "security_types", lambda *a, **k: (17, 117, 113))
    return calls


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    paths.profiles_dir.mkdir(parents=True)
    data = {"schema": 1, "id": "offices", "name": "Offices", "tool": "ultravnc",
            "login": "account", "options": []}  # fmt: skip
    (paths.profiles_dir / "offices.json").write_text(json.dumps(data), encoding="utf-8")
    hl, offices = HostList().add_group("Offices")
    hl = hl.set_group_profile(offices.id, "offices")
    hl, _a = hl.add_host("PC-A", offices.id, address="192.0.2.10")
    listfile.save(tmp_path / "office.json", hl, expected=None)
    return paths


def _open(qapp: QApplication, paths: settings.Paths, prefs: dict[str, Any]) -> CapyWindow:
    """CapyPanel opening, with these settings."""
    path = paths.profiles_dir.parent.parent / "office.json"
    return CapyWindow(paths, {"schema": 1, "recent_lists": [str(path)], **prefs})


@pytest.fixture
def window(qapp: QApplication, paths: settings.Paths) -> Iterator[CapyWindow]:
    yield _open(qapp, paths, {})


def _connect(win: CapyWindow) -> None:
    doc = win.hosts.document
    win.hosts.table.select_ids([h.id for h in doc.hosts.hosts] if doc else [])
    win.hosts.connect_selected()


def _profiles(win: CapyWindow) -> ProfilesSection:
    return win.settings_dialog().group(HostsSettings).connections.profiles


def _type(monkeypatch: pytest.MonkeyPatch, asked: list[str], remember: bool = False) -> None:
    def answer(dialog: CredentialDialog) -> int:
        asked.append(dialog.windowTitle())
        assert not dialog.remember.isChecked()  # unticked until you tick it
        dialog.user.setText("CORP\\ana")
        dialog.password.setText("x")
        dialog.remember.setChecked(remember)
        return 1  # Accepted

    monkeypatch.setattr(CredentialDialog, "exec", answer)


def test_passwords_are_kept_in_memory_only_unless_remember_is_ticked(
    window: CapyWindow, launched: list[Credential | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = _profiles(window)
    assert not hasattr(profiles, "passwords")  # no Kept in setting any more
    asked: list[str] = []
    _type(monkeypatch, asked)
    _connect(window)
    assert launched == [Credential("CORP\\ana", "x")] and len(asked) == 1
    assert credstore.names("") == []  # nothing left the memory


def test_a_remembered_password_is_used_the_next_time_capypanel_opens(
    qapp: QApplication,
    window: CapyWindow,
    paths: settings.Paths,
    launched: list[Credential | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    _type(monkeypatch, asked, remember=True)
    _connect(window)
    assert credstore.read("profile/offices") == ("CORP\\ana", "x")
    admin = Account("CORP\\admin", "y")
    window.hosts.accounts.use(Link(admin.user, Scope.ALL), admin, remember=True)

    later = _open(qapp, paths, {"accounts": window.hosts.prefs["accounts"]})
    monkeypatch.setattr(CredentialDialog, "exec", lambda _self: pytest.fail("asked again"))
    _connect(later)
    assert launched[-1] == Credential("CORP\\ana", "x")
    assert later.hosts.accounts.known("CORP\\admin") == admin
    kept = later.hosts.kept_logins()
    assert [(k.used_for, k.saved) for k in kept] == [("Offices", True), ("Every PC", True)]
    for login in kept:  # saved ones can be forgotten too
        login.forget()
    assert credstore.names("") == [] and later.hosts.accounts.known("CORP\\admin") is None


def test_every_login_window_has_remember_unticked(window: CapyWindow) -> None:
    def note(dialog: QDialog) -> str:
        return " ".join(label.text() for label in dialog.findChildren(QLabel))

    ready = window.hosts.connector.resolve("offices")
    profile_login = CredentialDialog(None, ready, "PC-A", on_command_line=False)
    assert not profile_login.remember.isChecked()
    assert profile_login.remember.text() == AccountDialog(None, "Why").remember.text()
    assert "only for hosts with this connection profile" in note(profile_login)
    assert not AccountDialog(None, "Why").remember.isChecked()


def test_typing_a_remembered_password_again_keeps_it_remembered(window: CapyWindow) -> None:
    """A PC rejected the account: its window starts with Remember ticked when Windows
    already keeps that password, so typing it again doesn't delete the saved one."""
    hosts = window.hosts
    admin = Account("CORP\\admin", "old")
    hosts.accounts.use(Link(admin.user, Scope.ALL), admin, remember=True)
    assert hosts.accounts.saved(admin.user)
    again = AccountDialog(None, "Why", admin.user, saved=hosts.accounts.saved(admin.user))
    assert again.remember.isChecked()
    again.password.setText("new")
    hosts.accounts.use(Link(admin.user, Scope.ALL), again.account(),
                       remember=again.remember.isChecked())  # fmt: skip
    assert credstore.read("account/corp\\admin") == (admin.user, "new")

    # Another account typed there isn't remembered unless ticked; a tick set by hand stays.
    other = AccountDialog(None, "Why", admin.user, saved=True)
    other.user.setText("CORP\\helpdesk")
    assert not other.remember.isChecked()
    other.user.setText(admin.user)
    assert other.remember.isChecked()
    other.remember.click()  # off, by hand
    other.password.setText("x")
    assert not other.remember.isChecked()
    temporary = Account("CORP\\temp", "t")
    hosts.accounts.keep(temporary, remember=False)
    unsaved = AccountDialog(None, "Why", temporary.user,
                            saved=hosts.accounts.saved(temporary.user))  # fmt: skip
    assert not unsaved.remember.isChecked()
