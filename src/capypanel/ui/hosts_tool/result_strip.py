from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from capypanel.core.i18n import _
from capypanel.ui import help_links, spacing
from capypanel.ui.hosts_tool.runner import Outcome, reason_place
from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes import engine as themes

WORKED_FOR = 8_000  # ms
ICON = 16


class IconBesideText(QWidget):
    def __init__(self, icon: QLabel, text: QLabel) -> None:
        super().__init__()
        self._icon, self._text = icon, text
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(text, 1)
        self.fit_icon()

    def fit_icon(self) -> None:
        self._icon.setFixedHeight(max(ICON, self._text.fontMetrics().lineSpacing()))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.fit_icon()


class ResultStrip(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultStrip")
        self._icon = QLabel()
        self._text = QLabel()
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setWordWrap(True)
        self._text.setOpenExternalLinks(False)
        self._text.setTextInteractionFlags(help_links.LINK_KEYS)
        self._text.linkActivated.connect(lambda _href: help_links.open_place(self._place))
        self.retry_button = QPushButton()
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self._retry_clicked)
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.hide)
        self._lead = IconBesideText(self._icon, self._text)
        row = QHBoxLayout(self)
        row.setContentsMargins(spacing.CONTROLS, spacing.ICON, spacing.ICON, spacing.ICON)
        row.addWidget(self._lead, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.retry_button)
        row.addWidget(self.close_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._retry: Callable[[], None] | None = None
        self._failed = False
        self._words = ""
        self._place = ""
        self.retranslate()
        self.hide()

    def retranslate(self) -> None:
        self.retry_button.setText(_("Try another account…"))
        self.close_button.setToolTip(_("Close"))
        self._show_words()

    def text(self) -> str:
        return self._words

    def help_place(self) -> str:
        return self._place

    def show_outcome(self, outcome: Outcome) -> None:
        failed = self._failed = outcome.failed
        self._words = outcome.text
        self._place = reason_place(outcome.error) if outcome.error is not None else ""
        self.restyle()
        self._retry = outcome.retry
        self.retry_button.setVisible(outcome.retry is not None)
        self.setProperty("failed", failed)
        self.style().unpolish(self)
        self.style().polish(self)
        self.show()
        if failed:
            self._timer.stop()
        else:
            self._timer.start(WORKED_FOR)

    def restyle(self) -> None:
        failed = self._failed
        color = themes.status_color("stopped" if failed else "online")
        self._icon.setPixmap(
            tabler_icon("circle-x" if failed else "circle-check", QColor(color), ICON).pixmap(
                ICON, ICON
            )
        )
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        self.close_button.setIcon(tabler_icon("x", muted, 14))
        self._lead.fit_icon()
        self._show_words()

    def _show_words(self) -> None:
        text, place = self._words, self._place
        if place:
            text += "&nbsp;&nbsp;" + help_links.strip_anchor(place, self)
        self._text.setText(text)
        self._text.setToolTip(help_links.url(place) if place else "")

    def _retry_clicked(self) -> None:
        retry = self._retry
        self.hide()
        if retry is not None:
            retry()
