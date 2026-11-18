"""A connection's tab: the terminal and, once the connection ends, a message strip at its foot
that says so, with Reconnect and Close tab. The strip is Hosts' result strip after a command:
red with a cross after an error, grey after a normal end."""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from capypanel.core.i18n import _
from capypanel.core.ssh.ending import ended_line, is_error
from capypanel.ui import spacing
from capypanel.ui.hosts_tool.result_strip import IconBesideText
from capypanel.ui.icons import tabler_icon
from capypanel.ui.ssh_tool.terminal.view import DEFAULT_PT, TerminalView
from capypanel.ui.themes import engine as themes


class EndedBar(QFrame):
    """CapyPanel's message strip (#resultStrip, drawn by the theme), with the words, Reconnect
    (the default, Enter) and Close tab. Its colours come from the theme's roles, never the
    terminal's palette. It stays at the tab's foot, never a window, and its words wrap."""

    reconnect = Signal()
    close_tab = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultStrip")
        self._icon = QLabel()
        self.label = QLabel()
        self.label.setWordWrap(True)  # wraps, never "…"
        self.reconnect_button = QPushButton()
        self.reconnect_button.setDefault(True)
        self.close_button = QPushButton()
        # Hosts' strip's own block: the icon on the middle of the words' first line, so the
        # two strips stay one design.
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
        self._end: tuple[str, int, bool] | None = None  # host, code, closed by CapyPanel
        self.retranslate()
        self.hide()

    def show_end(self, host: str, code: int, *, by_us: bool = False) -> None:
        # The exit code after our own close varies (0xC000013A or 0), so a close CapyPanel
        # asked for is known by `by_us`, never by the code.
        self.error = not by_us and is_error(code)
        self._end = (host, code, by_us)
        self.label.setText(ended_line(host, code, by_us=by_us))
        self._restyle()
        self.show()

    def retranslate(self) -> None:
        self.reconnect_button.setText(_("&Reconnect"))
        self.close_button.setText(_("Close &tab"))
        if self._end is not None:
            host, code, by_us = self._end
            self.label.setText(ended_line(host, code, by_us=by_us))

    def colour(self) -> str:
        """The strip's role colour, which the tab's mark takes too."""
        return themes.status_color("stopped" if self.error else "offline")

    def icon_name(self) -> str:
        return "circle-x" if self.error else "plug-connected-x"

    def _restyle(self) -> None:
        self._icon.setPixmap(
            tabler_icon(self.icon_name(), QColor(self.colour()), 16).pixmap(16, 16)
        )
        self._lead.fit_icon()
        self.setProperty("failed", self.error)
        self.setProperty("ended", not self.error)  # the theme's grey edge
        self.style().unpolish(self)
        self.style().polish(self)


class TerminalTab(QWidget):
    """The terminal and, once its connection ends, the strip at its foot. `changed` comes when
    the connection starts or ends, for the tab's mark; `close_asked` when the strip's Close tab
    is pressed."""

    changed = Signal()
    close_asked = Signal()

    def __init__(self, *, host: str, point_size: int = DEFAULT_PT) -> None:
        super().__init__()
        self.view = TerminalView(host=host, point_size=point_size)
        self.bar = EndedBar()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.bar)
        self.view.ended.connect(self._ended)
        # Whatever starts the connection again takes the strip away: Reconnect, and Enter on
        # the ended tab, which the view handles itself.
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

    def retranslate(self) -> None:
        self.bar.retranslate()

    def _started(self) -> None:
        self.bar.hide()
        self.changed.emit()

    def _ended(self, code: int) -> None:
        self.bar.show_end(self.view.host, code, by_us=self.view.closed_by_us)
        self.changed.emit()
