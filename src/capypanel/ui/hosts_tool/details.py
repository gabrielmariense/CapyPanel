"""The host Details panel: Connection, Logged on, Tags and Notes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.sessions import Session, SessionsError
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.icons import STATUS_COLORS, dot_icon
from capypanel.ui.list_workspace.details import DetailsPanel


@dataclass(frozen=True)
class HostDetails:
    host: Host
    group: str  # its full path
    profile: str  # the connection profile's name
    status: tuple[Status, datetime] | None = None  # None: not checked yet
    # The last logged-on users check: sessions (None when it failed), its error, and when.
    users: tuple[Sequence[Session] | None, SessionsError | None, datetime] | None = None


class HostDetailsPanel(DetailsPanel):
    def show_host(
        self, details: HostDetails | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        self.show_item(details, selected, summary, needle)

    def selected_text(self, selected: int) -> str:
        return ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)

    def pick_hint(self) -> str:
        return _("Select a host to see its details.")

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, HostDetails)
        self._heading(layout, shown)

        self.section(layout, _("Connection"))
        host = shown.host
        for key, label, value in (
            ("address", _("Address"), host.address),
            ("group", _("Group"), shown.group),
            ("profile", _("Profile"), shown.profile),
        ):
            layout.addWidget(self.muted(label))
            layout.addWidget(self.value(key, value) if value else self.muted("—"))

        self._users(layout, shown)

        self.section(layout, _("Tags"))
        layout.addWidget(self.chips(host.tags) if host.tags else self.muted("—"))

        self.section(layout, _("Notes"))
        layout.addWidget(self.notes(host.notes, needle) if host.notes else self.muted("—"))

    def _heading(self, layout: QVBoxLayout, details: HostDetails) -> None:
        row = QHBoxLayout()
        row.setSpacing(4)
        name = self.value("name", details.host.name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        status = details.status[0] if details.status else None
        color = STATUS_COLORS.get(str(status), STATUS_COLORS["offline"])
        line = QFontMetrics(font).height()
        size = round(line * 0.5)
        dot = QLabel()
        dot.setPixmap(dot_icon(color, size).pixmap(size, size))
        # As tall as the name's first line (and its copy box's padding): centred on it, even
        # when a long name wraps.
        dot.setFixedHeight(line + 4)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        layout.addWidget(self.muted(line))

    def _users(self, layout: QVBoxLayout, details: HostDetails) -> None:
        if details.users is None:
            self.section(layout, _("Logged on"))
            layout.addWidget(self.muted(_("Not checked")))
            return
        found, error, when = details.users
        sessions = found or ()
        clock = check_texts.clock_text(when)
        if error is not None or not sessions:
            self.section(layout, _("Logged on · {when}").format(when=clock))
            if error is not None:
                text = check_texts.users_text(sessions, error)
                failed = self.muted(text)
                failed.setToolTip(check_texts.users_tip(error, when))
                layout.addWidget(failed)
            else:
                layout.addWidget(self.muted(_("No one logged on")))
            return
        heading = _("Logged on ({n}) · {when}").format(n=len(sessions), when=clock)
        self.section(layout, heading)
        for session in check_texts.by_state(sessions):
            layout.addWidget(self._session(session))

    def _session(self, session: Session) -> QWidget:
        row = QWidget()
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setVerticalSpacing(1)
        name = self.value("users", check_texts.user_name(session))
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
        about = self.muted(" · ".join(p for p in parts if p))
        about.setContentsMargins(7, 0, 0, 0)  # under the name's text, inside its copy box
        grid.addWidget(about, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return row
