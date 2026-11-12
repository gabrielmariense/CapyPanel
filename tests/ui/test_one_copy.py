"""One running copy per person: the lock beside the settings, and a second start asking the
first to show its window. Both copies live in this one process here; nothing leaves the PC."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from capypanel.ui import one_copy
from capypanel.ui.one_copy import LOCK_NAME, OneCopy, already_running_text, pipe_name


def test_a_second_start_brings_the_running_copy_forward(qapp: QApplication, tmp_path: Path) -> None:
    first, second = OneCopy(tmp_path), OneCopy(tmp_path)
    asked: list[bool] = []
    first.show_requested.connect(lambda: asked.append(True))
    assert first.claim()  # the only copy
    assert (tmp_path / LOCK_NAME).exists()
    assert not second.claim()  # the same settings folder is taken
    assert second.ask_running() and asked == [True]  # the first one showed its window
    assert second.ask_running() and asked == [True, True]  # every later start too
    first.release()
    assert second.claim()  # once the first has quit, the next start is the only copy
    second.release()


def test_a_copy_in_another_windows_session_can_t_be_shown_here(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = OneCopy(tmp_path), OneCopy(tmp_path)
    asked: list[bool] = []
    first.show_requested.connect(lambda: asked.append(True))
    assert first.claim() and not second.claim()
    sessions = iter([7, 1])  # the start asks from session 7; the running copy is in session 1
    monkeypatch.setattr(one_copy, "_session", lambda: next(sessions))
    assert not second.ask_running() and asked == []  # so the start says it, in a message
    text = already_running_text("ana@EXAMPLE")
    assert "ana@EXAMPLE" in text and "another Windows session" in text
    first.release()


def test_nobody_answering_is_not_a_window_shown(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(one_copy, "WAIT", 150)
    assert not OneCopy(tmp_path).ask_running()  # no copy is listening


def test_a_lock_that_can_t_be_told_apart_never_stops_the_start(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = OneCopy(tmp_path)
    assert held.claim()
    # The settings folder on a share, open on another PC: that copy can't be shown here, and
    # this PC's copy still starts.
    monkeypatch.setattr(one_copy, "_this_pc", lambda: "OTHER-PC")
    assert OneCopy(tmp_path).claim()
    held.release()
    # A folder that can't be written (it isn't there): the same.
    assert OneCopy(tmp_path / "missing").claim()


def test_each_settings_folder_has_its_own_pipe(tmp_path: Path) -> None:
    here, there = tmp_path / "a" / LOCK_NAME, tmp_path / "b" / LOCK_NAME
    assert pipe_name(here) != pipe_name(there)
    assert pipe_name(here) == pipe_name(Path(str(here).upper()))  # Windows paths: any case
    assert pipe_name(here).startswith("CapyPanel-") and "\\" not in pipe_name(here)
