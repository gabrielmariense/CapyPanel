"""The updater in the app: the look at GitHub (faked here, nothing reaches the network), the
menu bar's button, the update window and the hand-over to the new version's exe."""

import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from capypanel import __version__
from capypanel.core import i18n, settings, updates
from capypanel.core.ssh import launch as ssh_launch
from capypanel.core.updates import Release, UpdateError
from capypanel.ui import updater as updater_ui
from capypanel.ui.main_window import window as window_module
from capypanel.ui.updater import NARROW, NOTES_HEIGHT, WIDE, RestartWindow, UpdateWindow

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


def test_at_every_start_by_default_and_the_other_choices(
    window: CapyWindow, github: dict[str, Any]
) -> None:
    updater = window.updater
    assert updater.how_often() == updates.AT_START  # the default, with no file
    updater._own()["last"] = datetime.now(UTC).isoformat()  # looked a moment ago
    updater._maybe_look(started=True)  # a new start: looks again all the same
    _wait(lambda: not updater.looking)
    asked = github["asked"]
    updater._maybe_look(started=False)  # the hourly tick: not again within a day
    assert github["asked"] == asked
    updater.set_how_often(updates.DAILY)
    updater._maybe_look(started=True)  # once a day: a start soon after doesn't look
    assert github["asked"] == asked
    updater.set_how_often(updates.WEEKLY)
    updater._own()["last"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    updater._maybe_look(started=True)
    assert github["asked"] == asked  # three days: not a week yet
    updater.set_how_often(updates.OFF)
    updater._own()["last"] = "2000-01-01T00:00:00+00:00"
    updater._maybe_look(started=True)
    assert github["asked"] == asked
    assert "updates" not in window.prefs or "check" not in window.prefs["updates"]  # not per person
    dialog = window.settings_dialog()
    choice = dialog.general.updates
    assert choice.currentData() == updates.OFF and choice.isEnabled()
    words = " ".join(label.text() for label in dialog.general.findChildren(QLabel))
    assert "Everyone on this PC" in words  # the mark of the settings shared on this PC
    assert "A change here reaches everyone on this PC: an update replaces" in words
    choice.setCurrentIndex(choice.findData(updates.AT_START))
    assert updater.how_often() == updates.AT_START
    assert not (window.paths.company_tools_dir / updates.CHECK_FILE).exists()  # the default
    dialog.close()


def test_help_asks_and_says_when_it_is_up_to_date(
    window: CapyWindow, github: dict[str, Any]
) -> None:
    github["latest"] = None
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.windowTitle() == "CapyPanel"
    assert dialog.help_button.place() == "download-update-capypanel"  # first in the footer
    assert dialog.heading.text() == "Checking for updates…" and not dialog.busy.isHidden()
    _wait(lambda: not window.updater.looking)
    # Just the message, in the middle of a narrower window: no icon, chip or list.
    assert dialog.heading.text() == "You already have the newest version."
    assert dialog.line.text() == f"CapyPanel {__version__}"
    assert dialog.icon.isHidden() and dialog.chip.isHidden() and dialog.changes.isHidden()
    assert dialog.busy.isHidden() and dialog.heading.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert dialog.install.isHidden() and dialog.skip.isHidden()
    assert dialog.later.text() == "Close" and dialog.later.isDefault()
    QApplication.processEvents()  # fitted to its few lines, no empty space
    assert dialog.width() == NARROW and dialog.height() < NOTES_HEIGHT / 2
    assert dialog._body.contentsMargins().top() == updater_ui.SHORT_BODY[1]  # centred, as drawn
    dialog.close()


def test_a_failed_check_says_why_with_the_releases_link(
    window: CapyWindow, github: dict[str, Any]
) -> None:
    github["latest"] = UpdateError("GitHub didn't answer.")
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    _wait(lambda: not window.updater.looking)
    assert dialog.heading.text() == "Couldn't check for updates."
    assert dialog.line.text() == "GitHub didn't answer."
    links = dialog.links.text()
    assert "Releases on GitHub ↗" in links and updates.RELEASES_URL in links
    assert dialog.later.text() == "Close" and dialog.install.isHidden()
    dialog.close()


def test_from_source_the_window_shows_the_notes_but_installs_nothing(window: CapyWindow) -> None:
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.heading.text() == "Update available"
    assert dialog.chip.text() == f"{__version__} → 99.0.0" and not dialog.icon.isHidden()
    assert dialog.line.text() == "Your settings, lists and saved logins stay as they are."
    assert dialog.changes_text() == ["Everything."] and not dialog.changes.isHidden()
    assert "Notes on GitHub ↗" in dialog.links.text() and NEWER.page_url in dialog.links.text()
    assert dialog.install.isHidden() and "runs from source" in dialog.reason.text()
    assert not dialog.skip.isHidden() and dialog.later.isDefault()
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
    assert helper[0].endswith(str(Path("new") / "CapyPanel" / "CapyPanel.exe"))
    assert not Path(helper[0]).is_relative_to(tmp_path)  # in app data, not beside CapyPanel
    assert helper[1:] == ["--apply-update", str(app_dir.resolve()), str(updates.own_pid()),
                          __version__, "99.0.0"]  # fmt: skip
    dialog.close()


def test_install_waits_for_the_separate_ssh_windows_to_close(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    # They run CapyPanel's own exe, so its files stay in use and the swap would roll back.
    monkeypatch.setattr(updater_ui, "packaged", lambda: True)
    monkeypatch.setattr(updates, "cannot_install", lambda app_dir: "")
    monkeypatch.setattr(updater_ui._Job, "start", lambda self: pytest.fail("it downloaded"))
    monkeypatch.setattr(ssh_launch, "open_windows", lambda: 2)
    said: list[QMessageBox] = []
    monkeypatch.setattr(updater_ui, "run_modal", lambda box: said.append(box) or 0)
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: pytest.fail("it quit"))  # fmt: skip
    dialog.install.click()
    [box] = said
    assert box.text() == (
        "2 SSH connections are still open in separate windows. Close them, then install the update."
    )
    assert box.standardButtons() == QMessageBox.StandardButton.Ok  # no choice to offer
    assert dialog.install.isEnabled() and dialog._job is None
    dialog.close()


def test_a_separate_window_opened_during_the_download_stops_the_hand_over(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(updater_ui, "packaged", lambda: True)
    monkeypatch.setattr(ssh_launch, "open_windows", lambda: 1)
    said: list[str] = []
    monkeypatch.setattr(updater_ui, "run_modal", lambda box: said.append(box.text()) or 0)
    app_dir = tmp_path / "CapyPanel"
    app_dir.mkdir()
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=app_dir, working=lambda: False,
                          quit_for_update=lambda start: pytest.fail("it quit"))  # fmt: skip
    dialog._release = NEWER
    dialog._unpacked(str(updates.places(app_dir).new_app), "")  # downloaded and unpacked
    one = "1 SSH connection is still open in a separate window. Close it, then install the update."
    assert said == [one]
    assert dialog.status.text() == one and dialog.install.isEnabled()  # Install again later
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


def test_the_start_after_an_update_opens_a_window_saying_what_happened(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert updater_ui.after_restart(["CapyPanel.exe"]) is None
    assert updater_ui.after_restart(["CapyPanel.exe", "--updated-from", "0.26.0"]) == (
        "updated", "0.26.0", "")  # fmt: skip
    assert updater_ui.after_restart(["x", "--update-failed", "0.26.1", "it broke"]) == (
        "failed", "0.26.1", "it broke")  # fmt: skip
    shown: list[RestartWindow] = []
    monkeypatch.setattr(window_module, "run_modal", lambda dialog: shown.append(dialog) or 0)
    this = replace(NEWER, version=__version__, notes="## English\n- Brand new.\n## Other\n- No.")
    window.updater.remember_install(this)  # kept through the restart
    assert window.prefs["updates"]["installed"]["version"] == __version__
    window.show_restart_note("updated", "0.26.0", "")
    [done] = shown
    assert done.windowTitle() == "CapyPanel" and done.heading.text() == "Update installed"
    assert done.chip.text() == f"0.26.0 → {__version__}"
    assert done.line.text() == "Your settings, lists and saved logins are as they were."
    assert done.changes_text() == ["Brand new."] and not done.changes.isHidden()
    assert done.close_button.isDefault()
    assert "installed" not in window.prefs["updates"]  # said once
    window.show_restart_note("failed", "0.26.1", "The new version didn't pass its self-test")
    failed = shown[1]
    assert failed.heading.text() == "The update to 0.26.1 wasn't installed."
    assert failed.line.text() == (  # the reason on its own line, never one word left alone
        f"You still have CapyPanel {__version__}.\nThe new version didn't pass its self-test."
    )
    # Its own sentence: a capital first, one closing period even when Windows brought one.
    assert updater_ui.sentence("access is denied.") == "Access is denied"
    assert failed.changes.isHidden() and failed.chip.isHidden()
    assert "Releases on GitHub" in failed.links.text()


def test_a_release_found_on_its_own_opens_its_window_once(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert updater_ui.FIRST_LOOK <= 1000  # not a long wait after the start
    opened: list[UpdateWindow] = []
    monkeypatch.setattr(window_module, "run_modal", lambda dialog: opened.append(dialog) or 0)
    monkeypatch.setattr(window_module, "on_screen", lambda w: True)
    guide = ["home"]
    monkeypatch.setattr(type(window.guides), "running", property(lambda self: guide[0]))
    window.updater.look(asked=False)
    _wait(lambda: not window.updater.looking)
    assert not opened and not window.update_button.isHidden()  # a guide is up: it waits
    guide[0] = ""
    window._offer_update()  # the retry, once the guide is gone
    [dialog] = opened
    assert dialog.heading.text() == "Update available" and not dialog.changes.isHidden()
    window.updater.look(asked=False)  # the next look in this run: the button is enough
    _wait(lambda: not window.updater.looking)
    window._offer_update()
    assert len(opened) == 1


def test_the_update_window_shows_the_notes_in_the_app_s_language(window: CapyWindow) -> None:
    window.updater.offer = replace(
        NEWER, notes="## Português (Brasil)\n- Só a versão.\n\n## English\n- Only the version."
    )
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.changes_text() == ["Only the version."]
    dialog.close()
    i18n.set_language("pt_BR")
    try:
        dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                              quit_for_update=lambda start: False)  # fmt: skip
        assert dialog.changes_text() == ["Só a versão."]
        dialog.close()
    finally:
        i18n.set_language("en")


def test_the_notes_become_one_change_each_and_their_links(window: CapyWindow) -> None:
    notes = (
        "- An update no longer stops.\n  It goes on, wrapped.\n"
        "* **Bold** and `code` and [a page](https://example.com/a).\n\n"
        "A paragraph of its own.\n\n"
        "[Code signing policy](https://example.com/signing/)\n"
    )
    changes, links = updater_ui.changes_and_links(notes)
    assert changes == [
        "An update no longer stops. It goes on, wrapped.",
        "**Bold** and `code` and [a page](https://example.com/a).",
        "A paragraph of its own.",
    ]
    assert links == [("Code signing policy", "https://example.com/signing/")]
    window.updater.offer = replace(NEWER, notes=notes)
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    marks = dialog.findChildren(QLabel, "updateMark")
    assert [mark.text() for mark in marks] == ["✓"] * 3
    words = [label.text() for label in dialog.findChildren(QLabel, "updateChange")]
    assert "<b>Bold</b>" in words[1] and "<code>code</code>" in words[1]
    assert '<a href="https://example.com/a">a page</a>' in words[1]
    shown = dialog.links.text()  # the release page first, then the notes' own link
    assert shown.index("Notes on GitHub ↗") < shown.index("Code signing policy ↗")
    assert "Code signing" not in " ".join(words)  # a link line isn't a change
    QApplication.processEvents()
    assert dialog.width() == WIDE and dialog.height() <= NOTES_HEIGHT
    dialog.close()


def test_a_long_folder_in_the_reason_wraps_instead_of_widening_the_window(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = "C:\\Users\\EXAMPLE\\AppData\\Local\\Programs\\CapyPanel-portable\\0.28.0\\app"
    monkeypatch.setattr(updater_ui, "packaged", lambda: True)
    monkeypatch.setattr(
        updates, "cannot_install", lambda app_dir: f"CapyPanel can't write to {folder}"
    )
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert dialog.reason.text().startswith(
        f"CapyPanel can't write to C:\\{updater_ui.ZERO_WIDTH_SPACE}"
    )
    assert dialog.reason.text().endswith(
        ", so the update can't be installed from here. Open Notes on GitHub, download the zip "
        "and unpack it in place of this copy."
    )
    assert dialog.install.isHidden()
    dialog.show()
    _wait(lambda: dialog.width() == WIDE)
    QApplication.processEvents()
    assert dialog.width() == WIDE and dialog.reason.width() <= WIDE - 48
    dialog.close()


def test_long_notes_scroll_inside_the_tallest_window(window: CapyWindow) -> None:
    many = "\n".join(f"- Change number {n} with a few words to wrap." for n in range(40))
    window.updater.offer = replace(NEWER, notes=many)
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    dialog.show()
    _wait(lambda: dialog.height() == NOTES_HEIGHT)
    assert dialog.changes.verticalScrollBar().maximum() > 0  # the rest is a scroll away
    dialog.close()


def test_the_download_shows_in_the_footer_in_skip_s_place(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(updater_ui, "packaged", lambda: True)
    monkeypatch.setattr(updates, "cannot_install", lambda app_dir: "")
    monkeypatch.setattr(updater_ui._Job, "start", lambda self: None)  # nothing downloads
    window.updater.offer = NEWER
    dialog = UpdateWindow(window, window.updater, app_dir=Path("."), working=lambda: False,
                          quit_for_update=lambda start: False)  # fmt: skip
    assert not dialog.skip.isHidden() and dialog._going.isHidden()
    assert dialog.install.isDefault()
    dialog.install.click()
    assert dialog.skip.isHidden() and not dialog._going.isHidden()
    assert not dialog.install.isEnabled() and not dialog.install.isHidden()
    assert dialog.later.text() == "Cancel" and dialog.later.isDefault()
    dialog._step("Downloading…", 12_400_000, 48_000_000)
    words = dialog.status.text()  # the decimal mark is the PC's own
    assert words.startswith("Downloading… 12") and "of 48" in words and words.endswith(" MB")
    assert dialog.progress.maximum() == 48_000_000 and not dialog.progress.isHidden()
    dialog._job = None
    dialog.close()


def test_about_shows_beta_and_checks_for_updates(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    assert dialog.about.beta.text() == "beta"
    assert dialog.about.updates_button.text() == "Check for &updates"
    dialog.close()


def _job_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, passes: bool) -> list[str]:
    """Download, check and unpack, faked: nothing reaches the network or runs an exe."""
    tested: list[str] = []

    def download(url: str, path: Path, **_kwargs: Any) -> None:
        path.write_text("x", encoding="utf-8")

    def unpack(_archive: Path, into: Path) -> Path:
        (into / "CapyPanel").mkdir()
        return into / "CapyPanel"

    monkeypatch.setattr(updates, "download", download)
    monkeypatch.setattr(updates, "expected_sha256", lambda _text, _name: "same")
    monkeypatch.setattr(updates, "sha256_of", lambda _path: "same")
    monkeypatch.setattr(updates, "unpack", unpack)
    monkeypatch.setattr(updates, "self_test", lambda exe: tested.append(exe.name) or passes)
    return tested


def test_the_new_version_s_self_test_runs_before_capypanel_closes(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tested = _job_world(monkeypatch, tmp_path, passes=True)
    app_dir = tmp_path / "CapyPanel"
    job = updater_ui._Job(NEWER, app_dir)
    steps: list[str] = []
    ended: list[tuple[str, str]] = []
    job.step.connect(lambda words, _done, _total: steps.append(words))
    job.ended.connect(lambda folder, why: ended.append((folder, why)))
    job._run()
    assert tested == ["CapyPanel.exe"] and "Checking the new version…" in steps
    assert ended == [(str(updates.places(app_dir).new_app), "")]
    assert updates.was_tested(updates.places(app_dir), "99.0.0")  # the helper won't run it again
    _job_world(monkeypatch, tmp_path, passes=False)
    ended.clear()
    job._run()
    assert ended == [("", "The new version didn't pass its self-test")]  # CapyPanel stays open


def test_the_helper_s_splash_says_it_is_updating(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from capypanel.ui import update_splash

    assert update_splash.splash_text("0.26.4") == "Updating to 0.26.4…"
    picture = update_splash.picture("Updating to 0.26.4…", 1.5)
    assert picture.devicePixelRatio() == 1.5  # pixel for pixel, like the launcher's
    assert (picture.width(), picture.height()) == (480, 300)
    swapped: list[tuple[Any, ...]] = []
    monkeypatch.setattr(updates, "run_helper", lambda *args: swapped.append(args) or 0)
    monkeypatch.setattr(update_splash, "HAND_OVER", 0)
    closed: list[bool] = []
    code = update_splash.run(tmp_path, 7, "0.26.3", "0.26.4", lambda: closed.append(True))
    assert code == 0 and closed == [True]
    assert swapped == [(tmp_path, 7, "0.26.3", "0.26.4", None)]
