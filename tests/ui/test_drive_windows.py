"""Mapped drives, Map a drive… and Clear caches…: their rows, windows and answers. Every call to
another PC is replaced: nothing here reaches the network or runs a script."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import access, drives, sessions
from capypanel.core.remote.access import Account
from capypanel.core.remote.drives import App, Checked, Drive, Person
from capypanel.core.remote.run import Engine, RunAs, RunResult, Script
from capypanel.core.remote.sessions import Session
from capypanel.ui.hosts_tool import command_windows, drive_windows, runner
from capypanel.ui.hosts_tool.drive_windows import (
    ClearCachesDialog,
    DriveRow,
    DrivesDialog,
    MapDriveDialog,
    drive_rows,
)
from capypanel.ui.hosts_tool.runner import HostTarget

ANA = Session("ana", "CORP", "console", "active", None, session_id=1)
SHARED, HOME = "\\\\FS01\\Shared", "\\\\FS01\\ana"


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


class FakeRuns:
    """Stands in for the run layer: records each run and answers with `output`."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, Script, RunAs, str]] = []
        self.output = ""

    def run(
        self,
        host: str,
        script: Script,
        account: Account | None = None,
        timeout: float = 0,
        run_as: RunAs = RunAs.ACCOUNT,
        user: str = "",
    ) -> RunResult:
        self.runs.append((host, script, run_as, user))
        return RunResult(Engine.WMI, 0, self.output, "", 1.0)


@pytest.fixture
def runs(window: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> FakeRuns:
    fake = FakeRuns()
    monkeypatch.setattr(window.hosts.runner, "scripts", fake)
    return fake


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


def _answer(monkeypatch: pytest.MonkeyPatch, answer: Callable[[QDialog], int]) -> list[QDialog]:
    opened: list[QDialog] = []

    def run(dialog: QDialog) -> int:
        opened.append(dialog)
        return answer(dialog)

    for module in (runner, command_windows):
        monkeypatch.setattr(module, "run_modal", run)
    return opened


ANA_SAVED = Person("ana", "CORP", (Drive("H:", HOME), Drive("S:", SHARED)))


def test_rows_say_nothing_about_state_until_the_session_is_checked() -> None:
    rui = Person("rui", "CORP", ())
    assert drive_rows([ANA_SAVED, rui], None) == [
        DriveRow("ana", "H:", HOME), DriveRow("ana", "S:", SHARED),
        DriveRow("rui", "", "No saved drives"),
    ]  # fmt: skip
    checked = Checked(
        {"corp\\ana": (Drive("S:", SHARED, "Unavailable"), Drive("T:", "\\\\FS01\\Tmp", "OK"))},
        {"corp\\rui": OSError("no")},
    )
    assert drive_rows([ANA_SAVED, rui], checked) == [
        DriveRow("ana", "H:", HOME, "Not mapped now", True),
        DriveRow("ana", "S:", SHARED, "Not connected", True),
        DriveRow("ana", "T:", "\\\\FS01\\Tmp", "Connected, this session only"),
        DriveRow("rui", "", "No saved drives", "Couldn't check", True),
    ]


def test_mapped_drives_shows_the_saved_drives_then_the_session_s_state(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drives, "saved_drives", lambda *_a: [ANA_SAVED])
    dialog = DrivesDialog(None, window.hosts.runner, _target(window), lambda then: None)
    _settle(window)
    assert dialog.table.topLevelItemCount() == 2 and dialog.table.isColumnHidden(3)
    assert dialog.summary.text().startswith("Drives saved for the person signed in to PC-1")
    runs.output = f"CAPYPANEL-DRIVE\tH:\t{HOME}\tOK\nCAPYPANEL-DRIVE\tS:\t{SHARED}\tUnavailable\n"
    dialog.check_sessions()
    _settle(window)
    assert [(r[2], r[3]) for r in runs.runs] == [(RunAs.USER, "CORP\\ana")]
    assert not dialog.table.isColumnHidden(3)
    states = [dialog.table.topLevelItem(i).text(3) for i in range(2)]  # type: ignore[union-attr]
    assert states == ["Connected", "Not connected"]


def test_map_a_drive_runs_as_the_person_signed_in(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fill(dialog: QDialog) -> int:
        assert isinstance(dialog, MapDriveDialog)
        assert not dialog.map_button.isEnabled()
        dialog.path.setText("C:\\Users")  # not a share
        assert not dialog.map_button.isEnabled()
        dialog.path.setText(SHARED + "\\")
        assert dialog.map_button.isEnabled()
        return QDialog.DialogCode.Accepted

    _answer(monkeypatch, fill)
    window.hosts.runner.run("map-drive", _target(window), window.hosts.show_outcome)
    _settle(window)
    ((host, script, run_as, user),) = runs.runs
    assert (host, run_as, user, script.arguments) == (
        "192.0.2.1", RunAs.USER, "CORP\\ana", ("S:", SHARED))  # fmt: skip
    assert "Mapped S: to \\\\FS01\\Shared for <b>ana</b> on PC-1." in (
        window.hosts.result_strip.text())  # fmt: skip


def test_clear_caches_names_what_it_cleared_and_what_was_open(
    window: CapyWindow, runs: FakeRuns, monkeypatch: pytest.MonkeyPatch
) -> None:
    def untick_firefox(dialog: QDialog) -> int:
        assert isinstance(dialog, ClearCachesDialog)
        dialog.ticks[App.FIREFOX].setChecked(False)
        return QDialog.DialogCode.Accepted

    _answer(monkeypatch, untick_firefox)
    runs.output = ("CAPYPANEL-CACHE teams open 0 0\nCAPYPANEL-CACHE edge cleared 5242880 0\n"
                   "CAPYPANEL-CACHE chrome none 0 0\n")  # fmt: skip
    window.hosts.runner.run("clear-caches", _target(window), window.hosts.show_outcome)
    _settle(window)
    ((_host, script, run_as, _user),) = runs.runs
    assert run_as is RunAs.ACCOUNT and script.arguments == ("ana", "CORP", "teams,edge,chrome")
    text = window.hosts.result_strip.text()
    assert "Cleared 5 MB of caches for <b>ana</b> on PC-1: Edge." in text
    assert "Teams was open, so its cache stayed." in text


def test_clear_caches_needs_one_app_ticked(qapp: QApplication) -> None:
    dialog = ClearCachesDialog(None, "PC-1", "ana")
    assert dialog.apps() == tuple(App)
    for tick in dialog.ticks.values():
        tick.setChecked(False)
    assert not dialog.action.isEnabled()


def test_cleared_text_when_nothing_was_there(qapp: QApplication) -> None:
    found = [drives.Cleared(App.CHROME, drives.CacheState.NONE)]
    assert drive_windows.cleared_text("ana", "PC-1", found) == (
        "Nothing to clear for <b>ana</b> on PC-1: those apps keep no cache there.")  # fmt: skip
