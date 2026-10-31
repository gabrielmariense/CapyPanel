import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from capypanel.core import credstore, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote.sessions import Account
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


def _type(monkeypatch: pytest.MonkeyPatch, asked: list[str]) -> None:
    def answer(dialog: CredentialDialog) -> int:
        asked.append(dialog.windowTitle())
        dialog.user.setText("CORP\\ana")
        dialog.password.setText("x")
        return 1  # Accepted

    monkeypatch.setattr(CredentialDialog, "exec", answer)


def test_passwords_are_kept_in_memory_only_unless_saving_is_chosen(
    window: CapyWindow, launched: list[Credential | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = _profiles(window)
    assert not profiles.save_passwords_choice()  # the default
    assert profiles.passwords.currentText() == "Temporary credentials"
    assert profiles.passwords_row.description.text() == "Forgotten when CapyPanel closes."
    asked: list[str] = []
    _type(monkeypatch, asked)
    _connect(window)
    assert launched == [Credential("CORP\\ana", "x")] and len(asked) == 1
    assert credstore.names("") == []  # nothing left the memory


def test_a_saved_password_is_used_the_next_time_capypanel_opens(
    qapp: QApplication,
    window: CapyWindow,
    paths: settings.Paths,
    launched: list[Credential | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profiles = _profiles(window)
    profiles.passwords.setCurrentIndex(1)  # Save in Windows Credential Manager
    assert window.hosts.prefs["save_passwords"] is True
    assert "Forget typed passwords" in profiles.passwords_row.description.text()
    assert "domain accounts" in profiles.passwords.toolTip()  # the details, for who looks
    asked: list[str] = []
    _type(monkeypatch, asked)
    _connect(window)
    assert credstore.read("profile/offices") == ("CORP\\ana", "x")
    window.hosts._save_account(Account("CORP\\admin", "y"))  # pyright: ignore[reportPrivateUsage]

    later = _open(qapp, paths, {"save_passwords": True})
    monkeypatch.setattr(CredentialDialog, "exec", lambda _self: pytest.fail("asked again"))
    _connect(later)
    assert launched[-1] == Credential("CORP\\ana", "x")
    assert later.hosts._account == Account("CORP\\admin", "y")  # pyright: ignore[reportPrivateUsage]
    later.hosts._fill_connect_menu()  # pyright: ignore[reportPrivateUsage]
    assert later.hosts.forget_menu.isEnabled()  # saved ones can be forgotten too
    later.hosts.forget_passwords()
    assert credstore.names("") == [] and later.hosts._account is None  # pyright: ignore[reportPrivateUsage]


def test_the_password_boxes_say_where_the_password_goes(window: CapyWindow) -> None:
    def note(dialog: QDialog) -> str:
        return " ".join(label.text() for label in dialog.findChildren(QLabel))

    ready = window.hosts.connector.resolve("offices")
    assert "never saved" in note(CredentialDialog(None, ready, "PC-A", on_command_line=False))
    saved = CredentialDialog(None, ready, "PC-A", on_command_line=False, saved=True)
    assert "Windows Credential Manager" in note(saved) and "never saved" not in note(saved)
    assert "never saved" in note(AccountDialog(None, "Why"))
    assert "never saved" not in note(AccountDialog(None, "Why", saved=True))


def test_keeping_passwords_until_closing_again_deletes_the_saved_ones(
    window: CapyWindow, launched: list[Credential | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = _profiles(window)
    profiles.passwords.setCurrentIndex(1)
    _type(monkeypatch, [])
    _connect(window)
    window.hosts._save_account(Account("CORP\\admin", "y"))  # pyright: ignore[reportPrivateUsage]
    assert len(credstore.names("")) == 2
    profiles.passwords.setCurrentIndex(0)  # Keep until CapyPanel closes
    assert window.hosts.prefs["save_passwords"] is False and credstore.names("") == []
    assert "offices" in window.hosts.connector.credentials  # typed this session: still kept
