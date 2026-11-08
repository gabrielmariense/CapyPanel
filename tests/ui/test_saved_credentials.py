from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel.core import credstore, settings
from capypanel.core.hosts.accounts import Link, Scope
from capypanel.core.printers import usm
from capypanel.core.remote.access import Account
from capypanel.core.tools.connect import Credential
from capypanel.ui import saved_credentials
from capypanel.ui.hosts_tool.settings import HostsSettings
from capypanel.ui.printers_tool import refresh
from capypanel.ui.saved_credentials import (
    KeptLogin,
    SavedCredentialsDialog,
    forget_details,
    kept_text,
)


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "save_passwords": True})
    yield win
    win.close()


def _keep_some(win: CapyWindow) -> None:
    """A saved profile password and an account typed for every PC (in memory only)."""
    profile = win.hosts.connector.choices()[0][0]
    win.hosts.connector.credentials.remember(profile, Credential("EXAMPLE\\ana", "x"))
    win.hosts.accounts.use(Link("EXAMPLE\\svc", Scope.ALL), Account("EXAMPLE\\svc", "y"),
                           remember=False)  # fmt: skip


def _rows(dialog: SavedCredentialsDialog) -> list[list[str]]:
    table = dialog.table
    return [
        [table.topLevelItem(r).text(c) for c in range(4)]  # type: ignore[union-attr]
        for r in range(table.topLevelItemCount())
    ]


def test_the_window_lists_the_connection_logins_by_what_they_re_used_for(
    window: CapyWindow,
) -> None:
    _keep_some(window)
    dialog = SavedCredentialsDialog(None, window.kept_logins)
    rows = _rows(dialog)
    assert len(rows) == 2
    assert [r[0] for r in rows] == sorted((r[0] for r in rows), key=str.casefold)
    assert ["Every PC", "Hosts › Accounts", "EXAMPLE\\svc", "Temporary"] in rows
    assert any(r[2:] == ["EXAMPLE\\ana", "Credential Manager"] for r in rows)
    assert not any("x" in r or "y" in r for r in rows)  # no password


def test_printers_snmp_logins_are_not_listed(window: CapyWindow) -> None:
    # They're set in Settings › Printers › Connecting, not with the connection logins.
    refresh.save_v3_account(usm.Account("snmp-reader", usm.Auth.SHA, "auth-pass"))
    credstore.save(refresh.COMMUNITY, "s3cret")
    assert window.kept_logins() == []


def test_forget_deletes_the_picked_login_and_forget_all_the_rest(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keep_some(window)
    dialog = SavedCredentialsDialog(None, window.kept_logins)
    [account] = [
        dialog.table.topLevelItem(r)
        for r in range(2)
        if dialog.table.topLevelItem(r).text(0) == "Every PC"  # type: ignore[union-attr]
    ]
    assert account is not None
    dialog.table.setCurrentItem(account)
    dialog.forget_button.click()
    assert window.hosts.accounts.known("EXAMPLE\\svc") is None
    assert len(_rows(dialog)) == 1
    asked: list[str] = []

    def answer(_parent: Any, _title: str, text: str, action: str, details: str) -> bool:
        asked.extend([text, action, details])
        return True

    monkeypatch.setattr(saved_credentials, "confirm", answer)
    dialog.forget_all_button.click()
    assert asked[:2] == ["Forget this login?", "&Forget 1 login"]
    assert asked[2].startswith("Saved in Credential Manager:\n• ")
    assert "EXAMPLE\\ana" in asked[2]
    assert _rows(dialog) == [] and credstore.names("") == []
    assert not dialog.forget_button.isEnabled() and not dialog.forget_all_button.isEnabled()


def test_a_login_windows_wont_delete_is_said_once(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise OSError("access denied")

    logins = [KeptLogin(name, "Tool", "user", True, refuse) for name in ("A", "B")]
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    monkeypatch.setattr(saved_credentials, "confirm", lambda *_a: True)
    dialog = SavedCredentialsDialog(None, lambda: logins)
    dialog.forget_all_button.click()
    assert len(warned) == 1 and "access denied" in warned[0]


def test_settings_counts_what_s_kept_and_opens_the_window(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keep_some(window)
    dialog = window.settings_dialog()
    row = dialog.group(HostsSettings).connections.profiles.saved_row
    assert row.description.text() == "2 kept: 1 in Credential Manager, 1 temporary."

    def forget_everything(win: SavedCredentialsDialog) -> int:
        for login in window.kept_logins():
            login.forget()
        return 0

    monkeypatch.setattr(SavedCredentialsDialog, "exec", forget_everything)
    dialog.group(HostsSettings).connections.profiles.manage_button.click()
    assert row.description.text() == "None kept."  # Settings shows it at once


def test_the_settings_line_names_both_places() -> None:
    def login(saved: bool) -> KeptLogin:
        return KeptLogin("A", "Tool", "user", saved, lambda: None)

    assert kept_text([]) == "None kept."
    assert kept_text([login(True)]) == "1 kept: 1 in Credential Manager."
    assert kept_text([login(False)] * 2) == "2 kept: 2 temporary."


def test_connect_opens_saved_credentials(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[int] = []
    monkeypatch.setattr(SavedCredentialsDialog, "exec", lambda _self: opened.append(1) or 0)
    window.hosts._fill_connect_menu()  # pyright: ignore[reportPrivateUsage]
    [entry] = [
        a for a in window.hosts.toolbar.connect_menu.actions() if a.text() == "Sa&ved credentials…"
    ]
    entry.trigger()
    assert opened == [1]


def test_forget_all_names_each_login_by_where_it_s_kept() -> None:
    ultra = KeptLogin("UltraVNC", "UltraVNC Viewer", "EXAMPLE\\ana", True, lambda: None)
    vnc = KeptLogin("RealVNC", "RealVNC Viewer", "(password only)", False, lambda: None)
    assert forget_details([ultra, vnc]) == (
        "Saved in Credential Manager:\n"
        "• UltraVNC · EXAMPLE\\ana\n\n"
        "Temporary:\n"
        "• RealVNC · (password only)\n\n"
        "CapyPanel asks for them again when it needs them."
    )
