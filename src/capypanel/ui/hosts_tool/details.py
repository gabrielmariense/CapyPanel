"""The host Details panel: the host's name and status, a row of command buttons, a waiting
restart, then Connection, Logged on, PC facts, Tags and Notes."""

import html
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QLocale, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts import commands as host_commands
from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.hosts_tool.host_state import Facts, PendingPower
from capypanel.ui.icons import STATUS_COLORS, dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel


def escape(text: str) -> str:
    """Text shown as rich text: <, > and & escaped; quotes stay as they are."""
    return html.escape(text, quote=False)


BUTTON = (34, 30)  # px: the command buttons
MENU_BUTTON = 48  # px: Users ▾ and Power ▾, room for their arrow
ICON = 18
GB = 1024**3


@dataclass(frozen=True)
class HostDetails:
    host: Host
    group: str  # its full path
    profile: str  # the connection profile's name
    status: tuple[Status, datetime] | None = None  # None: not checked yet
    # The last logged-on users check: sessions (None when it failed), its error, and when.
    users: tuple[Sequence[Session] | None, RemoteError | None, datetime] | None = None
    facts: Facts | None = None
    pending: PendingPower | None = None  # a restart or shutdown CapyPanel asked for


class HostDetailsPanel(DetailsPanel):
    command_clicked = Signal(str)  # a command button: the command's id
    session_menu_requested = Signal(object, QPoint)  # a right-click on a person: Session, where
    read_facts = Signal()  # PC facts' Read again
    cancel_pending = Signal()  # the waiting restart's Cancel restart

    def __init__(self) -> None:
        super().__init__()
        # Opened by the arrow beside Profile; the tool fills it each time (aboutToShow).
        self.profile_menu = QMenu(self)
        # The command buttons' menus: the tool fills them each time they open.
        self.users_menu = QMenu(self)
        self.power_menu = QMenu(self)
        self.more_menu = QMenu(self)
        self.buttons: dict[str, QToolButton] = {}

    def show_host(
        self, details: HostDetails | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        self.show_item(details, selected, summary, needle)

    def selected_text(self, selected: int) -> str:
        return ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)

    def pick_hint(self) -> str:
        return _("Select a host to see its details.")

    def item_id(self, shown: object) -> str:
        return shown.host.id if isinstance(shown, HostDetails) else ""

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, HostDetails)
        self._heading(layout, shown)
        layout.addSpacing(6)
        layout.addLayout(self._command_row(shown))
        if shown.pending is not None and shown.pending.at > datetime.now(UTC):
            layout.addSpacing(8)
            layout.addWidget(self._pending_strip(shown.pending))

        self.section(layout, _("Connection"))
        host = shown.host
        for key, label, value in (
            ("address", _("Address"), host.address),
            ("group", _("Group"), shown.group),
        ):
            layout.addWidget(self.muted(label))
            layout.addWidget(self.value(key, value) if value else self.muted("—"))
        layout.addWidget(self.muted(_("Profile")))
        layout.addLayout(self._profile_row(shown.profile))

        self._users(layout, shown)
        self._facts(layout, shown.facts)

        self.section(layout, _("Tags"))
        layout.addWidget(self.chips(host.tags) if host.tags else self.muted("—"))

        self.section(layout, _("Notes"))
        layout.addWidget(self.notes(host.notes, needle) if host.notes else self.muted("—"))

    # ---- the command buttons ----

    def _command_row(self, details: HostDetails) -> QHBoxLayout:
        """C$, the user's folder, Computer Management and Send a message as icons, then Users ▾
        and Power ▾ in amber, then … with every command. A tooltip names each."""
        row = QHBoxLayout()
        row.setSpacing(6)
        self.buttons = {}
        text = self.palette().color(QPalette.ColorRole.Text)
        amber = QColor(STATUS_COLORS["attention"])
        reachable = bool(details.host.connect_address)
        icons = {"c-share": "", "user-folder": "folder-user", "computer-management": "settings",
                 "message": "message"}  # fmt: skip
        for command_id in host_commands.QUICK:
            command = host_commands.command(command_id)
            button = self._button(icons[command_id], text, _(command.name).rstrip("…"))
            if command_id == "c-share":
                button.setText("C$")  # the share's name is the clearest icon
                font = QFont(button.font())
                font.setBold(True)
                button.setFont(font)
            if command_id == "user-folder":
                who = _folder_user(details)
                if who:
                    button.setToolTip(_("{user}'s folder").format(user=who))
            button.setEnabled(reachable)
            button.clicked.connect(lambda _c=False, c=command_id: self.command_clicked.emit(c))
            self.buttons[command_id] = button
            row.addWidget(button)
        people = _people(details)
        users = self._button("user-x", amber, _("Log off or disconnect someone"), risky=True)
        users.setMenu(self.users_menu)
        users.setEnabled(reachable and bool(people))
        if reachable and not people:
            users.setToolTip(_("No one is signed in, or no one was checked: use Refresh"))
        power = self._button("power", amber, _("Restart or shut down"), risky=True)
        power.setMenu(self.power_menu)
        power.setEnabled(reachable)
        more = self._button("dots", text, _("Every command"))
        more.setMenu(self.more_menu)
        more.setProperty("arrow", False)  # … says there's more already
        for key, button in (("users", users), ("power", power), ("more", more)):
            if button.menu() is not None:
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.buttons[key] = button
            row.addWidget(button)
        for button in (users, power):
            button.setFixedWidth(MENU_BUTTON)
        row.addStretch(1)
        return row

    def _button(self, icon: str, color: QColor, tip: str, *, risky: bool = False) -> QToolButton:
        button = QToolButton()
        button.setObjectName("commandButton")
        button.setProperty("risky", risky)
        button.setFixedSize(*BUTTON)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon:
            button.setIcon(tabler_icon(icon, color, ICON))
            button.setIconSize(QSize(ICON, ICON))
        return button

    def _pending_strip(self, pending: PendingPower) -> QFrame:
        """A restart waiting: when, when it was asked and who saw the message; Cancel restart."""
        strip = QFrame()
        strip.setObjectName("attentionStrip")
        grid = QGridLayout(strip)
        grid.setContentsMargins(10, 6, 6, 6)
        clock = QLabel()
        clock.setPixmap(tabler_icon("clock", QColor(STATUS_COLORS["attention"]), 16).pixmap(16, 16))
        when = check_texts.clock_text(pending.at)
        heading = _("Restarts at {when}") if pending.restart else _("Shuts down at {when}")
        heading = QLabel(f"<b>{escape(heading.format(when=when))}</b>")
        lines = [_("You asked at {when}.").format(when=check_texts.clock_text(pending.asked))]
        if pending.told:
            lines.append(_("{names} got your message.").format(names=", ".join(pending.told)))
        about = QLabel(" ".join(lines))
        about.setWordWrap(True)
        cancel = QPushButton(_("Cancel restart") if pending.restart else _("Cancel shutdown"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.cancel_pending)
        grid.addWidget(clock, 0, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(heading, 0, 1)
        grid.addWidget(about, 1, 1)
        grid.addWidget(cancel, 2, 1, Qt.AlignmentFlag.AlignRight)
        grid.setColumnStretch(1, 1)
        return strip

    # ---- the sections ----

    def _profile_row(self, profile: str) -> QHBoxLayout:
        """The profile, copied by a click like every value, and an arrow to pick another."""
        row = QHBoxLayout()
        row.setSpacing(2)
        row.addWidget(self.value("profile", profile) if profile else self.muted("—"), 1)
        self.profile_button = QToolButton()
        self.profile_button.setObjectName("profilePicker")
        self.profile_button.setToolTip(_("Change the connection profile"))
        self.profile_button.setCursor(Qt.CursorShape.PointingHandCursor)
        text = self.palette().color(QPalette.ColorRole.Text)
        self.profile_button.setIcon(tabler_icon("chevron-down", text, 14))
        self.profile_button.clicked.connect(self._open_profile_menu)
        row.addWidget(self.profile_button, 0, Qt.AlignmentFlag.AlignTop)
        return row

    def _open_profile_menu(self) -> None:
        """Under the arrow, its right edge on the arrow's: the panel is at the window's right."""
        button, menu = self.profile_button, self.profile_menu
        menu.aboutToShow.emit()  # filled first, so its width is known
        left = button.width() - menu.sizeHint().width()
        menu.popup(button.mapToGlobal(QPoint(left, button.height())))

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
        # A right-click on the person: send them a message, disconnect or log them off.
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda pos, s=session, r=row: self.session_menu_requested.emit(s, r.mapToGlobal(pos))
        )
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 2, 0, 2)
        grid.setVerticalSpacing(1)
        name = self.value("users", check_texts.user_name(session))
        name.setToolTip(
            check_texts.user_name(session, full=True)
            + "\n"
            + _("Click to copy, right-click for what you can do")
        )
        name.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        name.customContextMenuRequested.connect(
            lambda pos, s=session, n=name: self.session_menu_requested.emit(s, n.mapToGlobal(pos))
        )
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

    def _facts(self, layout: QVBoxLayout, facts: Facts | None) -> None:
        """PC facts: read once when the host is opened here, with Read again. While the slow
        part is still on its way, its rows read "Reading…"."""
        if facts is None:
            self.section(layout, _("PC facts"))
            layout.addWidget(self.muted(_("Not read yet")))
        else:
            when = check_texts.clock_text(facts.when)
            heading = (
                _("PC facts · reading…") if facts.reading
                else _("PC facts · {when}").format(when=when)
            )  # fmt: skip
            self.section(layout, heading)
            quick_pending = facts.space is None and facts.quick_error is None
            pc_pending = facts.pc is None and facts.pc_error is None
            rows: list[tuple[str, str, str | None, BaseException | None, bool]] = [
                ("restarted", _("Last restart"), restart_text(facts.restarted),
                 facts.quick_error, quick_pending),
                ("space", _("Free on C:"), space_text(facts), facts.quick_error, quick_pending),
                ("windows", _("Windows"), windows_text(facts), facts.pc_error, pc_pending),
                ("model", _("Model"), model_text(facts), facts.pc_error, pc_pending),
                ("serial", _("Serial"), facts.pc.serial if facts.pc else None, facts.pc_error,
                 pc_pending),
                ("memory", _("Memory"), memory_text(facts), facts.pc_error, pc_pending),
                ("bios", _("BIOS"), facts.pc.bios if facts.pc else None, facts.pc_error,
                 pc_pending),
            ]  # fmt: skip
            for key, label, value, error, pending in rows:
                layout.addWidget(self.muted(label))
                if pending:
                    layout.addWidget(self._indented(self.muted(_("Reading…"))))
                elif error is not None:
                    layout.addWidget(self._indented(self._warning(facts_error_text(error))))
                elif value:
                    layout.addWidget(self.value(key, value))
                else:
                    layout.addWidget(self._indented(self.muted("—")))
        again = QPushButton(_("Read again") if facts is not None else _("Read"))
        again.setAutoDefault(False)
        again.setEnabled(facts is None or not facts.reading)
        again.clicked.connect(self.read_facts)
        line = QHBoxLayout()
        line.addWidget(again)
        line.addStretch(1)
        layout.addSpacing(4)
        layout.addLayout(line)

    @staticmethod
    def _indented(label: QLabel) -> QLabel:
        label.setContentsMargins(7, 2, 0, 2)  # where a copy value's text starts
        return label

    @staticmethod
    def _warning(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("warningText")
        label.setWordWrap(True)
        return label


# ---- how the facts read ----


def _people(details: HostDetails) -> list[Session]:
    return list(details.users[0] or ()) if details.users is not None else []


def _folder_user(details: HostDetails) -> str:
    from capypanel.ui.hosts_tool.runner import folder_user

    who = folder_user(_people(details))
    return who.user if who is not None else ""


def restart_text(when: datetime | None) -> str | None:
    if when is None:
        return None
    local = when.astimezone()
    if local.date() == datetime.now().astimezone().date():
        return _("Today {time}").format(time=check_texts.clock_text(when))
    return check_texts.when_text(when)


def gigabytes(size: int) -> str:
    """ "21.3 GB" under 100 GB, "222 GB" above: as precise as anyone needs."""
    value = size / GB
    number = QLocale(i18n.language()).toString(value, "f", 1 if value < 100 else 0)
    return _("{n} GB").format(n=number)


def space_text(facts: Facts) -> str | None:
    space = facts.space
    if space is None:
        return None
    return _("{free} of {total}").format(free=gigabytes(space.free), total=gigabytes(space.total))


def windows_text(facts: Facts) -> str | None:
    pc = facts.pc
    if pc is None:
        return None
    name = f"{pc.windows} {pc.release}".strip()
    return f"{name} · {pc.build}" if pc.build else name


def model_text(facts: Facts) -> str | None:
    pc = facts.pc
    if pc is None:
        return None
    maker = pc.maker.strip()
    # "Dell Inc." and "OptiPlex 3000" read as "Dell OptiPlex 3000".
    first = maker.split()[0] if maker else ""
    if first and not pc.model.casefold().startswith(first.casefold()):
        return f"{first} {pc.model}".strip()
    return pc.model or maker or None


def memory_text(facts: Facts) -> str | None:
    pc = facts.pc
    if pc is None or not pc.memory:
        return None
    return _("{n} GB").format(n=round(pc.memory / GB))


def facts_error_text(error: BaseException) -> str:
    if isinstance(error, RemoteError):
        return {
            Reason.UNREACHABLE: _("Not reached: the PC didn't answer"),
            Reason.NOT_ADMIN: _("No access: needs an admin account on this PC"),
            Reason.REJECTED: _("No access: the PC didn't accept the account"),
            Reason.OTHER: _("Couldn't read: Windows error {code}").format(code=error.code),
        }[error.reason]
    if isinstance(error, TimeoutError):
        return _("Couldn't read: it took too long to answer")
    return _("Couldn't read: {error}").format(error=error)
