import logging
import threading
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.core.ssh.ending import ended_line, is_error
from capypanel.ui import help_links, spacing
from capypanel.ui.hosts_tool.result_strip import IconBesideText
from capypanel.ui.icons import tabler_icon
from capypanel.ui.notes import escape
from capypanel.ui.ssh_tool.terminal.view import DEFAULT_PT, TerminalView
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)
HELP_PLACE = "ssh-when-a-connection-ends"


def trust_words() -> str:
    # i18n: ssh.exe asks in English whatever the language: say so in a translation.
    return _("First connection to this server from this PC: ssh.exe asks whether you trust the "
             "server. Type yes, not just y, then press Enter. If it asks for a password, nothing "
             "shows as you type it.")  # fmt: skip


class TrustHint(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultStrip")
        self.setProperty("hint", True)
        self._icon = QLabel()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.close_button = QToolButton()
        self.close_button.setAutoRaise(True)
        self.close_button.clicked.connect(self.hide)
        self._lead = IconBesideText(self._icon, self.label)
        row = QHBoxLayout(self)
        row.setContentsMargins(spacing.CONTROLS, spacing.ICON, spacing.ICON, spacing.ICON)
        row.addWidget(self._lead, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.close_button, 0, Qt.AlignmentFlag.AlignTop)
        themes.switches().switched.connect(self._restyle)
        self.retranslate()
        self._restyle()
        self.hide()

    def retranslate(self) -> None:
        self.label.setText(trust_words())
        self.close_button.setToolTip(_("Close"))

    def _restyle(self) -> None:
        self.ensurePolished()
        palette = self.palette()
        accent = palette.color(QPalette.ColorRole.Accent)
        ground = palette.color(self.backgroundRole())
        shows = themes.contrast_ratio(accent.name(), ground.name()) >= themes.MARK_CONTRAST
        mark = accent if shows else palette.color(QPalette.ColorRole.WindowText)
        self._icon.setPixmap(tabler_icon("info-circle", mark, 16).pixmap(16, 16))
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        self.close_button.setIcon(tabler_icon("x", muted, 14))
        self._lead.fit_icon()


class TrustCheck(QObject):
    answered = Signal(int, bool)

    def __init__(self, number: int, asks: Callable[[], bool]) -> None:
        super().__init__()
        self._number, self._asks = number, asks

    def start(self) -> None:
        threading.Thread(target=self._run, name="ssh-known-hosts", daemon=True).start()

    def _run(self) -> None:
        try:
            asks = self._asks()
        except Exception:
            log.exception("Checking whether ssh.exe knows the server failed")
            asks = False
        self.answered.emit(self._number, asks)


class EndedBar(QFrame):
    reconnect = Signal()
    close_tab = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultStrip")
        self._icon = QLabel()
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setOpenExternalLinks(False)
        self.label.setTextInteractionFlags(help_links.LINK_KEYS)
        self.label.linkActivated.connect(lambda _href: help_links.open_place(HELP_PLACE))
        self.reconnect_button = QPushButton()
        self.reconnect_button.setDefault(True)
        self.close_button = QPushButton()
        self._lead = IconBesideText(self._icon, self.label)
        row = QHBoxLayout(self)
        row.setContentsMargins(spacing.CONTROLS, spacing.ICON, spacing.ICON, spacing.ICON)
        row.addWidget(self._lead, 1, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.reconnect_button)
        row.addWidget(self.close_button)
        self.reconnect_button.clicked.connect(self.reconnect)
        self.close_button.clicked.connect(self.close_tab)
        themes.switches().switched.connect(self._restyle)
        self.error = False
        self.in_window = False
        self._end: tuple[str, int, bool] | None = None
        self.retranslate()
        self.hide()

    def show_end(self, host: str, code: int, *, by_us: bool = False) -> None:
        # Our own close exits with 0xC000013A or 0, so `by_us` tells it, never the code.
        self.error = not by_us and is_error(code)
        self._end = (host, code, by_us)
        self._restyle()
        self.show()

    def retranslate(self) -> None:
        self.reconnect_button.setText(_("&Reconnect"))
        self.close_button.setText(_("Close &window") if self.in_window else _("Close &tab"))
        self._show_words()

    def words(self) -> str:
        if self._end is None:
            return ""
        host, code, by_us = self._end
        return ended_line(host, code, by_us=by_us)

    def _show_words(self) -> None:
        text = escape(self.words())
        if self.error:
            text += "&nbsp;&nbsp;" + help_links.strip_anchor(HELP_PLACE, self)
        self.label.setText(text)
        self.label.setToolTip(help_links.url(HELP_PLACE) if self.error else "")

    def colour(self) -> str:
        return themes.status_color("stopped" if self.error else "offline")

    def icon_name(self) -> str:
        return "circle-x" if self.error else "plug-connected-x"

    def _restyle(self) -> None:
        self._icon.setPixmap(
            tabler_icon(self.icon_name(), QColor(self.colour()), 16).pixmap(16, 16)
        )
        self._lead.fit_icon()
        self.setProperty("failed", self.error)
        self.setProperty("ended", not self.error)
        self.style().unpolish(self)
        self.style().polish(self)
        self._show_words()


class TerminalTab(QWidget):
    changed = Signal()
    close_asked = Signal()

    def __init__(self, *, host: str, point_size: int = DEFAULT_PT) -> None:
        super().__init__()
        self.view = TerminalView(host=host, point_size=point_size)
        self.hint = TrustHint()
        self.bar = EndedBar()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.hint)
        layout.addWidget(self.bar)
        self.asks_to_trust: Callable[[], bool] | None = None
        self._checks = 0
        self._check: TrustCheck | None = None
        self.view.ended.connect(self._ended)
        self.view.started.connect(self._started)
        self.bar.reconnect.connect(self.view.restart)
        self.bar.close_tab.connect(self.close_asked)

    @property
    def host(self) -> str:
        return self.view.host

    @property
    def running(self) -> bool:
        return self.view.running

    @property
    def ended(self) -> bool:
        return self.bar.isVisibleTo(self)

    def start(
        self, argv: Sequence[str], *, env: Mapping[str, str] | None = None, cwd: str | None = None
    ) -> None:
        self.view.start(argv, env=env, cwd=cwd)

    def close_connection(self) -> None:
        self.view.close_connection()

    def set_in_window(self, in_window: bool) -> None:
        self.bar.in_window = in_window
        self.bar.retranslate()

    def retranslate(self) -> None:
        self.hint.retranslate()
        self.bar.retranslate()

    def _started(self) -> None:
        self.bar.hide()
        self.hint.hide()
        self._checks += 1
        if self.asks_to_trust is not None:
            self._check = TrustCheck(self._checks, self.asks_to_trust)
            self._check.answered.connect(self._answered)
            self._check.start()
        self.changed.emit()

    def _answered(self, number: int, asks: bool) -> None:
        if asks and number == self._checks and self.running:
            self.hint.show()

    def _ended(self, code: int) -> None:
        self.hint.hide()
        self.bar.show_end(self.view.host, code, by_us=self.view.closed_by_us)
        self.changed.emit()
