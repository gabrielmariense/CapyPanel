from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.tools import definitions
from capypanel.core.tools.connect import Credential
from capypanel.ui import connect as connect_ui
from capypanel.ui.connect import CredentialDialog
from capypanel.ui.main_window.window import MainWindow

Launch = tuple[str, str, int | None, Credential | None]


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Launch]:
    """Records launches instead of starting programs; the viewer counts as installed."""
    calls: list[Launch] = []

    def fake_launch(tool: Any, exe: Path, target: Any, credential: Any = None) -> None:
        calls.append((tool.id, target.address, target.port, credential))

    monkeypatch.setattr(connect_ui, "launch", fake_launch)
    monkeypatch.setattr(connect_ui.detect, "find_executable", lambda tool: Path("viewer.exe"))
    return calls


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, hq = HostList().add_group("Hosts")
    hl, _a = hl.add_host("PC-A", hq.id, address="10.0.0.1")
    hl, _b = hl.add_host("PC-B", hq.id)
    office = tmp_path / "office.json"
    listfile.save(office, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(office)]})
    yield win
    win.close()


def _select(win: MainWindow, *names: str) -> None:
    ids = [h.id for h in win.document.hosts.hosts if h.name in names] if win.document else []
    win.table.select_ids(ids)


def test_connecting_asks_for_the_password_once_per_session(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def answer(dialog: CredentialDialog) -> int:
        asked.append(dialog.windowTitle())
        dialog.user.setText("CORP\\ana")
        dialog.password.setText("s3cret")
        return 1  # Accepted

    monkeypatch.setattr(CredentialDialog, "exec", answer)
    _select(window, "PC-A")
    window.connect_selected()
    _select(window, "PC-B")
    window.connect_selected()
    assert len(asked) == 1  # remembered for the rest of the session
    typed = Credential("CORP\\ana", "s3cret")
    # A host without an address connects by its name.
    assert launched == [("ultravnc", "10.0.0.1", None, typed), ("ultravnc", "PC-B", None, typed)]
    assert window.commands.forget_passwords.isEnabled()
    window.forget_passwords()
    assert not window.connector.credentials


def test_cancelling_the_password_starts_nothing(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(CredentialDialog, "exec", lambda dialog: 0)
    _select(window, "PC-A")
    window.connect_selected()
    assert launched == [] and not window.connector.credentials


def test_many_hosts_at_once_are_confirmed_first(
    window: MainWindow, launched: list[Launch], monkeypatch: pytest.MonkeyPatch
) -> None:
    window.connector.credentials.remember("ultravnc", Credential("", "x"))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    targets = [(f"PC-{n}", connect_ui.Target(f"PC-{n}")) for n in range(6)]
    assert window.connector.connect(targets) == 0 and launched == []
    assert window.connector.connect(targets[:5]) == 5  # up to five: no question


def test_password_prompt_shows_the_user_field_only_when_the_tool_uses_one(
    qapp: QApplication,
) -> None:
    base = {"schema": 1, "id": "t", "name": "T", "kind": "vnc", "credentials": "arguments"}
    no_user = definitions.from_data({**base, "arguments": [["{address}"], ["{password}"]]})
    dialog = CredentialDialog(None, no_user, "PC-A")
    assert dialog.user.parent() is None or not dialog.user.isVisibleTo(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.password.setText("x")
    assert ok.isEnabled()


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
