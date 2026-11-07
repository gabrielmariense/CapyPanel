"""The Commands window: every command for one PC, from Commands ▾ › All commands… (the selected
host) or Manual connection (an address typed on the spot). The host or address, its profile and
Connect on top; the groups on the left, a click jumping to one; the commands in the middle, one
line each, the picked one grown to show its description and Run (Enter runs it, the arrow keys
move, typing searches); on the right, what the picked command found, in the Details panel's
parts and with no buttons. Commands that need typing open their small window over this one."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QGuiApplication,
    QKeyEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts import commands as host_commands
from capypanel.core.hosts.bulk import write_csv
from capypanel.core.hosts.commands import GROUP_NAMES, HostCommand, Need
from capypanel.core.hosts.commands import Group as CommandGroup
from capypanel.core.hosts.model import MAX_ADDRESS
from capypanel.core.i18n import _
from capypanel.core.remote import host_printers, services
from capypanel.core.remote.access import Account, RemoteError
from capypanel.core.remote.own_scripts import OwnScript, State
from capypanel.core.remote.run import RunAs
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.core.tools.connect import Target
from capypanel.ui import checks as check_texts
from capypanel.ui.connect import Request
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool import command_windows as windows
from capypanel.ui.hosts_tool.details import HostDetailsPanel
from capypanel.ui.hosts_tool.host_state import Facts
from capypanel.ui.hosts_tool.runner import (
    RETRY_REASONS,
    HostTarget,
    Outcome,
    failed_text,
    folder_user,
)
from capypanel.ui.hosts_tool.script_review import ReviewDialog, state_text
from capypanel.ui.icons import STATUS_COLORS, dot_icon, tabler_icon
from capypanel.ui.notes import hint as hint_label
from capypanel.ui.settings.pages import PathLabel, open_folder

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.tool import HostsTool

SIZE = (1000, 620)  # fixed: it never grows as commands are added
GROUPS_WIDTH = 150  # px, at least
GROUP_ROOM = 40  # px past a group's name: the rows' padding and the list's frame
ROW_SPACING = 2  # px between the commands; a gap widget adds one more
RESULTS_WIDTH = 400  # px: the rest goes to the commands, whose names are longer in pt
ROW = 28  # px: a command's line
APART = 8  # px: the gap above a command set apart, where menus draw a line
ICON = 16
RECENT_ADDRESSES = 10
LISTS = ("printers", "programs")  # their answer is a table on the right, not a window
SCRIPT_GROUPS = (CommandGroup.SCRIPTS, CommandGroup.OWN)  # the Scripts tab
TABLE_ROW = 30  # px, about a grid row: a printers table shows every printer
MOST_TABLE = 330  # px: a longer list (programs) scrolls inside its table


def split_address(typed: str) -> Target:
    """ "PC-01" or "192.0.2.7:5901": a port after one colon is the connection's port."""
    typed = typed.strip()
    name, colon, port = typed.rpartition(":")
    if colon and name and ":" not in name and port.isdigit() and 0 < int(port) < 65536:
        return Target(name, int(port))
    return Target(typed)


@dataclass(frozen=True)
class Shown:
    """What the results side shows: the PC, its status, and the picked command's answer."""

    target: HostTarget
    command: HostCommand
    status: tuple[Status, datetime] | None
    users: tuple[Sequence[Session] | None, RemoteError | None, datetime] | None
    facts: Facts | None
    outcome: Outcome | None
    listed: "Listed | None" = None


@dataclass(frozen=True)
class Listed:
    """Printers or Installed programs as read for the right side: rows, or why not."""

    reading: bool = True
    when: datetime | None = None
    rows: Sequence[Any] = field(default_factory=tuple)
    spooler: str = ""  # the Print Spooler's state, for printers: "running", "stopped"…


class Results(HostDetailsPanel):
    """The right side: the Details panel's heading and parts, for the picked command only."""

    list_menu_requested = Signal(str, int, QPoint)  # command id, row (-1: none), where

    def item_id(self, shown: object) -> str:
        return shown.target.key if isinstance(shown, Shown) else ""

    def pick_hint(self) -> str:
        return _("Type a host name or address to run its commands.")

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, Shown)
        self.heading(layout, shown.target.name, shown.status,
                     unchecked=_("Not checked yet: run Status"))  # fmt: skip
        command = shown.command
        if command.id == "status":
            self.section(layout, _("Status"))
            text = (_("Run checks whether it answers.") if shown.status is None
                    else check_texts.status_tip(*shown.status))  # fmt: skip
            layout.addWidget(self.muted(text))
        elif command.id == "users":
            self.users(layout, shown.users)
        elif command.id == "facts":
            self.facts(layout, shown.facts, button=False)
        elif command.id == "all-checks":
            self.users(layout, shown.users)
            self.facts(layout, shown.facts, button=False)
        elif command.id in LISTS:
            self._listed(layout, shown)
        else:
            self.section(layout, _(command.name).rstrip("…"))
            if shown.outcome is None:
                layout.addWidget(self.muted(_(command.description)))
            self._outcome(layout, shown.outcome)

    def _listed(self, layout: QVBoxLayout, shown: Shown) -> None:
        """A read-only grid table under its heading, with a line under it; what can be done
        with a row is on its right-click."""
        listed, printers = shown.listed, shown.command.id == "printers"
        title = _("Printers") if printers else _("Installed programs")
        if listed is None or listed.reading or listed.when is None:
            self.section(layout, _("{title} · reading…").format(title=title) if listed
                         else title)  # fmt: skip
            if listed is None:
                layout.addWidget(self.muted(_(shown.command.description)))
            self._outcome(layout, shown.outcome)
            return
        when = check_texts.clock_text(listed.when)
        if printers:
            self.section(layout, _("{title} · {when}").format(title=title, when=when))
        else:
            self.section(layout, _("{title} · {n} · {when}").format(
                title=title, n=len(listed.rows), when=when))  # fmt: skip
        table = QTreeWidget()
        table.setObjectName("grid")
        table.setRootIsDecorated(False)
        table.setUniformRowHeights(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if printers:
            table.setHeaderLabels([_("Printer"), _("Status"), _("Jobs")])
            for printer in listed.rows:
                row = QTreeWidgetItem([printer.name, windows.printer_status(printer),
                                       str(printer.jobs)])  # fmt: skip
                row.setIcon(1, dot_icon(STATUS_COLORS[windows.printer_dot(printer)]))
                table.addTopLevelItem(row)
        else:
            table.setHeaderLabels([_("Name"), _("Version")])
            for program in listed.rows:
                table.addTopLevelItem(QTreeWidgetItem([program.name, program.version]))
        header = table.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        for column in range(1, table.columnCount()):
            header.setSectionResizeMode(column, header.ResizeMode.ResizeToContents)
        # Every row shows, up to MOST_TABLE; a longer list scrolls inside the table.
        row_height = table.sizeHintForRow(0) if listed.rows else TABLE_ROW
        rows = max(len(listed.rows), 1) * max(row_height, 1)
        frame = 2 * table.frameWidth() + 4
        table.setFixedHeight(min(MOST_TABLE, header.sizeHint().height() + rows + frame))
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        command_id = shown.command.id

        def menu(pos: QPoint) -> None:
            item = table.itemAt(pos)
            index = table.indexOfTopLevelItem(item) if item is not None else -1
            if item is not None:
                table.setCurrentItem(item)
            self.list_menu_requested.emit(command_id, index, table.viewport().mapToGlobal(pos))

        table.customContextMenuRequested.connect(menu)
        layout.addWidget(table)
        if printers:
            states = {"running": _("running"), "stopped": _("stopped"),
                      "starting": _("starting"), "stopping": _("stopping")}  # fmt: skip
            spooler = states.get(listed.spooler, listed.spooler)
            line = (_("Print Spooler: {state}. Right-click a printer to clear its queue.")
                    .format(state=spooler) if spooler
                    else _("Right-click a printer to clear its queue."))  # fmt: skip
        else:
            line = _("Right-click to copy a row, copy or export the list, or open it in its own "
                     "window with a search.")  # fmt: skip
        layout.addWidget(self.muted(line))
        self._outcome(layout, shown.outcome)

    def _outcome(self, layout: QVBoxLayout, outcome: Outcome | None) -> None:
        """The last answer, and Try another account… when the account was refused."""
        if outcome is None:
            return
        answer = QLabel(outcome.text)
        answer.setTextFormat(Qt.TextFormat.RichText)
        answer.setWordWrap(True)
        if outcome.failed:
            answer.setObjectName("warningText")
        layout.addWidget(answer)
        if outcome.output:
            layout.addWidget(windows.output_box(outcome.output))
        if outcome.retry is not None:
            link = QLabel(f'<a href="retry">{_("Try another account…")}</a>')
            link.setTextFormat(Qt.TextFormat.RichText)
            link.linkActivated.connect(lambda _href, r=outcome.retry: r())
            layout.addWidget(link)


class CommandRow(QFrame):
    """One command: its icon and name on one line; picked, it grows to show its description
    and Run. Risky ones are amber, with an amber left edge."""

    def __init__(
        self, window: "CommandsWindow", command: HostCommand, script: OwnScript | None = None
    ) -> None:
        super().__init__()
        self.command = command
        self.script = script  # one of your own scripts
        self.setObjectName("commandRow")
        self.setProperty("risky", command.risky)
        self.setProperty("picked", False)
        self._window = window
        self.gap: QWidget | None = None  # above a command set apart
        text = self.palette().color(QPalette.ColorRole.Text)
        color = QColor(STATUS_COLORS["attention"]) if command.risky else text
        icon = QLabel()
        icon.setPixmap(tabler_icon(command.icon, color, ICON).pixmap(ICON, ICON))
        self.name = QLabel()
        self.name.setObjectName("commandName")
        self.name.setWordWrap(True)  # a long name wraps rather than widen the list
        self.name.setProperty("risky", command.risky)
        self.run = QPushButton(_("&Run"))
        self.run.setObjectName("risky" if command.risky else "")
        self.run.clicked.connect(lambda: window.run(command))
        self.about = QLabel(_(command.description))
        self.about.setObjectName("hint")
        self.about.setWordWrap(True)
        grid = QGridLayout(self)
        grid.setContentsMargins(8, 3, 6, 3)
        grid.setHorizontalSpacing(10)
        grid.addWidget(icon, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(self.run, 0, 2)
        grid.addWidget(self.about, 1, 1, 1, 2)
        grid.setColumnStretch(1, 1)
        self.extra: QWidget | None = None  # your own script's Run as and Review…
        self.run_as: QComboBox | None = None
        name = _(command.name)
        if script is not None:
            name = command.name  # a file's name: never translated
            if not script.ready:
                name = f"{name} · {state_text(script)}"
                self.run.setText(_("Re&view…"))
                self.run.setObjectName("")
            else:
                self._add_run_as(window, script, grid)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.set_name(name)
        self.set_picked(False)

    def _add_run_as(self, window: "CommandsWindow", script: OwnScript, grid: QGridLayout) -> None:
        """Who it runs as, for this run: as approved, and fixed when it was locked."""
        approval = script.approval
        assert approval is not None
        self.run_as = QComboBox()
        # Narrower than its longest choice, so the row fits the column; the list shows it whole.
        self.run_as.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.run_as.setMinimumContentsLength(8)
        for choice in RunAs:
            self.run_as.addItem(windows.run_as_text(choice), choice)
        self.run_as.setCurrentIndex(max(self.run_as.findData(approval.run_as), 0))
        if approval.locked:
            self.run_as.setEnabled(False)
            self.run_as.setToolTip(_("Locked when it was approved"))
        label = QLabel(_("Run as:"))
        label.setObjectName("hint")
        review = QPushButton(_("Re&view…"))
        review.setAutoDefault(False)
        review.clicked.connect(lambda: window.review(script))
        self.extra = QWidget()
        line = QHBoxLayout(self.extra)
        line.setContentsMargins(0, 2, 0, 2)
        line.addWidget(label)
        line.addWidget(self.run_as, 1)
        line.addWidget(review)
        grid.addWidget(self.extra, 2, 1, 1, 2)

    def run_as_choice(self) -> RunAs:
        return RunAs(self.run_as.currentData()) if self.run_as is not None else RunAs.ACCOUNT

    def set_name(self, text: str) -> None:
        self.name.setText(text)

    def set_picked(self, picked: bool) -> None:
        self.setProperty("picked", picked)
        font = self.name.font()
        font.setBold(picked)
        self.name.setFont(font)
        self.run.setVisible(picked)
        self.run.setDefault(picked)  # Enter runs the picked one
        self.about.setVisible(picked)
        if self.extra is not None:
            self.extra.setVisible(picked)
        self.setMinimumHeight(ROW)
        self.setMaximumHeight(16_777_215 if picked else ROW)  # picked: as tall as it needs
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: object) -> None:
        self._window.pick(self)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if self.script is not None:
            self._window.pick(self)
            self._window.own_menu(self.script, event.globalPos())

    def mouseDoubleClickEvent(self, event: object) -> None:
        self._window.pick(self)  # a double-click doesn't run: risky ones mustn't run by accident


class CommandsWindow(QDialog):
    def __init__(
        self, tool: "HostsTool", target: HostTarget | None, profile: str, *, scripts: bool = False
    ) -> None:
        super().__init__(tool)
        self._tool = tool
        self._typed = target is None  # Manual connection: the address is typed here
        self._target = target
        self._outcomes: dict[tuple[str, str], Outcome] = {}  # (target key, command id)
        self._lists: dict[tuple[str, str], Listed] = {}  # printers and programs, as read
        self.setFixedSize(*SIZE)

        # ---- the top line ----
        self.address = QComboBox()
        self.address.setEditable(True)
        self.address.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.address.addItems(tool.recent_addresses())
        self.address.setCurrentIndex(-1)
        line = self.address.lineEdit()
        assert line is not None
        line.setMaxLength(MAX_ADDRESS)
        line.setPlaceholderText(_("Hostname or IP address"))
        address_label = QLabel(_("&Address:"))
        address_label.setBuddy(self.address)
        self.host_label = QLabel()
        self.profile = QComboBox()
        for profile_id, text in tool.connector.choices():
            self.profile.addItem(text, profile_id)
        self.profile.setCurrentIndex(max(self.profile.findData(profile), 0))
        profile_label = QLabel(_("&Profile:"))
        profile_label.setBuddy(self.profile)
        self.connect_button = QPushButton(_("&Connect"))
        self.connect_button.setAutoDefault(False)
        self.connect_button.clicked.connect(self._connect)
        left_top = QHBoxLayout()
        if self._typed:
            left_top.addWidget(address_label)
            left_top.addWidget(self.address, 1)
        else:
            left_top.addWidget(self.host_label)
            left_top.addStretch(1)
            self.address.hide()
        right_top = QHBoxLayout()
        right_top.addWidget(profile_label)
        right_top.addWidget(self.profile, 1)
        right_top.addWidget(self.connect_button)

        # ---- two tabs: the commands, and the scripts, which change more of the PC ----
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.addTab(_("Commands"))
        self.tabs.addTab(_("Scripts"))
        self.tabs.setCurrentIndex(1 if scripts else 0)
        self.tabs.currentChanged.connect(lambda _index: self._filter())

        # ---- the groups, the commands, the results ----
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.groups = QListWidget()
        self.groups.setObjectName("pageList")
        self.groups.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.groups.itemClicked.connect(self._jump)
        self.groups.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Wide enough for the longest group name in any language, so none is cut off and the
        # columns don't move on a language switch.
        metrics = self.groups.fontMetrics()
        longest = max(
            metrics.horizontalAdvance(name)
            for group in CommandGroup
            for name in i18n.in_every_language(GROUP_NAMES[group])
        )
        groups_width = max(GROUPS_WIDTH, longest + GROUP_ROOM)
        for widget in (self.search, self.groups):
            widget.setFixedWidth(groups_width)
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self.search)
        left.addWidget(self.groups, 1)
        self._headings: dict[CommandGroup, QLabel] = {}
        self._gaps: dict[CommandGroup, QWidget] = {}  # above each heading
        self.rows: list[CommandRow] = []
        column = QWidget()
        rows = QVBoxLayout(column)
        rows.setContentsMargins(0, 0, 8, 0)
        rows.setSpacing(ROW_SPACING)
        for group in CommandGroup:
            commands = host_commands.in_group(group)
            if not commands and group is not CommandGroup.OWN:
                continue
            heading = QLabel(_(GROUP_NAMES[group]).upper())
            heading.setObjectName("groupHeading")
            # Gaps are widgets, so they hide with their group or command (another tab, a search).
            self._gaps[group] = _gap(6 - ROW_SPACING)
            rows.addWidget(self._gaps[group])
            rows.addWidget(heading)
            self._headings[group] = heading
            item = QListWidgetItem(_(GROUP_NAMES[group]))
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.groups.addItem(item)
            if group is CommandGroup.OWN:  # filled from the scripts folder, again on a change
                rows.addWidget(self._own_bar())
                self._own_box = QWidget()
                self._own_rows = QVBoxLayout(self._own_box)
                self._own_rows.setContentsMargins(0, 0, 0, 0)
                self._own_rows.setSpacing(ROW_SPACING)
                rows.addWidget(self._own_box)
            for command in commands:
                row = CommandRow(self, command)
                if command.apart:
                    row.gap = _gap(APART - ROW_SPACING)  # where menus draw a line
                    rows.addWidget(row.gap)
                self.rows.append(row)
                rows.addWidget(row)
        rows.addStretch(1)
        self.list = QScrollArea()
        self.list.setWidget(column)
        self.list.setWidgetResizable(True)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.verticalScrollBar().valueChanged.connect(self._follow_scroll)
        self.results = Results()
        self.results.setFixedWidth(RESULTS_WIDTH)
        self.results.session_menu_requested.connect(self._session_menu)
        self.results.list_menu_requested.connect(self._list_menu)
        self.results.copied.connect(lambda text: tool.say(_("Copied: {text}").format(text=text)))

        hint = QLabel(_("↑ ↓ pick, Enter runs, typing searches. Commands that need more open a "
                        "small window; risky ones ask first."))  # fmt: skip
        hint.setObjectName("hint")
        self.add_button = QPushButton(_("A&dd to list…"))
        self.add_button.setAutoDefault(False)
        self.add_button.clicked.connect(self._add_to_list)
        close = QPushButton(_("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.close)

        grid = QGridLayout(self)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addLayout(left_top, 0, 0, 1, 4)
        grid.addLayout(right_top, 0, 4)
        grid.addWidget(self.tabs, 1, 0, 1, 3)
        grid.addLayout(left, 2, 0)
        grid.addWidget(_divider(), 2, 1)
        grid.addWidget(self.list, 2, 2)
        grid.addWidget(_divider(), 1, 3, 2, 1)
        grid.addWidget(self.results, 1, 4, 2, 1)
        grid.addWidget(hint, 3, 0, 1, 5)
        bottom = QHBoxLayout()
        bottom.addWidget(self.add_button)
        bottom.addStretch(1)
        bottom.addWidget(close)
        grid.addLayout(bottom, 4, 0, 1, 5)
        grid.setColumnMinimumWidth(0, groups_width)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(2, 1)

        self._picked: CommandRow | None = None
        self._fill_own()
        tool.own_scripts.changed.connect(self._fill_own)
        tool.host_changed.connect(self._changed)
        tool.runner.facts_changed.connect(self._changed)
        self.address.editTextChanged.connect(self._address_typed)
        self.search.installEventFilter(self)
        self._filter()  # the tab's commands only
        self._show_target()
        (self.address if self._typed else self.search).setFocus()

    # ---- the PC ----

    def target(self) -> HostTarget | None:
        if not self._typed:
            return self._target
        typed = self.address.currentText().strip()
        if not typed:
            return None
        address = split_address(typed).address
        return HostTarget("@" + address.casefold(), address, address)

    def _address_typed(self) -> None:
        self._show_target()

    def _show_target(self) -> None:
        target = self.target()
        title = _("Manual connection") if self._typed else _("Commands")
        self.setWindowTitle(f"{title} · {target.name}" if target else title)
        if target is not None and not self._typed:
            shown = (f"<b>{_escape(target.name)}</b>" if target.name == target.address
                     else f"<b>{_escape(target.name)}</b> · {_escape(target.address)}")  # fmt: skip
            self.host_label.setText(shown)
        for row in self.rows:
            review = row.script is not None and not row.script.ready  # needs no PC
            row.run.setEnabled(target is not None or review)
        self.connect_button.setEnabled(target is not None and self.profile.count() > 0)
        self._update_add()
        self._update_names()
        self._show_results()

    def _update_add(self) -> None:
        target = self.target()
        places = self._tool.where_in_list(target.address) if target else []
        self.add_button.setEnabled(target is not None and not places and
                                   self._tool.can_add_hosts())  # fmt: skip
        if places:
            where = "; ".join(_("in {group}, as {name}").format(group=g or _("No group"), name=n)
                              for g, n in places)  # fmt: skip
            self.add_button.setToolTip(_("Already in this list: {where}").format(where=where))
        else:
            self.add_button.setToolTip(_("Adds this PC to the open host list"))

    def _update_names(self) -> None:
        """The user's folder row names the person: "ana.admin's folder"."""
        target = self.target()
        found = self._tool.users_found(target.key) if target else None
        who = folder_user(found[0] if found else None)
        for row in self.rows:
            if row.command.id == "user-folder":
                row.set_name(_("{user}'s folder").format(user=who.user) if who
                             else _(row.command.name))  # fmt: skip

    def _changed(self, key: str) -> None:
        target = self.target()
        if target is not None and key == target.key:
            self._update_names()
            self._show_results()

    # ---- the commands ----

    def pick(self, row: CommandRow) -> None:
        if self._picked is row:
            return
        if self._picked is not None:
            self._picked.set_picked(False)
        self._picked = row
        row.set_picked(True)
        QTimer.singleShot(0, self, lambda: self._scroll_to(row))  # dropped if the window goes
        self._show_results()

    def _scroll_to(self, row: CommandRow) -> None:
        """Up or down to the row; never sideways, which cut the group headings off."""
        self.list.ensureWidgetVisible(row, 0, 4)
        self.list.horizontalScrollBar().setValue(0)

    def picked(self) -> HostCommand | None:
        return self._picked.command if self._picked is not None else None

    def run(self, command: HostCommand) -> None:
        row = next((r for r in self.rows if r.command is command), None)
        script = row.script if row is not None else None
        if script is not None and not script.ready:
            self.review(script)
            return
        target = self.target()
        if target is None:
            return
        if self._typed:
            self._tool.remember_address(self.address.currentText().strip())
        if command.id in LISTS:
            self._read_list(command.id, target)
        elif script is not None and row is not None:
            self._tool.runner.run_own(script, target, self._report, row.run_as_choice())
        else:
            self._tool.runner.run(command.id, target, self._report, parent=self)
        self._show_results()

    # ---- printers and programs, as tables on the right ----

    def _read_list(self, command_id: str, target: HostTarget) -> None:
        key = (target.key, command_id)
        before = self._lists.get(key)
        self._lists[key] = Listed(True, before.when if before else None,
                                  before.rows if before else ())  # fmt: skip
        self._outcomes.pop(key, None)

        def work(account: Account | None) -> Listed:
            if command_id == "programs":
                from capypanel.core.remote import inventory

                rows: Sequence[Any] = inventory.installed_programs(target.address, account)
                return Listed(False, datetime.now(UTC), rows)
            rows = host_printers.list_printers(target.address, account)
            try:
                spooler = services.service_state(target.address, services.SPOOLER, account)
            except RemoteError:
                spooler = ""  # listed anyway: only its state line goes
            return Listed(False, datetime.now(UTC), rows, spooler)

        def done(listed: Listed) -> None:
            if self._alive():
                self._lists[key] = listed
                self._show_results()

        def failed(error: BaseException) -> None:
            if not self._alive():
                return
            self._lists.pop(key, None)
            action = (
                _("read the printers")
                if command_id == "printers"
                else _("read the installed programs")
            )
            retry = None
            if isinstance(error, RemoteError) and error.reason in RETRY_REASONS:
                again = lambda: self._read_list(command_id, target)  # noqa: E731
                retry = lambda: self._tool.runner.another_account(target, error, again)  # noqa: E731
            self._outcomes[key] = Outcome(failed_text(action, target.name, error), error, retry)
            self._show_results()

        self._tool.runner.call(work, done, failed)

    def _list_menu(self, command_id: str, index: int, where: QPoint) -> None:
        target = self.target()
        listed = self._lists.get((target.key, command_id)) if target else None
        if target is None or listed is None:
            return
        menu = QMenu(self)
        row = listed.rows[index] if 0 <= index < len(listed.rows) else None
        if command_id == "printers":
            clear = menu.addAction(_("Clear &queue…"))
            clear.setEnabled(row is not None and row.jobs > 0)
            clear.triggered.connect(lambda: self._clear_queue(target, row))
            copy = menu.addAction(_("&Copy row"))
            copy.setEnabled(row is not None)
            if row is not None:
                text = "\t".join([row.name, windows.printer_status(row), str(row.jobs)])
                copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(text))
        else:
            header, rows = windows.program_header(), windows.program_rows(listed.rows)
            copy = menu.addAction(_("&Copy row"))
            copy.setEnabled(row is not None)
            copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(
                "\t".join(rows[index])))  # fmt: skip
            menu.addSeparator()
            menu.addAction(_("Copy &list"), lambda: QGuiApplication.clipboard().setText(
                write_csv(header, rows, "\t")))  # fmt: skip
            menu.addAction(_("&Export CSV…"), lambda: windows.export_csv(
                self, target.name, header, rows, self._tool.csv_folder))  # fmt: skip
            menu.addSeparator()
            menu.addAction(_("&Open in its own window…"), lambda: run_modal(
                windows.ProgramsDialog(self, self._tool.runner, target, self._tool.csv_folder,
                                       listed.rows, listed.when)))  # fmt: skip
        menu.exec(where)

    def _clear_queue(self, target: HostTarget, printer: Any) -> None:
        if printer is None or not windows.ask_clear_queue(self, target.name, printer):
            return
        key = (target.key, "printers")

        def done(_value: object) -> None:
            if not self._alive():
                return
            self._tool.say(_("Cleared the queue of {printer} on {host}.").format(
                printer=printer.name, host=target.name))  # fmt: skip
            self._read_list("printers", target)

        def failed(error: BaseException) -> None:
            if not self._alive():
                return
            action = _("clear the queue of {printer}").format(printer=printer.name)
            self._outcomes[key] = Outcome(failed_text(action, target.name, error), error)
            self._show_results()

        self._tool.runner.call(
            lambda account: host_printers.clear_queue(target.address, printer.name, account),
            done,
            failed,
        )

    def _alive(self) -> bool:
        """Still open: an answer can come back after the window was closed and deleted."""
        return shiboken6.isValid(self) and shiboken6.isValid(self.results)

    def _report(self, command_id: str, outcome: Outcome) -> None:
        if not self._alive():
            return
        target = self.target()
        if target is not None:
            self._outcomes[(target.key, command_id)] = outcome
            self._show_results()

    def _show_results(self) -> None:
        target, command = self.target(), self.picked()
        if target is None or command is None:
            self.results.show_item(None, 0)
            return
        tool = self._tool
        status = tool.status_found(target.key)
        self.results.show_item(
            Shown(
                target,
                command,
                status,
                tool.users_found(target.key),
                tool.facts_of(target.key),
                self._outcomes.get((target.key, command.id)),
                self._lists.get((target.key, command.id)),
            ),
            1,
        )

    def _session_menu(self, session: Session, where: QPoint) -> None:
        target = self.target()
        if target is not None:
            self._tool.session_menu(session, where, target, self._report, parent=self)

    def _visible_rows(self) -> list[CommandRow]:
        return [r for r in self.rows if not r.isHidden()]

    def _move(self, step: int) -> None:
        shown = self._visible_rows()
        if not shown:
            return
        index = shown.index(self._picked) if self._picked in shown else -1
        self.pick(shown[max(0, min(len(shown) - 1, index + step))])

    def showing_scripts(self) -> bool:
        return self.tabs.currentIndex() == 1

    def _filter(self) -> None:
        """The tab's commands; typing narrows every group to those whose name or description
        match."""
        needle = self.search.text().strip().casefold()
        scripts = self.showing_scripts()
        for row in self.rows:
            text = f"{row.name.text()} {row.about.text()}".casefold()
            in_tab = (row.command.group in SCRIPT_GROUPS) == scripts
            row.setHidden(not in_tab or (bool(needle) and needle not in text))
            if row.gap is not None:
                row.gap.setHidden(row.isHidden())
        first = True
        for index in range(self.groups.count()):
            item = self.groups.item(index)
            group = item.data(Qt.ItemDataRole.UserRole)
            any_shown = any(not r.isHidden() for r in self.rows if r.command.group == group)
            if group is CommandGroup.OWN:  # shown even when empty: its folder and Rescan
                any_shown = scripts and (not needle or any_shown)
                self._own_line.setHidden(not any_shown)
            self._headings[group].setHidden(not any_shown)
            self._gaps[group].setHidden(not any_shown or first)  # none above the first
            first = first and not any_shown
            item.setHidden(not any_shown)
        shown = self._visible_rows()
        if shown and self._picked not in shown:
            self.pick(shown[0])
            self.list.verticalScrollBar().setValue(0)

    # ---- your own scripts ----

    def _own_bar(self) -> QWidget:
        """Under Your scripts: where they come from, Rescan, and the folder."""
        self._own_line = QWidget()
        self._own_hint = hint_label()  # what's wrong, when something is
        self._own_path = PathLabel()  # else the folder, cut in the middle
        color = self.palette().color(QPalette.ColorRole.Text)
        self._rescan = _icon_button("refresh", color, _("Rescan the scripts folder"))
        self._rescan.clicked.connect(self._tool.own_scripts.rescan)
        self._folder_button = _icon_button("folder-search", color, "")
        self._folder_button.clicked.connect(self._open_scripts_folder)
        line = QHBoxLayout(self._own_line)
        line.setContentsMargins(8, 0, 6, 2)
        line.setSpacing(4)
        line.addWidget(self._own_hint, 1)
        line.addWidget(self._own_path, 1)
        line.addWidget(self._rescan)
        line.addWidget(self._folder_button)
        return self._own_line

    def _fill_own(self) -> None:
        """Your scripts' rows, from what the scripts folder holds now."""
        if not self._alive():
            return
        own = self._tool.own_scripts
        picked = self._picked.command.id if self._picked is not None else ""
        for row in [r for r in self.rows if r.script is not None]:
            self.rows.remove(row)
            if row is self._picked:
                self._picked = None
            row.hide()
            row.deleteLater()
        for script in own.scripts:
            risky = bool(script.ready and script.approval and script.approval.risky)
            command = HostCommand(script.id, CommandGroup.OWN, script.name,
                                  _own_description(script), "bolt", Need.RUN,
                                  risky=risky)  # fmt: skip
            row = CommandRow(self, command, script)
            self.rows.append(row)
            self._own_rows.addWidget(row)
        folder = own.folder()
        if folder is None:
            text = _("Choose a scripts folder in Settings › Hosts › General.")
        elif own.scanning:
            text = _("Reading {folder}…").format(folder=folder)
        elif own.error is not None:
            text = _("Couldn't read {folder}: {error}").format(folder=folder, error=own.error)
        elif not own.scripts:
            text = _("No .ps1, .bat or .cmd files in {folder}.").format(folder=folder)
        else:
            text = ""
        self._own_hint.setText(text)
        self._own_hint.setVisible(bool(text))
        self._own_path.set_path(folder or "")
        self._own_path.setVisible(not text)
        self._rescan.setVisible(folder is not None)
        self._rescan.setEnabled(not own.scanning)
        self._folder_button.setToolTip(_("Open the scripts folder") if folder
                                       else _("Choose a scripts folder"))  # fmt: skip
        target = self.target()
        for row in self.rows:
            if row.script is not None:
                row.run.setEnabled(target is not None or not row.script.ready)
        again = next((r for r in self.rows if r.command.id == picked), None)
        if again is not None:
            self.pick(again)
        self._filter()

    def _open_scripts_folder(self) -> None:
        folder = self._tool.own_scripts.folder()
        if folder is None:
            self._tool.open_settings("hosts")
        else:
            open_folder(folder)

    def review(self, script: OwnScript) -> None:
        dialog = ReviewDialog(self, script)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._tool.own_scripts.approve(script, dialog.approval())

    def own_menu(self, script: OwnScript, where: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(_("Re&view…"), lambda: self.review(script))
        menu.addAction(_("Open &folder"), lambda: open_folder(script.file.parent))
        menu.addSeparator()
        menu.addAction(_("Re&scan"), self._tool.own_scripts.rescan)
        menu.exec(where)

    def _jump(self, item: QListWidgetItem) -> None:
        heading = self._headings[item.data(Qt.ItemDataRole.UserRole)]
        bar = self.list.verticalScrollBar()
        bar.setValue(min(heading.y(), bar.maximum()))
        rows = [r for r in self._visible_rows() if r.command.group == item.data(
            Qt.ItemDataRole.UserRole)]  # fmt: skip
        if rows:
            self.pick(rows[0])

    def _follow_scroll(self, value: int) -> None:
        """The group in view is the one marked on the left, as in Settings."""
        current = None
        for index in range(self.groups.count()):
            item = self.groups.item(index)
            if item.isHidden():
                continue
            heading = self._headings[item.data(Qt.ItemDataRole.UserRole)]
            if heading.y() <= value + ROW:
                current = item
        bar = self.list.verticalScrollBar()
        if value >= bar.maximum() and bar.maximum() > 0:  # at the end: the last group
            shown = [self.groups.item(i) for i in range(self.groups.count())
                     if not self.groups.item(i).isHidden()]  # fmt: skip
            current = shown[-1] if shown else current
        if current is not None:
            self.groups.blockSignals(True)
            self.groups.setCurrentItem(current)
            self.groups.blockSignals(False)

    # ---- the keyboard ----

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """↑ and ↓ in the search field move the pick, as everywhere else in the window."""
        if (
            watched is self.search
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            self._move(-1 if event.key() == Qt.Key.Key_Up else 1)
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing deletes the window: its key watch on the search goes first, so no key
        reaches it while its parts are being deleted."""
        self.search.removeEventFilter(self)
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move(-1 if event.key() == Qt.Key.Key_Up else 1)
            return
        text = event.text()
        if (
            text
            and text.isprintable()
            and not event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self.search.setFocus()
            self.search.insert(text)  # typing searches, wherever the focus was
            return
        super().keyPressEvent(event)

    # ---- the bottom and top buttons ----

    def _connect(self) -> None:
        target = self.target()
        if target is None:
            return
        if self._typed:
            typed = self.address.currentText().strip()
            self._tool.remember_address(typed)
            where = split_address(typed)
        else:
            where = Target(target.address)
        self._tool.connector.connect(
            [Request(target.name, where, self.profile.currentData() or "")]
        )

    def _add_to_list(self) -> None:
        target = self.target()
        if target is None:
            return
        host_id = self._tool.add_typed_host(target.address, self.profile.currentData() or "")
        if host_id is not None:
            self._update_add()


def _own_description(script: OwnScript) -> str:
    """The line under your own script: its file and whether it asks, or why it can't run."""
    approval = script.approval
    if not script.ready or approval is None:
        return {
            State.NEW: _("New in the scripts folder. Review it before it can run."),
            State.CHANGED: _("Changed since it was approved. Review it again before it can run."),
            State.OPEN: _("Every user can change this file, so it can't run."),
            State.TOO_BIG: _("Too big for a script, so it can't run."),
            State.UNREADABLE: _("The file couldn't be read."),
        }[script.state]
    asks = _("Asks before every run.") if approval.risky else _("Runs without asking.")
    return f"{script.file.name}. {asks}"


def _icon_button(icon: str, color: QColor, tip: str) -> QToolButton:
    """A small icon button, as in the Details panel's row."""
    button = QToolButton()
    button.setObjectName("commandButton")
    button.setIcon(tabler_icon(icon, color, ICON))
    button.setToolTip(tip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _gap(height: int) -> QWidget:
    gap = QWidget()
    gap.setFixedHeight(height)
    return gap


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("pagesDivider")
    line.setFixedWidth(1)
    return line


def _escape(text: str) -> str:
    import html

    return html.escape(text, quote=False)
