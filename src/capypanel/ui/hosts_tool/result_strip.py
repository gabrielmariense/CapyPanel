"""The strip above the host table with a command's answer, in the look of Printers' attention
strip: a green edge when it worked, closing by itself after a few seconds; a red edge when it
failed, staying until closed, with the reason and "Try another account…" when another account
might do."""

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton

from capypanel.core.i18n import _
from capypanel.ui.hosts_tool.runner import Outcome
from capypanel.ui.icons import STATUS_COLORS, tabler_icon

WORKED_FOR = 8_000  # ms a green strip stays
ICON = 16


class ResultStrip(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultStrip")
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setWordWrap(True)
        self.retry_button = QPushButton()
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._retry_clicked)
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.hide)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 4, 4)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._text, 1)
        row.addWidget(self.retry_button)
        row.addWidget(self.close_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._retry: Callable[[], None] | None = None
        self.retranslate()
        self.hide()

    def retranslate(self) -> None:
        self.retry_button.setText(_("Try another account…"))
        self.close_button.setToolTip(_("Close"))

    def text(self) -> str:
        return self._text.text()

    def show_outcome(self, outcome: Outcome) -> None:
        failed = outcome.failed
        color = STATUS_COLORS["stopped" if failed else "online"]
        self._icon.setPixmap(
            tabler_icon("circle-x" if failed else "circle-check", QColor(color), ICON).pixmap(
                ICON, ICON
            )
        )
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        self.close_button.setIcon(tabler_icon("x", muted, 14))
        self._text.setText(outcome.text)
        self._retry = outcome.retry
        self.retry_button.setVisible(outcome.retry is not None)
        self.setProperty("failed", failed)
        self.style().unpolish(self)  # the edge's colour follows the property
        self.style().polish(self)
        self.show()
        if failed:
            self._timer.stop()  # stays until closed: there's something to read
        else:
            self._timer.start(WORKED_FOR)

    def _retry_clicked(self) -> None:
        retry = self._retry
        self.hide()
        if retry is not None:
            retry()
