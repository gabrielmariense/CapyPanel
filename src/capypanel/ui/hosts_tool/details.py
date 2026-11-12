"""The host Details panel: the host's name and status, a row of command buttons, a waiting
restart, then Connection, Logged on, PC facts, Tags and Notes."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
from capypanel.core.remote.access import Reason, RemoteError, code_text
from capypanel.core.remote.inventory import PowerShellBlocked
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.hosts_tool import quick
from capypanel.ui.hosts_tool.host_state import Facts, PendingPower
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import GAP, DetailsPanel
from capypanel.ui.notes import Elided, escape
from capypanel.ui.themes import engine as themes

NOBODY_FOR = timedelta(minutes=10)  # how long "nobody signed in" is believed
ICON = 18
PICKER_HEIGHT = 28  # px: a changeable value's button, as tall as a dropdown
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
    # Commands run as: the account, whether this PC overrides its group (its own Accounts row),
    # and the tooltip saying why that one.
    commands_as: tuple[str, bool, str] = ("", False, "")
    profile_user: str = ""  # the login kept for that profile, if one was typed or saved
    quick: tuple[str, ...] = host_commands.QUICK  # this admin's quick commands, in order
    hidden: frozenset[str] = frozenset()  # the parts this admin chose not to see


class HostDetailsPanel(DetailsPanel):
    command_clicked = Signal(str)  # a command button: the command's id
    commands_requested = Signal()  # the Commands button: the Commands window
    session_menu_requested = Signal(object, QPoint)  # a right-click on a person: Session, where
    read_facts = Signal()  # PC facts' Read again
    cancel_pending = Signal()  # the waiting restart's Cancel restart

    def __init__(self) -> None:
        super().__init__()
        # Opened by the arrow beside Profile; the tool fills it each time (aboutToShow).
        self.profile_menu = QMenu(self)
        self.account_menu = QMenu(self)  # the arrow by Commands run as, filled the same way
        # The command buttons' menus: the tool fills them each time they open.
        self.users_menu = QMenu(self)
        self.power_menu = QMenu(self)
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
        self.heading(layout, shown.host.name, shown.status)
        layout.addSpacing(6)
        layout.addWidget(self._command_grid(shown))
        if shown.pending is not None and shown.pending.at > datetime.now(UTC):
            layout.addSpacing(8)
            layout.addWidget(self._pending_strip(shown.pending))

        host, hidden = shown.host, shown.hidden
        # A PC that didn't answer says so once, under its name: the parts below don't repeat it.
        said = shown.status is not None and shown.status[0] is not Status.ONLINE
        if "connection" not in hidden:
            self._connection(layout, shown)
        if "users" not in hidden:
            self.users(layout, shown.users, said=said)
        if "facts" not in hidden:
            self.facts(layout, shown.facts, said=said)
        if "tags" not in hidden:
            self.section(layout, _("Tags"))
            layout.addWidget(self.chips(host.tags) if host.tags else self.muted("—"))
        if "notes" not in hidden:
            self.section(layout, _("Notes"))
            layout.addWidget(self.notes(host.notes, needle) if host.notes else self.muted("—"))
        self.hidden_line(layout, len(hidden))

    def _connection(self, layout: QVBoxLayout, shown: HostDetails) -> None:
        """A label on the left, its value on the same line, every value at the same x. The two
        logins, each named by what uses it, are buttons filling the value column."""
        self.section(layout, _("Connection"))
        host = shown.host
        self.profile_button = self._profile_picker(shown.profile, shown.profile_user)
        self.account_button = self._account_picker(*shown.commands_as)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        rows: tuple[tuple[str, QWidget], ...] = (
            (_("Address"), self.value("address", host.address) if host.address
             else self.muted("—")),
            (_("Group"), self.value("group", shown.group) if shown.group else self.muted("—")),
            (_("Connect with"), self.profile_button),
            (_("Commands run as"), self.account_button),
        )  # fmt: skip
        for row, (label, value) in enumerate(rows):
            name = QLabel(label)  # never wraps: the column is as wide as its widest label
            name.setObjectName("hint")
            grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(grid)

    # ---- the command buttons ----

    def _command_grid(self, details: HostDetails) -> QWidget:
        """Four columns of equal buttons, an icon over its word. The fixed row first: Refresh
        (this PC), Commands (the Commands window), Users ▾ and Power ▾ in amber. Under it the
        admin's quick commands in rows of four, in their order; a row that isn't full keeps its
        buttons on the left, and with none picked only the fixed row shows."""
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP + 4)  # the fixed row stands a little apart
        self.buttons = {}
        text = self.palette().color(QPalette.ColorRole.Text)
        amber = QColor(themes.status_color("attention"))
        reachable = bool(details.host.connect_address)
        fixed, short = quick.fixed_labels(), quick.short_labels()
        width = self._button_width()

        refresh = self.word_button("refresh", text, fixed["refresh"],
                               _("Refresh host: status, logged-on users and PC facts"))  # fmt: skip
        refresh.clicked.connect(lambda: self.command_clicked.emit("all-checks"))
        commands = self.word_button("bolt", text, fixed["commands"],
                                _("Every command for this PC, in the Commands window"))  # fmt: skip
        commands.clicked.connect(self.commands_requested)
        people = _people(details)
        users = self.word_button("user-x", amber, f"{fixed['users']} ▾",
                             _("Log off or disconnect someone"), risky=True)  # fmt: skip
        users.setMenu(self.users_menu)
        users.setEnabled(reachable and bool(people))
        if reachable and not people:
            users.setToolTip(_("No one is signed in, or no one was checked: use Refresh"))
        power = self.word_button("power", amber, f"{fixed['power']} ▾",
                             _("Restart or shut down"), risky=True)  # fmt: skip
        power.setMenu(self.power_menu)
        for button in (refresh, commands, power):
            button.setEnabled(reachable)
        for key, button in (("refresh", refresh), ("commands", commands), ("users", users),
                            ("power", power)):  # fmt: skip
            if button.menu() is not None:
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                button.setProperty("arrow", False)  # the ▾ is in its word
            self.buttons[key] = button
        column.addLayout(self.button_rows([refresh, commands, users, power], width))

        who, nobody = _folder_user(details), _nobody(details)
        picked: list[QToolButton] = []
        for command_id in details.quick:
            command = host_commands.command(command_id)
            name = _(command.name)
            enabled = reachable
            if command.needs_user and nobody:  # the reason has no room on the button
                name = _("{command} (nobody signed in)").format(command=name.rstrip("…"))
                enabled = False
            elif command_id == "user-folder" and who:
                name = _("{command} ({user})").format(command=name, user=who)
            color = amber if command.risky else text
            button = self.word_button(command.icon, color, short[command_id],
                                      name.rstrip("…"), risky=command.risky)  # fmt: skip
            button.setEnabled(enabled)
            button.clicked.connect(lambda _c=False, c=command_id: self.command_clicked.emit(c))
            self.buttons[f"quick:{command_id}"] = button
            picked.append(button)
        if picked:
            column.addLayout(self.button_rows(picked, width))
        return widget

    def _button_width(self) -> int:
        """Every button as wide as the widest word any of them can have in this font and
        language, so the grid never changes width with what's picked."""
        fixed = quick.fixed_labels()
        words = [f"{fixed[k]} ▾" if k in ("users", "power") else fixed[k] for k in fixed]
        return self.grid_width([*words, *quick.short_labels().values()])

    def minimum_width(self) -> int:
        return self.grid_minimum(self._button_width())

    def _pending_strip(self, pending: PendingPower) -> QFrame:
        """A restart waiting: when, when it was asked and who saw the message; Cancel restart."""
        strip = QFrame()
        strip.setObjectName("attentionStrip")
        grid = QGridLayout(strip)
        grid.setContentsMargins(10, 6, 6, 6)
        clock = QLabel()
        amber = QColor(themes.status_color("attention"))
        clock.setPixmap(tabler_icon("clock", amber, 16).pixmap(16, 16))
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

    def _profile_picker(self, profile: str, user: str) -> "ValuePicker":
        """The profile; a key when a login is kept for it, which the tooltip names."""
        tip = _("What Connect opens, and the login it uses. Refresh's logged-on users and the "
                "commands use the account under it.")  # fmt: skip
        if user:
            tip = f"{_('Signs in as {user}').format(user=user)}\n{tip}"
        picker = ValuePicker(profile or "—", ("key",) if user else (), tip)
        picker.clicked.connect(lambda: self._open_menu(self.profile_menu, picker))
        return picker

    def _account_picker(self, account: str, own: bool, tip: str) -> "ValuePicker":
        """The account; a pin only when this PC overrides its group, which the tooltip says."""
        if own:
            tip = f"{_('Only this PC')}\n{tip}"
        picker = ValuePicker(account, ("pin",) if own else (), tip)
        picker.clicked.connect(lambda: self._open_menu(self.account_menu, picker))
        return picker

    def _open_menu(self, menu: QMenu, picker: QWidget) -> None:
        """Under the value, from its left edge, like a dropdown's list."""
        menu.aboutToShow.emit()  # filled first
        menu.popup(picker.mapToGlobal(QPoint(0, picker.height())))

    def heading(
        self,
        layout: QVBoxLayout,
        host_name: str,
        checked: tuple[Status, datetime] | None,
        *,
        unchecked: str = "",
    ) -> None:
        """The status dot and the host's name, then its status and when it was checked."""
        row = QHBoxLayout()
        row.setSpacing(4)
        name = self.value("name", host_name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        status = checked[0] if checked else None
        color = themes.status_color(status if status is not None else "offline")
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
        if checked is None:
            line = unchecked or _("Not checked: use Refresh")
        else:
            found, when = checked
            line = _("{status} · checked {when}").format(
                status=check_texts.status_text(found), when=check_texts.clock_text(when)
            )
        layout.addWidget(self.muted(line))

    def users(
        self,
        layout: QVBoxLayout,
        users: tuple[Sequence[Session] | None, RemoteError | None, datetime] | None,
        *,
        said: bool = False,
    ) -> None:
        """Logged on: each person with their session; a right-click offers what can be done.
        `said`: the panel already says the PC didn't answer, so this part only shows a dash."""
        if users is None:
            self.section(layout, _("Logged on"))
            layout.addWidget(self.muted(_("Not checked")))
            return
        found, error, when = users
        sessions = found or ()
        clock = check_texts.clock_text(when)
        if error is not None or not sessions:
            self.section(layout, _("Logged on · {when}").format(when=clock))
            if error is not None:
                text = (
                    "—" if said and _unreached(error) else check_texts.users_text(sessions, error)
                )
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

    def facts(
        self,
        layout: QVBoxLayout,
        facts: Facts | None,
        *,
        button: bool = True,
        said: bool = False,
    ) -> None:
        """PC facts: read once when the host is opened here, with Read again (`button`). While
        the slow part is still on its way, its rows read "Reading…". When nothing could be
        read for one reason, it's said once, not on every row; and not at all when the panel
        already says the PC didn't answer (`said`)."""
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
            unread = facts.pc.unread if facts.pc is not None else {}
            errors = [error or unread.get(key) for key, _l, _v, error, _p in rows]
            whys = {facts_error_text(e) for e in errors if e is not None}
            if all(e is not None for e in errors) and len(whys) == 1:
                first = next(e for e in errors if e is not None)
                if said and _unreached(first):
                    layout.addWidget(self.muted("—"))
                else:
                    layout.addWidget(self._warning("facts_error", whys.pop()))
                rows = []
            for key, label, value, error, pending in rows:
                error = error or unread.get(key)  # this row alone couldn't be read
                layout.addWidget(self.muted(label))
                if pending:
                    layout.addWidget(self._indented(self.muted(_("Reading…"))))
                elif error is not None:
                    layout.addWidget(self._warning(f"{key}_error", facts_error_text(error)))
                elif value:
                    layout.addWidget(self.value(key, value))
                else:
                    layout.addWidget(self._indented(self.muted("—")))
        if not button:
            return
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

    def _warning(self, key: str, text: str) -> QLabel:
        """Why a row couldn't be read, in amber; a click copies it, as any value, so an error
        can be pasted into a report."""
        label = self.value(key, text)
        label.setStyleSheet(f"QLabel#copyValue {{ color: {themes.status_color('attention')}; }}")
        return label


# ---- how the facts read ----


def _people(details: HostDetails) -> list[Session]:
    return list(details.users[0] or ()) if details.users is not None else []


def _nobody(details: HostDetails) -> bool:
    """Whether a check from the last few minutes found no one signed in."""
    if details.users is None:
        return False
    sessions, error, when = details.users
    return error is None and not sessions and datetime.now(when.tzinfo) - when < NOBODY_FOR


def _folder_user(details: HostDetails) -> str:
    from capypanel.ui.hosts_tool.runner import folder_user

    who = folder_user(_people(details))
    return who.user if who is not None else ""


def restart_text(when: datetime | None) -> str | None:
    if when is None:
        return None
    local = check_texts.local(when)
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


def _unreached(error: BaseException) -> bool:
    return isinstance(error, RemoteError) and error.reason is Reason.UNREACHABLE


def facts_error_text(error: BaseException) -> str:
    if isinstance(error, RemoteError):
        return {
            Reason.UNREACHABLE: _("Not reached: the PC didn't answer"),
            Reason.NOT_ADMIN: _("No access: needs an admin account on this PC"),
            Reason.REJECTED: _("No access: the PC didn't accept the account"),
            Reason.OTHER: _("Couldn't read: Windows error {code}").format(
                code=code_text(error.code)
            ),
        }[error.reason]
    if isinstance(error, TimeoutError):
        return _("Couldn't read: it took too long to answer")
    if isinstance(error, PowerShellBlocked):
        return _("Couldn't read: Windows didn't let PowerShell start on your PC (an antivirus "
                 "may block it)")  # fmt: skip
    return _("Couldn't read: {error}").format(error=error)


class ValuePicker(QPushButton):
    """A value you can change in Details: a flat button filling the value column, the value on
    the left, small marks (key, pin) and one chevron at its right edge. A click opens its menu;
    the tooltip says what the marks mean."""

    def __init__(self, text: str, marks: Sequence[str], tip: str) -> None:
        super().__init__()
        self.setObjectName("valuePicker")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tip)
        self.marks = tuple(marks)
        self.label = Elided(text)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 3, 6, 3)
        row.setSpacing(6)
        row.addWidget(self.label, 1)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        text_color = self.palette().color(QPalette.ColorRole.Text)
        for icon, color in [*((m, muted) for m in self.marks), ("chevron-down", text_color)]:
            mark = QLabel()
            mark.setPixmap(tabler_icon(icon, color, 14).pixmap(14, 14))
            row.addWidget(mark)
        for child in self.findChildren(QLabel):  # the button takes the clicks
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumHeight(PICKER_HEIGHT)

    def value_text(self) -> str:
        return self.label.full

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        layout = self.layout()
        if layout is not None:
            hint = hint.expandedTo(layout.sizeHint())
        return QSize(hint.width(), max(hint.height(), PICKER_HEIGHT))
