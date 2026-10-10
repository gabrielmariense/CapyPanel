"""The Details pane: the selected host in sections (Connection, Logged on, Tags, Notes), every
value copied by a click. With nothing or several hosts selected, a summary instead."""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.sessions import Session, SessionsError
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.icons import STATUS_COLORS

LONG_WORD = 24  # longer runs of letters may break anywhere, so they never widen the pane
MARK = "rgba(255, 196, 0, 0.38)"  # the search's mark, as in the host table


@dataclass(frozen=True)
class HostDetails:
    host: Host
    group: str  # its full path
    profile: str  # the connection profile's name
    status: tuple[Status, datetime] | None = None  # None: not checked yet
    # The last logged-on users check: sessions (None when it failed), its error, and when.
    users: tuple[Sequence[Session] | None, SessionsError | None, datetime] | None = None


def breakable(text: str) -> str:
    """Lets long words (an address, a path) wrap at any character: a word too wide for the pane
    would otherwise make it wider."""
    zero_width = "​"
    return " ".join(
        zero_width.join(word) if len(word) > LONG_WORD else word for word in text.split(" ")
    )


class CopyValue(QLabel):
    """A value that highlights on hover and copies itself on a click."""

    copied = Signal(str)

    def __init__(self, text: str, shown: str | None = None) -> None:
        super().__init__(shown if shown is not None else breakable(text))
        self._text = text
        self.setObjectName("copyValue")
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # the stylesheet's :hover
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Click to copy"))

    def copy_text(self) -> str:
        return self._text

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QGuiApplication.clipboard().setText(self._text)
            self.copied.emit(self._text)
        super().mousePressEvent(event)


class DetailsPane(QWidget):
    """Details of the selected host, or a summary when none or several are selected."""

    copied = Signal(str)  # a value was copied: the window says so in its status bar

    def __init__(self) -> None:
        super().__init__()
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._values: dict[str, list[CopyValue]] = {}
        self._shown: tuple[HostDetails, str] | None = None  # what's on show, and the search

        # A card with the lists' background, so the three panes read as a set in every theme.
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setBackgroundRole(QPalette.ColorRole.Base)
        card.setAutoFillBackground(True)
        self._pages = QStackedLayout(card)
        self._pages.addWidget(self._hint)
        self._pages.addWidget(self._scroll)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.show_host(None, 0)

    def retranslate(self) -> None:
        """The hint comes back with the next show_host(); a host on show is drawn again."""
        if self._shown is not None:
            self._build(*self._shown)

    def show_host(
        self, details: HostDetails | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        """summary: what the table shows (online, offline…), above the hint when none is picked.
        needle: the search, marked where it's found in the notes."""
        if details is None:
            self._shown = None
            if selected > 1:
                self._hint.setText(
                    ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)
                )
            else:
                hint = _("Select a host to see its details.")
                self._hint.setText(f"{summary}\n\n{hint}" if summary else hint)
            self._pages.setCurrentIndex(0)
            return
        self._shown = (details, needle)
        self._build(details, needle)
        self._pages.setCurrentIndex(1)

    def shown_value(self, key: str) -> str:
        """The text a section shows, one value per line: for tests and the window."""
        return "\n".join(v.copy_text() for v in self._values.get(key, []))

    # ---- building the page ----

    def _build(self, details: HostDetails, needle: str) -> None:
        self._values = {}
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        self._heading(layout, details)

        self._section(layout, _("Connection"))
        host = details.host
        for key, label, value in (
            ("address", _("Address"), host.address),
            ("group", _("Group"), details.group),
            ("profile", _("Profile"), details.profile),
        ):
            layout.addWidget(self._muted(label))
            layout.addWidget(self._value(key, value) if value else self._muted("—"))

        self._users(layout, details)

        self._section(layout, _("Tags"))
        layout.addWidget(self._chips(host.tags) if host.tags else self._muted("—"))

        self._section(layout, _("Notes"))
        layout.addWidget(self._notes(host.notes, needle) if host.notes else self._muted("—"))
        layout.addStretch(1)
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self._scroll.setWidget(page)

    def _heading(self, layout: QVBoxLayout, details: HostDetails) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)
        dot = QLabel("●")
        status = details.status[0] if details.status else None
        color = STATUS_COLORS.get(str(status), STATUS_COLORS["offline"])
        dot.setStyleSheet(f"color: {color};")
        name = self._value("name", details.host.name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(name, 1)
        layout.addLayout(row)
        if details.status is None:
            line = _("Not checked: use Refresh")
        else:
            found, when = details.status
            line = _("{status} · checked {when}").format(
                status=check_texts.status_text(found), when=check_texts.clock_text(when)
            )
        layout.addWidget(self._muted(line))

    def _users(self, layout: QVBoxLayout, details: HostDetails) -> None:
        if details.users is None:
            self._section(layout, _("Logged on"))
            layout.addWidget(self._muted(_("Not checked")))
            return
        found, error, when = details.users
        sessions = found or ()
        clock = check_texts.clock_text(when)
        if error is not None or not sessions:
            self._section(layout, _("Logged on · {when}").format(when=clock))
            if error is not None:
                text = check_texts.users_text(sessions, error)
                failed = self._muted(text)
                failed.setToolTip(check_texts.users_tip(error, when))
                layout.addWidget(failed)
            else:
                layout.addWidget(self._muted(_("No one logged on")))
            return
        heading = _("Logged on ({n}) · {when}").format(n=len(sessions), when=clock)
        self._section(layout, heading)
        for session in check_texts.by_state(sessions):
            layout.addWidget(self._session(session))

    def _session(self, session: Session) -> QWidget:
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setVerticalSpacing(1)
        name = self._value("users", check_texts.user_name(session))
        name.setToolTip(check_texts.user_name(session, full=True) + "\n" + _("Click to copy"))
        grid.addWidget(name, 0, 0)
        states = {"active": _("Active"), "disconnected": _("Disconnected"), "idle": _("Idle")}
        badge = QLabel(states.get(session.state, session.state))
        badge.setObjectName("stateBadge")
        badge.setProperty("active", session.state == "active")
        grid.addWidget(badge, 0, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        kinds = {"console": _("Console"), "rdp": _("Remote Desktop")}
        parts = [kinds.get(session.kind, ""), session.client]
        if session.logon_time is not None:
            parts.append(_("since {when}").format(when=check_texts.clock_text(session.logon_time)))
        about = self._muted(" · ".join(p for p in parts if p))
        about.setContentsMargins(7, 0, 0, 0)  # under the name's text, inside its copy box
        grid.addWidget(about, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return row

    def _chips(self, tags: Sequence[str]) -> QWidget:
        row = QWidget()
        flow = QHBoxLayout(row)
        flow.setContentsMargins(0, 2, 0, 2)
        flow.setSpacing(6)
        for tag in tags:
            chip = self._value("tags", tag)
            chip.setObjectName("tagValue")
            chip.setWordWrap(False)
            flow.addWidget(chip)
        flow.addStretch(1)
        return row

    def _notes(self, notes: str, needle: str) -> QWidget:
        box = QFrame()
        box.setObjectName("notesBox")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(4, 4, 4, 4)
        value = self._value("notes", notes, marked(notes, needle))
        value.setTextFormat(Qt.TextFormat.RichText)
        inner.addWidget(value)
        return box

    def _value(self, key: str, text: str, shown: str | None = None) -> CopyValue:
        value = CopyValue(text, shown)
        value.copied.connect(self.copied)
        self._values.setdefault(key, []).append(value)
        return value

    @staticmethod
    def _section(layout: QVBoxLayout, title: str) -> None:
        """A thin line across the pane, then the section's heading in the accent colour."""
        rule = QFrame()
        rule.setObjectName("detailsRule")
        layout.addSpacing(10)
        layout.addWidget(rule)
        layout.addSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("detailsSection")
        layout.addWidget(heading)

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(breakable(text))
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label


def marked(text: str, needle: str) -> str:
    """The text as rich text, line breaks kept, with every match of the search marked."""
    folded, needle = text.casefold(), needle.strip().casefold()
    pieces, start = [], 0
    while needle and (found := folded.find(needle, start)) != -1:
        pieces.append(_plain(text[start:found]))
        hit = _plain(text[found : found + len(needle)])
        pieces.append(f'<span style="background: {MARK};">{hit}</span>')
        start = found + len(needle)
    pieces.append(_plain(text[start:]))
    return "".join(pieces)


def _plain(text: str) -> str:
    return html.escape(breakable(text)).replace("\n", "<br>")
