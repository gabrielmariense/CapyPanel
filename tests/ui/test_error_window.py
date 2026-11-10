"""The window for an error nothing caught: one window however many errors, the same one counted
instead of shown again, and details big enough to read."""

from collections.abc import Iterator

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from capypanel.ui import error_window

FIRST = 'Traceback (most recent call last):\n  File "settings.py", line 109\nRuntimeError: gone'
OTHER = 'Traceback (most recent call last):\n  File "tool.py", line 7\nValueError: odd'


@pytest.fixture(autouse=True)
def closed(qapp: QApplication) -> Iterator[None]:
    yield
    if error_window._window is not None:
        error_window._window.close()
    assert error_window._window is None


def test_errors_that_follow_each_other_share_one_window() -> None:
    window = error_window.show(FIRST)
    assert window.isVisible() and window.isModal()
    assert window.message.text() == "Something went wrong. The details were saved to the app log."
    assert window.details.toPlainText() == FIRST
    assert error_window.show(FIRST + "\n") is window  # the same again: counted, not repeated
    assert error_window.show(OTHER) is window
    assert window.message.text() == (
        "Something went wrong 3 times. The details were saved to the app log."
    )
    assert window.details.toPlainText() == (f"This error happened 2 times:\n{FIRST}\n\n{OTHER}")


def test_the_details_show_at_once_in_a_box_big_enough_to_read() -> None:
    window = error_window.show(FIRST)
    assert not window.details.isHidden() and window.details.isReadOnly()
    assert window.width() >= 800 and window.height() >= 500
    assert window.details.height() >= 350  # the old box showed about five lines
    assert window.isSizeGripEnabled()


def test_copy_all_takes_every_error() -> None:
    window = error_window.show(FIRST)
    error_window.show(OTHER)
    window.copy_button.click()
    assert QGuiApplication.clipboard().text() == f"{FIRST}\n\n{OTHER}"


def test_a_closed_window_starts_over() -> None:
    first = error_window.show(FIRST)
    first.close_button.click()
    assert error_window._window is None
    again = error_window.show(OTHER)
    assert again is not first and again.details.toPlainText() == OTHER


def test_an_uncaught_error_is_logged_and_shown(caplog: pytest.LogCaptureFixture) -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as e:
        error_window.report(type(e), e, e.__traceback__)
    window = error_window._window
    assert window is not None
    assert window.details.toPlainText().endswith("RuntimeError: boom")
    assert "test_error_window.py" in window.details.toPlainText()
    assert any(r.levelname == "CRITICAL" and r.exc_info for r in caplog.records)
