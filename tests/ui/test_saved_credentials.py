from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel.core import credstore, settings
from capypanel.core.printers import usm
from capypanel.core.remote.sessions import Account
from capypanel.core.tools.connect import Credential
from capypanel.ui import saved_credentials
from capypanel.ui.hosts_tool.settings import HostsSettings
from capypanel.ui.printers_tool import refresh
from capypanel.ui.printers_tool.settings import PrintersSettings
from capypanel.ui.saved_credentials import KeptLogin, SavedCredentialsDialog, kept_text


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "save_passwords": True})
    yield win
    win.close()


def _keep_some(win: CapyWindow) -> None:
    """A saved profile password, an account typed for logged-on users (in memory only) and
    the printers' v3 account."""
    profile = win.hosts.connector.choices()[0][0]
    win.hosts.connector.credentials.remember(profile, Credential("EXAMPLE\\ana", "x"))
    win.hosts._account = Account("EXAMPLE\\svc", "y")  # pyright: ignore[reportPrivateUsage]
    refresh.save_v3_account(usm.Account("snmp-reader", usm.Auth.SHA, "auth-pass"))


def _rows(dialog: SavedCredentialsDialog) -> list[list[str]]:
    table = dialog.table
    return [
        [table.topLevelItem(r).text(c) for c in range(4)]  # type: ignore[union-attr]
        for r in range(table.topLevelItemCount())
    ]


def test_the_window_lists_every_tool_s_logins_by_what_they_re_used_for(
    window: CapyWindow,
) -> None:
    _keep_some(window)
    credstore.save(refresh.COMMUNITY, "s3cret")
    dialog = SavedCredentialsDialog(None, window.kept_logins)
    rows = _rows(dialog)
    assert [r[0] for r in rows] == sorted((r[0] for r in rows), key=str.casefold)
    assert ["Logged-on users", "Hosts › Refresh", "EXAMPLE\\svc", "Until CapyPanel closes"] in rows
    assert ["SNMP account (v3)", "Printers › Refresh", "snmp-reader", "Credential Manager"] in rows
    assert ["SNMP community string (v2c)", "Printers › Refresh", "—", "Credential Manager"] in rows
    assert not any("x" in r or "auth-pass" in r or "s3cret" in r for r in rows)  # no password


def test_forget_deletes_the_picked_login_and_forget_all_the_rest(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _keep_some(window)
    dialog = SavedCredentialsDialog(None, window.kept_logins)
    assert len(_rows(dialog)) == 3
    snmp = dialog.table.topLevelItem(2)  # SNMP account (v3)
    assert snmp is not None
    dialog.table.setCurrentItem(snmp)
    dialog.forget_button.click()
    assert refresh.v3_account() is None and len(_rows(dialog)) == 2
    asked: list[str] = []

    def answer(_parent: Any, _title: str, text: str, _action: str) -> bool:
        asked.append(text)
        return True

    monkeypatch.setattr(saved_credentials, "confirm", answer)
    dialog.forget_all_button.click()
    assert asked[0].startswith("Forget all 2 logins?")
    assert _rows(dialog) == [] and credstore.names("") == []
    assert window.hosts._account is None  # pyright: ignore[reportPrivateUsage]
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
    assert row.description.text() == "3 kept: 2 in Credential Manager, 1 until CapyPanel closes."
    printers = dialog.group(PrintersSettings)

    def forget_everything(win: SavedCredentialsDialog) -> int:
        for login in window.kept_logins():
            login.forget()
        return 0

    monkeypatch.setattr(SavedCredentialsDialog, "exec", forget_everything)
    dialog.group(HostsSettings).connections.profiles.manage_button.click()
    assert row.description.text() == "None kept."  # Settings shows it at once
    printers.general.version.setCurrentIndex(printers.general.version.findData(refresh.V3))
    assert "not set" in printers.general.account_row.description.text()


def test_the_settings_line_names_both_places() -> None:
    def login(saved: bool) -> KeptLogin:
        return KeptLogin("A", "Tool", "user", saved, lambda: None)

    assert kept_text([]) == "None kept."
    assert kept_text([login(True)]) == "1 kept: 1 in Credential Manager."
    assert kept_text([login(False)] * 2) == "2 kept: 2 until CapyPanel closes."


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
