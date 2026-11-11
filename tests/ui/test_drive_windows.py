"""Mapped drives: its rows and its window. Every call to another PC is replaced: nothing here
reaches the network."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import access, drives, sessions
from capypanel.core.remote.drives import Drive, Person
from capypanel.core.remote.sessions import Session
from capypanel.ui.hosts_tool.drive_windows import DriveRow, DrivesDialog, drive_rows
from capypanel.ui.hosts_tool.runner import HostTarget

ANA = Session("ana", "CORP", "console", "active", None, session_id=1)
SHARED, HOME = "\\\\FS01\\Shared", "\\\\FS01\\ana"
ANA_SAVED = Person("ana", "CORP", (Drive("H:", HOME), Drive("S:", SHARED)))


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
           ) -> Iterator[CapyWindow]:  # fmt: skip
    monkeypatch.setattr(access, "check_reachable", lambda host: None)
    monkeypatch.setattr(sessions, "read_sessions", lambda *_a: [ANA])
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, office = HostList().add_group("Office")
    hl, _host = hl.add_host("PC-1", office.id, address="192.0.2.1")
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


def _target(win: CapyWindow) -> HostTarget:
    assert win.hosts.document is not None
    host = win.hosts.document.hosts.hosts[0]
    win.hosts.table.select_ids([host.id])
    target = win.hosts.selected_target()
    assert target is not None
    return target


def _settle(win: CapyWindow) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not win.hosts.runner.busy():
            QApplication.processEvents()
            return
    pytest.fail("a host command never finished")


def test_rows_list_each_person_s_saved_drives_by_letter() -> None:
    rui = Person("rui", "CORP", ())
    assert drive_rows([ANA_SAVED, rui]) == [
        DriveRow("ana", "H:", HOME), DriveRow("ana", "S:", SHARED),
        DriveRow("rui", "", "No saved drives"),
    ]  # fmt: skip


def test_mapped_drives_shows_the_saved_drives_and_copies_them(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drives, "saved_drives", lambda *_a: [ANA_SAVED])
    dialog = DrivesDialog(None, window.hosts.runner, _target(window))
    _settle(window)
    assert dialog.table.topLevelItemCount() == 2 and dialog.table.columnCount() == 3
    assert dialog.summary.text().startswith("Drives saved for the person signed in to PC-1")
    dialog.copy_button.click()
    assert QGuiApplication.clipboard().text().splitlines()[1] == f"ana\tH:\t{HOME}"
    dialog.close()
