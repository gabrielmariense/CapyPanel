"""The log's line about how long the start took, part by part."""

from typing import cast

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from capypanel.ui import app


def test_the_start_line_names_each_part_and_their_total() -> None:
    assert app._process_age() > 0  # Windows says when this process was made
    stages = app._Stages()
    stages._parts = [("before the app's own code", 1.5)]
    stages.done("Qt and the log")
    stages._parts[-1] = ("Qt and the log", 0.25)
    assert stages.text() == (
        "Started in 1.75 s (before the app's own code 1.50, Qt and the log 0.25)"
    )


class _Window:
    """What the hand-over uses of the main window, recording what it was asked."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def raise_(self) -> None:
        self.calls.append("raise")

    def activateWindow(self) -> None:  # noqa: N802  # Qt's name
        self.calls.append("activate")

    def isVisible(self) -> bool:  # noqa: N802
        return True

    def isMinimized(self) -> bool:  # noqa: N802
        return False


def _hand_over(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, splash: list[bool], active: bool
) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(app, "close_splash", lambda: calls.append("close splash"))
    monkeypatch.setattr(app, "_active", lambda: active)
    hand_over = app._HandOver(cast(QWidget, _Window(calls)), on_screen=lambda: splash.pop(0))
    hand_over._timer.stop()  # ticked by hand below
    for _tick in range(3):
        hand_over.tick()
    return calls


def test_the_window_is_active_before_the_splash_is_told_to_go(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _hand_over(qapp, monkeypatch, [True, False], active=False)
    assert calls[:3] == ["raise", "activate", "close splash"]
    # The splash went on the second tick and took the focus away: asked back once, no more.
    assert calls[3:] == ["raise", "activate"]


def test_a_window_that_kept_the_focus_isn_t_raised_again(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _hand_over(qapp, monkeypatch, [False], active=True)
    assert calls == ["raise", "activate", "close splash"]


def test_without_a_splash_on_screen_none_is_found() -> None:
    assert app._splash_on_screen() is False  # tests never start the exe's launcher
