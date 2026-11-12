"""The updater in the app: the look at GitHub (faked here, nothing reaches the network), the
menu bar's button, the update window and the hand-over to the new version's exe."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from capypanel import __version__
from capypanel.core import settings, updates
from capypanel.core.updates import Release, UpdateError
from capypanel.ui import updater as updater_ui
from capypanel.ui.updater import NOTES_HEIGHT, UpdateWindow

NEWER = Release(
    version="99.0.0", notes="## What's new\n- Everything.",
    page_url="https://github.com/gabrielmariense/CapyPanel/releases/tag/v99.0.0",
    zip_url="https://github.com/x/z.zip", sha_url="https://github.com/x/z.zip.sha256",
    zip_name=updates.zip_name("99.0.0"), zip_size=38_000_000,
)  # fmt: skip


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What GitHub answers: a Release, None, or an UpdateError to raise; and how often asked."""
    answer: dict[str, Any] = {"latest": NEWER, "asked": 0}

    def latest(timeout: float = 15) -> Release | None:
        answer["asked"] += 1
        if isinstance(answer["latest"], UpdateError):
            raise answer["latest"]
        return answer["latest"]

    monkeypatch.setattr(updates, "latest", latest)
    return answer


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, github: dict[str, Any]) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    yield win
    win.close()


def _wait(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return
    pytest.fail("never happened")


def test_from_source_nothing_looks_on_its_own(window: CapyWindow, github: dict[str, Any]) -> None:
    assert not updater_ui.packaged()
    assert not window.updater._timer.isActive()  # only CapyPanel.exe looks once a day
    assert github["asked"] == 0 and window.update_button.isHidden()


def test_a_newer_release_puts_a_button_on_the_menu_bar(window: CapyWindow) -> None:
    window.updater.look(asked=False)
    _wait(lambda: not window.updater.looking)
    assert window.updater.offer == NEWER
    assert not window.update_button.isHidden() and window.update_button.text() == "Update 99.0.0"
    assert window.update_button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    window.show()
    QApplication.processEvents()
    words = window.update_button.fontMetrics().horizontalAdvance("Update 99.0.0")
    assert window.update_button.width() > words  # the words fit, beside the icon
    assert window.menuBar().cornerWidget() is window.update_button
    assert window.updater._own()["last"]  # when it last looked, for the once a day
    window.updater.skip("99.0.0")
    assert window.update_button.isHidden() and window.prefs["updates"]["skip"] == "99.0.0"
    window.updater.look(asked=False)  # on its own, a skipped version stays skipped
    _wait(lambda: not window.updater.looking)
    assert window.updater.offer is None
    window.updater.look(asked=True)  # asked from Help, it's offered again
    _wait(lambda: not window.updater.looking)
    assert window.updater.offer == NEWER


def test_nothing_newer_or_github_out_of_reach_shows_no_button(
    window: CapyWindow, github: dict[str, Any]
) -> None:
    github["latest"] = None
    window.updater.look(asked=False)
    _wait(lambda: not window.updater.looking)
    assert window.updater.offer is None and window.update_button.isHidden()
    github["latest"] = UpdateError("Couldn't reach GitHub: offline")
    window.updater.look(asked=False)
    _wait(lambda: not window.updater.looking)
    assert window.updater.offer is None


def test_once_a_day_and_the_off_switch(window: CapyWindow, github: dict[str, Any]) -> None:
    updater = window.updater
    updater._maybe_look()  # never looked: due
    _wait(lambda: not updater.looking)
    asked = github["asked"]
    updater._maybe_look()  # just looked: not again today
    assert github["asked"] == asked
    updater._own()["last"] = "2000-01-01T00:00:00+00:00"
    updater.set_checks(False)  # Settings › Updates: Off
    updater._maybe_look()
    assert github["asked"] == asked and window.prefs["updates"]["check"] is False
    dialog = window.settings_dialog()
    assert dialog.general.updates.currentData() is False
    dialog.general.updates.setCurrentIndex(0)  # Once a day
    assert updater.checks()
    dialog.close()


def test_help_asks_and_says_when_it_is_up_to_date(
    window: CapyWindow, github: dict[str, Any]
) -> None:
    github["latest"] = None
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.heading.text() == "Checking for updates…"
    _wait(lambda: not window.updater.looking)
    assert dialog.heading.text() == "CapyPanel is up to date"
    assert dialog.line.text() == f"{__version__} is the newest release."
    assert dialog.install.isHidden() and dialog.later.text() == "Close"
    QApplication.processEvents()  # fitted to its few lines, no empty space
    assert dialog.height() < NOTES_HEIGHT / 2
    dialog.close()


def test_from_source_the_window_shows_the_notes_but_installs_nothing(window: CapyWindow) -> None:
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.heading.text() == "CapyPanel 99.0.0 is out"
    assert "Everything" in dialog.notes.toPlainText() and not dialog.notes.isHidden()
    assert dialog.install.isHidden() and "runs from source" in dialog.status.text()
    dialog.skip.click()
    assert window.updater.offer is None and window.prefs["updates"]["skip"] == "99.0.0"


def test_install_waits_for_a_refresh_then_hands_over_and_quits(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(updater_ui, "packaged", lambda: True)
    started: list[list[str]] = []
    monkeypatch.setattr(
        updates, "start", lambda exe, *args, splash=True: started.append([str(exe), *args])
    )
    window.updater.offer = NEWER
    working = [True]
    quits: list[bool] = []

    def quit_for_update(start_helper: Callable[[], None]) -> bool:
        start_helper()
        quits.append(True)
        return True

    app_dir = tmp_path / "CapyPanel"
    app_dir.mkdir()
    dialog = UpdateWindow(window, window.updater, app_dir=app_dir, working=lambda: working[0],
                          quit_for_update=quit_for_update)  # fmt: skip
    assert not dialog.install.isHidden() and dialog.install.isDefault()
    dialog._release = NEWER
    dialog._unpacked(str(updates.places(app_dir).new_app), "")  # downloaded, checked, unpacked
    assert dialog.status.text() == "Waiting for CapyPanel to finish what it's doing…" and not quits
    working[0] = False
    dialog._try_restart()
    assert quits == [True]
    [helper] = started
    assert helper[0].endswith(str(Path("CapyPanel.update") / "CapyPanel" / "CapyPanel.exe"))
    assert helper[1:] == ["--apply-update", str(app_dir.resolve()), str(updates.own_pid()),
                          __version__, "99.0.0"]  # fmt: skip
    dialog.close()


def test_a_failed_download_says_why_and_lets_you_try_again(window: CapyWindow) -> None:
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: True)  # fmt: skip
    dialog._unpacked("", "The download doesn't match its SHA-256: it was changed or cut short.")
    assert "SHA-256" in dialog.status.text() and dialog.install.isEnabled()
    dialog._unpacked("", "Cancelled.")
    assert dialog.status.text() == "Cancelled."
    dialog.close()


def test_a_tool_that_keeps_capypanel_open_stops_the_hand_over(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(window.tools["profiles"], "quit_question", lambda parent: False)
    assert not window.quit_for_update(lambda: started.append(True))
    assert not started and not window._quitting  # nothing started, CapyPanel stays


def test_the_start_after_an_update_says_what_happened(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert updater_ui.after_restart(["CapyPanel.exe"]) is None
    assert updater_ui.after_restart(["CapyPanel.exe", "--updated-from", "0.26.0"]) == (
        "updated", "0.26.0", "")  # fmt: skip
    assert updater_ui.after_restart(["x", "--update-failed", "0.26.1", "it broke"]) == (
        "failed", "0.26.1", "it broke")  # fmt: skip
    window.show_restart_note("updated", "0.26.0", "")
    assert window.statusBar().currentMessage() == f"Updated from 0.26.0 to {__version__}."
    shown: list[str] = []
    monkeypatch.setattr(
        "capypanel.ui.main_window.window.QMessageBox.warning",
        lambda parent, title, text: shown.append(text),
    )
    window.show_restart_note("failed", "0.26.1", "The new version didn't pass its self-test")
    assert shown == [
        f"The update to 0.26.1 didn't go in, so this is still {__version__}: "
        "The new version didn't pass its self-test"
    ]


def test_about_shows_beta_and_checks_for_updates(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    assert dialog.about.beta.text() == "beta"
    assert dialog.about.updates_button.text() == "Check for &updates"
    dialog.close()
