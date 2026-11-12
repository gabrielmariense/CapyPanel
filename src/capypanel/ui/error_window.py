"""The window for an error nobody planned for. There is only ever one: an error that happens
while it's open joins it, and the same error again is counted instead of shown again, so a
fault that fires five times in a row is one window to close. The details are the point of the
window, so they're shown at once, in a box big enough to read."""

import logging
import traceback
from types import TracebackType

import shiboken6
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from capypanel.core.i18n import _
from capypanel.ui.dialogs import quiet_default
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)

SIZE = QSize(860, 520)  # a traceback's lines are long: wide enough to read most without scrolling


class ErrorWindow(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_("Unexpected error"))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setSizeGripEnabled(True)
        self._errors: dict[str, int] = {}  # each error's text, and how many times it happened
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.details.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.copy_button = QPushButton(_("Copy all"))
        self.copy_button.clicked.connect(self.copy)
        self.close_button = QPushButton(_("Close"))
        quiet_default(self.close_button)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.message)
        layout.addWidget(self.details, 1)
        layout.addLayout(buttons)
        self.resize(SIZE)

    def add(self, error: str) -> None:
        """One more error, as its whole text. One already shown is counted, not repeated."""
        error = error.strip()
        self._errors[error] = self._errors.get(error, 0) + 1
        times = sum(self._errors.values())
        saved = _("The details were saved to the app log.")
        if times == 1:
            self.message.setText(_("Something went wrong.") + " " + saved)
        else:
            happened = _("Something went wrong {n} times.").format(n=times)
            self.message.setText(happened + " " + saved)
        self.details.setPlainText(self.text())

    def text(self) -> str:
        """Every error once, the first one on top; one that repeated says how many times."""
        parts = []
        for error, times in self._errors.items():
            if times > 1:
                error = _("This error happened {n} times:").format(n=times) + "\n" + error
            parts.append(error)
        return "\n\n".join(parts)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text())


_window: ErrorWindow | None = None


def report(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
    """Python's hook for an error nothing caught. The log first: it's what a bug report needs."""
    log.critical("Unexpected error", exc_info=(exc_type, exc, tb))
    show("".join(traceback.format_exception(exc_type, exc, tb)))


def show(error: str) -> ErrorWindow:
    """Shows `error` in the error window, opening it if it isn't open. It never waits for the
    window to close: the errors that follow at once reach the same window."""
    global _window
    if _window is None or not shiboken6.isValid(_window):
        window = ErrorWindow()
        opened = themes.generation()
        window.finished.connect(lambda _result: _closed(window, opened))
        _window = window
    _window.add(error)
    _window.show()
    _window.raise_()
    _window.activateWindow()
    return _window


def _closed(window: ErrorWindow, opened: int) -> None:
    global _window
    if _window is window:
        _window = None
    if themes.generation() == opened:  # open during a theme switch: deleting it can crash Qt
        window.deleteLater()
