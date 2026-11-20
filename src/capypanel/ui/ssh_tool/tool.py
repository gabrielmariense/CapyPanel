"""The SSH tool: the list workspace on the host list open in Hosts, the same one Hosts and Profile
cleanup show, each host with its port and the name to log in as: its own, or its group's, picked
in Details or from the right-click menus. Refresh checks each one's SSH port. Connect opens
Windows' ssh.exe on it in a tab
beside the list, its terminal drawn by CapyPanel (ui/ssh_tool/terminal); Connect in a separate
window opens it in a console window of its own. CapyPanel never sees a password: ssh.exe asks
for it, or uses a key."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QIcon
from PySide6.QtWidgets import QDialog, QLabel, QMenu, QMessageBox, QToolButton, QWidget

from capypanel.core.hosts import listfile
from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.model import Group, Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.status import PortState
from capypanel.core.ssh import launch
from capypanel.core.ssh.host import (
    SshInfo,
    connect_info,
    group_login,
    group_login_of,
    info_of,
    login_of,
    logins_in,
    with_group_login,
    with_info,
    with_login,
)
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.guides import Guide, Step
from capypanel.ui.hosts import group_path, host_list_texts
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.list_workspace.customize import Part
from capypanel.ui.list_workspace.panels import SAMPLE_ID, is_sample, offers_typed, sample_tag
from capypanel.ui.list_workspace.tabbed import TabbedListWorkspace
from capypanel.ui.list_workspace.texts import EmptyTexts, ListTexts
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.menus import plain, popup
from capypanel.ui.shortcuts import KeyCommand
from capypanel.ui.ssh_tool import status
from capypanel.ui.ssh_tool.actions import create_actions, retranslate_actions
from capypanel.ui.ssh_tool.details import SshDetails, SshDetailsPanel
from capypanel.ui.ssh_tool.dialog import LoginDialog, SshHostDialog, empty_text, follow_text
from capypanel.ui.ssh_tool.refresh import SshRun, Target
from capypanel.ui.ssh_tool.settings import SshSettings
from capypanel.ui.ssh_tool.status import Cell, Checked
from capypanel.ui.ssh_tool.table import SshTable
from capypanel.ui.ssh_tool.toolbar import SshToolBar
from capypanel.ui.tab_strip import PINNED, mark_icon
from capypanel.ui.themes import engine as themes

if TYPE_CHECKING:  # loaded at the first connection, never at CapyPanel's start
    from capypanel.ui.ssh_tool.terminal.tab import TerminalTab

log = logging.getLogger(__name__)
AT_ONCE = 10  # more selected connect only the first ones: a tab or a window each
AUTO_STATUS = "auto_status"  # Settings' Refresh status by itself: {"on": bool, "minutes": int}
POINTS = "terminal_points"  # the terminal's text size, as Ctrl+= and Ctrl+- left it
MIN_POINTS, MAX_POINTS, DEFAULT_POINTS = 8, 20, 10  # as the terminal's view takes them


def missing_text() -> str:
    """When Windows' SSH client isn't installed. Its page moved between Windows versions, so
    Start's search leads there instead, as Microsoft's own steps do for both."""
    return _("Windows' SSH client (ssh.exe) isn't installed on this PC. To add it, search Start "
             "for “Optional features” and add “OpenSSH Client”. Adding it needs an "
             "administrator.")  # fmt: skip


def _named(found: tuple[str, Group | None]) -> tuple[str, str]:
    """A group's name to log in as and the group's own name: comparable, as a Group isn't."""
    login, source = found
    return login, source.name if source is not None else ""


class SshTool(TabbedListWorkspace):
    TOOL_ID = "ssh"
    ICON = "terminal-2"
    HELP_PLACE = "ssh/ssh/"
    TABS_ICON = "server-2"  # the list's tab
    LISTS_FROM = listfile.HOSTS  # Hosts' open list: one list for every host (his words, 2026-11-18)
    checks_changed = Signal()  # a Refresh started, found something, or ended

    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: SshTable = SshTable()
        self.details: SshDetailsPanel = SshDetailsPanel()
        self.toolbar: SshToolBar = SshToolBar(self.commands)
        self._checked: dict[str, Checked] = {}  # each host's last check, in memory only
        # The connections' tabs, by key, left to right, and each one's name on its tab
        # ("srv-01 (2)" for a second one). Never saved: a restart opens none.
        self._connections: dict[str, TerminalTab] = {}
        self._tab_names: dict[str, str] = {}
        self._opened = 0  # connections opened so far: each tab's key
        super().__init__(
            shell,
            commands=self.commands,
            toolbar=self.toolbar,
            table=self.table,
            details=self.details,
        )
        for action in vars(self.commands).values():
            action.setParent(self)
        self._run: SshRun | None = None
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.setText(_("Stop"))
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
        self._auto_timer = QTimer(self)  # Settings: Refresh status by itself, if switched on
        self._auto_timer.timeout.connect(self._auto_status_check)
        self._apply_auto_status()
        self._typed_host = ""  # what the search offers to connect to
        self._connect_typed = QAction(self)
        self._connect_typed.triggered.connect(self._connect_to_typed)
        self.table.set_cells(self._cell)
        self.table.set_logins(self._login_shown)
        self.settings_pages = SshSettings(self)  # its part of Settings
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self.open_first_list()

    def status_widgets(self) -> list[QWidget]:
        """Shown on the right of the status bar: a Refresh's progress and Stop."""
        return [self._progress, self._stop_button]

    def _fill_inventory(self) -> None:
        a = self.commands
        self.toolbar.inventory_menu.addActions([a.add_host, a.add_group, a.manage_groups])
        self.toolbar.inventory_menu.addAction(self.sort_groups_action)  # as in Hosts

    def _connect(self) -> None:
        a = self.commands
        a.add_host.triggered.connect(self.add_item)
        # Not in any menu bar menu, so their shortcuts (Ctrl+Shift+C, Ctrl+N, F5) live here:
        # toolbar menus only take keys while they're open.
        self.addActions([a.copy_address, a.add_host, a.refresh_shown])
        a.refresh_shown.triggered.connect(lambda: self.check_hosts(self.visible_items()))
        a.refresh_selected.triggered.connect(lambda: self.check_hosts(self.selected_items()))
        # Enter connects only from the host table, so it never fires while typing.
        a.connect_host.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.connect_host)
        a.connect_host.triggered.connect(self.connect_selected)
        a.connect_window.triggered.connect(lambda: self.connect_selected(window=True))
        a.copy_address.triggered.connect(self._copy_address)
        # Details' buttons act on the one host it shows: the one selected.
        self.details.connect_clicked.connect(self.connect_selected)
        self.details.refresh_clicked.connect(lambda: self.check_hosts(self.selected_items()))
        menu = self.details.login_menu
        menu.aboutToShow.connect(lambda: self._fill_host_login_menu(menu, self.selected_items()))

    # ---- texts ----

    def tool_name(self) -> str:
        return _("SSH")

    def menu_name(self) -> str:
        """No access key: View's S is the Status bar's and its H is Hosts'."""
        return _("SSH")

    def list_texts(self) -> ListTexts:
        return host_list_texts()  # Hosts' lists, so Hosts' words

    def items_text(self, n: int) -> str:
        return ngettext("{n} host", "{n} hosts", n).format(n=n)

    def remove_items_text(self, items: Sequence[Host]) -> tuple[str, str]:
        if len(items) == 1:
            text = _("Remove “{name}” from the list?").format(name=items[0].name)
        else:
            text = ngettext(
                "Remove {n} host from the list?", "Remove {n} hosts from the list?", len(items)
            ).format(n=len(items))
        return _("Remove hosts"), text

    def selected_text(self, n: int) -> str:
        return ngettext("{n} selected", "{n} selected", n).format(n=n)

    def found_text(self, n: int) -> str:
        return ngettext("{n} found", "{n} found", n).format(n=n)

    def counted_text(self, name: str, n: int) -> str:
        return ngettext("{name} ({n} host)", "{name} ({n} hosts)", n).format(name=name, n=n)

    def selected_source_texts(self) -> tuple[str, str]:
        return _("Selected hosts"), _("the selected hosts")

    def lists_page(self) -> str:
        return "hosts"  # Hosts' General page manages the host lists it shows

    def only_tags_text(self, shown: int, total: int) -> str:
        return _("Only hosts with all of: {tags} · {shown} of {total} shown").format(
            tags="{tags}", shown=shown, total=total
        )

    def no_match_text(self) -> str:
        return _("No hosts in this group have all the picked tags.")

    def search_fields(self) -> tuple[list[str], str]:
        """Every column that shows, and the notes (which have no column)."""
        table = self.table
        # Each a lower-case word in the list "Search name, address, log in as, status…".
        words = (
            (table.ADDRESS, _("address")),
            (table.PORT, _("port")),
            (table.LOGIN, _("log in as")),
            (table.STATUS, _("status")),
            (table.TAGS, _("tags")),
        )
        fields = [_("name")]
        fields += [word for column, word in words if not table.isColumnHidden(column)]
        fields.append(_("notes"))  # no column, so always searched
        return fields, _("Searches every host in the list (Ctrl+F)")

    def empty_texts(self) -> EmptyTexts:
        """SSH has no import: an empty list offers Add only."""
        return EmptyTexts(
            _("This list has no hosts yet.\nAdd one to start."),
            _("This list has no hosts."),
            _("This group has no hosts yet."),
            _("Every host is in a group."),
            _("No host matches “{text}”."),
        )

    def typed_offer(self, typed: str, rows: Sequence[Host]) -> list[QAction]:
        """Connect to {host}, while no row is the server typed: it connects at once, on port 22
        with ssh.exe's own login, so it has no ellipsis."""
        if not offers_typed(typed, rows) or not launch.is_destination(typed.strip()):
            return []
        self._typed_host = typed.strip()
        self._connect_typed.setText(
            _("Connect to {host}").format(host=self._typed_host.replace("&", "&&"))
        )
        return [self._connect_typed]

    def key_commands(self) -> list[KeyCommand]:
        """Its menus' commands; Refresh host keeps its one-host name on the Keyboard shortcuts
        page, as the right-click menu counts the hosts it'll refresh."""
        fixed = f"{self.TOOL_ID}.refresh_selected"
        return [
            replace(c, name=lambda: _("Re&fresh host")) if c.id == fixed else c
            for c in super().key_commands()
        ]

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self._stop_button.setText(_("Stop"))
        self.toolbar.retranslate()
        super().retranslate()
        for key, tab in self._connections.items():
            tab.retranslate()
            self._show_tab(key)
        self._show_more()

    def restyle(self) -> None:
        """After a theme switch: the dots, Details and the tabs' marks were drawn in the old
        theme's colours."""
        super().restyle()
        self.table.refill()
        self._selection_changed()
        for key in self._connections:
            self._show_tab(key)

    # ---- adding and editing hosts ----

    def add_item_action(self) -> QAction:
        return self.commands.add_host

    def add_item(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        # An empty list gets its first group; one with hosts is never started over.
        base = doc.hosts if doc.hosts.groups or doc.hosts.hosts else starter_list()
        dialog = SshHostDialog(self, base, default_group=self.nav.selected_group_id())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            added, host = base.add_host(
                values.name,
                values.group,
                address=values.address,
                tags=values.tags,
                notes=values.notes,
            )
            new = added.update_host(with_info(host, values.info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        if self._commit(new):
            self.table.select_ids([host.id])

    def edit_item(self, item: Host) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = SshHostDialog(self, doc.hosts, item)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        edited = replace(
            item,
            name=values.name,
            address=values.address,
            group=values.group,
            tags=values.tags,
            notes=values.notes,
        )
        try:
            new = doc.hosts.update_host(with_info(edited, values.info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        if self._commit(new) and (values.address, values.info.port) != (
            item.address,
            info_of(item).port,
        ):
            self._forget_check(item.id)  # it was about another address or port

    # ---- settings ----

    def settings_group(self) -> SshSettings:
        return self.settings_pages

    def auto_status(self) -> tuple[bool, int]:
        """Settings' Refresh status by itself: off by default, every 5 minutes once on."""
        saved = self.prefs.get(AUTO_STATUS)
        saved = saved if isinstance(saved, dict) else {}
        minutes = saved.get("minutes", 5)
        ok = isinstance(minutes, int) and not isinstance(minutes, bool) and 1 <= minutes <= 120
        return saved.get("on") is True, minutes if ok else 5

    def set_auto_status(self, choice: tuple[bool, int]) -> None:
        on, minutes = choice
        if (on, minutes) != self.auto_status():
            self.prefs[AUTO_STATUS] = {"on": on, "minutes": minutes}
            self._apply_auto_status()

    def _apply_auto_status(self) -> None:
        on, minutes = self.auto_status()
        if on:
            self._auto_timer.start(minutes * 60_000)
        else:
            self._auto_timer.stop()

    def _auto_status_check(self) -> None:
        """The hosts shown, quietly; skipped while a Refresh runs or a guide's sample shows."""
        hosts = self.visible_items()
        if self._run is None and hosts and not self.sample_shown():
            self.check_hosts(hosts, quiet=True)

    def prefs_applied(self) -> None:
        """A choice made in Settings was kept: save it."""
        self._save_prefs()
        self._update_state()

    # ---- the guide ----

    def guide(self) -> Guide:
        """Its own first steps: lists, adding hosts, the table, Connect with what the first
        connection asks, Refresh all and a separate window (the window adds View last). No step
        asks for a click, and the sample is never connected or checked (is_sample)."""
        bar = self.toolbar

        def steps() -> list[Step]:
            first_time = _(
                "Connects to the host you picked, in a tab of its own beside the list. "
                "The first time, ssh.exe asks whether you trust the server."
            )
            # Satya's line on its own, after it: ssh.exe asks in English (ssh-words.md).
            type_yes = _("Type yes, then press Enter.")
            return [
                Step(_("Your lists"),  # Profile cleanup's words: the same lists, Hosts'
                     _("Pick a list here: these are the same lists as in Hosts, the shared one "
                       "and your own. Click a group below it to see just that group's hosts."),
                     lambda: self.nav),
                Step(_("Add hosts"),
                     _("Inventory › Add host needs a name and an address. The port and Log in "
                       "as are optional: without them, ssh.exe uses port 22 and its own "
                       "settings."), lambda: bar.inventory_button),
                Step(_("Your hosts"),
                     _("The list's hosts are here. A double-click connects, and a right-click "
                       "shows everything you can do with one."),
                     lambda: None, lambda: self.table, keep_clear=lambda: self.details,
                     area=lambda: self.sample_row(self.window())),
                Step(_("Connect"), f"{first_time} {type_yes}", lambda: bar.connect_button),
                Step(_("Refresh all"),
                     _("Checks whether each host shown answers on its SSH port. Nothing logs "
                       "in."), lambda: bar.refresh_button),
                Step(_("In a separate window"),
                     _("To keep a connection outside CapyPanel, right-click a host and pick "
                       "Connect in a separate window."), lambda: None, lambda: self.table),
            ]  # fmt: skip

        return Guide("ssh", steps, setup=self.show_sample, cleanup=self.hide_sample)

    def sample_item(self, group: str) -> Host:
        """The guide's sample server: a documentation address (192.0.2.x) that never answers,
        and never asked: Connect and Refresh leave every sample out (is_sample)."""
        host = Host(id=SAMPLE_ID, name=_("SRV-SAMPLE"), group=group, address="192.0.2.30",
                    tags=(sample_tag(),), notes=_("Shown only while a guide is open."))  # fmt: skip
        return with_info(host, SshInfo(login="admin"))

    # ---- Connect ----

    def activate_selected(self) -> None:
        self.connect_selected()

    def connect_selected(self, *, window: bool = False) -> None:
        """ssh.exe on each selected host, at most 10 at once: a tab each, the first one in
        front; or with `window`, a console window each."""
        hosts = [h for h in self.selected_items() if not is_sample(h.id)]  # never connected
        if not hosts:
            return
        reachable = [h for h in hosts if h.connect_address]
        notes = []
        for index, host in enumerate(reachable[:AT_ONCE]):
            info = connect_info(self._doc.hosts, host) if self._doc else info_of(host)
            if window:
                opened = self._open_ssh(host.connect_address, info, host.name)
            else:
                opened = self.open_connection(
                    host.connect_address, info, host.name, front=index == 0
                )
            if not opened:
                return  # ssh.exe is missing: the rest can't connect either
        if len(reachable) > AT_ONCE:
            notes.append(_("Only the first {n} connect at once.").format(n=AT_ONCE))
        if skipped := len(hosts) - len(reachable):
            notes.append(
                ngettext(
                    "{n} host has no address and was skipped.",
                    "{n} hosts have no address and were skipped.",
                    skipped,
                ).format(n=skipped)
            )
        if notes:
            self._shell.show_message(" ".join(notes), 10_000)

    def _connect_to_typed(self) -> None:
        """The search's Connect to {host}: the server typed, on port 22, as ssh.exe chooses."""
        if self._typed_host:
            self.open_connection(self._typed_host, SshInfo(), self._typed_host)

    def _open_ssh(self, destination: str, info: SshInfo, name: str) -> bool:
        """In a separate window. False when ssh.exe isn't installed, after saying so."""
        try:
            launch.connect(destination, info, name)
        except launch.SshMissing:
            QMessageBox.warning(self, "CapyPanel", missing_text())
            return False
        except ValueError:
            self._cant_connect(name)
        except OSError as e:
            self._couldnt_start(name, e)
        return True

    def open_connection(
        self, destination: str, info: SshInfo, name: str, *, front: bool = True
    ) -> bool:
        """ssh.exe in a tab of its own, at the right end; `front` brings it to the front with
        the keys going to it. False when ssh.exe isn't installed, after saying so."""
        try:
            argv = launch.tab_command(destination, info)
        except launch.SshMissing:
            QMessageBox.warning(self, "CapyPanel", missing_text())
            return False
        except ValueError:
            self._cant_connect(name)
            return True
        from capypanel.ui.ssh_tool.terminal.tab import TerminalTab  # the first connection's

        self._opened += 1
        key = f"connection-{self._opened}"
        tab = TerminalTab(host=name, point_size=self.terminal_points())
        tab.changed.connect(lambda: self._show_tab(key))
        tab.close_asked.connect(lambda: self.close_tab(key))
        tab.view.size_picked.connect(self._size_picked)
        self._connections[key] = tab
        self._tab_names[key] = self._tab_name(name)
        self.add_page(key, tab, self._tab_names[key])
        try:
            tab.start(argv)
        except OSError as e:
            self._drop(key)
            self._couldnt_start(name, e)
            return True
        if front:
            self.switch(key)
        self._show_tab(key)
        return True

    def _cant_connect(self, name: str) -> None:
        log.warning("Not connecting to %s: an address or login ssh.exe would misread", name)
        self._shell.show_message(
            _("Can't connect to “{host}”: its address or Log in as has a space, starts with "
              "“-”, or has a character such as ; & | or quotes.").format(host=name),
            10_000,
        )  # fmt: skip

    def _couldnt_start(self, name: str, e: OSError) -> None:
        log.warning("Couldn't start ssh.exe for %s: %s", name, e)
        self._shell.show_message(
            _("Couldn't start ssh.exe: {error}").format(error=e.strerror or e), 10_000
        )

    # ---- the connections' tabs ----

    def _tab_name(self, host: str) -> str:
        """The host's name, and from its second tab on its number: "srv-01 (2)". A number
        freed by a closed tab is used again."""
        taken = set(self._tab_names.values())
        n = 1
        while (host if n == 1 else f"{host} ({n})") in taken:
            n += 1
        return host if n == 1 else f"{host} ({n})"

    def page_of(self, key: str) -> QWidget | None:
        return self._connections.get(key)

    def connections(self) -> list["TerminalTab"]:
        """The connections' tabs, left to right."""
        return [self._connections[k] for k in self.tabs.tab_keys() if k in self._connections]

    def switch(self, key: str) -> None:
        super().switch(key)
        tab = self._connections.get(key)
        if tab is not None:
            tab.view.setFocus()  # typing goes to the server at once

    def _mark(self, tab: "TerminalTab") -> tuple[QIcon, str]:
        """A tab's mark and its words: the plug while the connection is open, then the strip's
        own icon and colour once it has ended."""
        if tab.running:
            icon = mark_icon("plug-connected", themes.status_color("online"))
            return icon, _("Connection open")
        if tab.ended:
            icon = mark_icon(tab.bar.icon_name(), tab.bar.colour())
            return icon, _("Ended with an error") if tab.bar.error else _("Ended")
        return QIcon(), ""

    def _show_tab(self, key: str) -> None:
        tab = self._connections.get(key)
        if tab is not None:
            icon, tip = self._mark(tab)
            self.tabs.show_tab(key, self._tab_names[key], icon, tip, closable=True)
            self._show_more()

    def _show_more(self) -> None:
        """The list's tab and ▾'s list of every tab."""
        doc = self.document
        n = len(doc.hosts.hosts) if doc is not None else 0
        text = _("Hosts ({n})").format(n=n)
        self.tabs.set_pinned_text(text)
        items = [(PINNED, text, QIcon())]
        for key in self.tabs.tab_keys():
            tab = self._connections.get(key)
            if tab is not None:
                items.append((key, self._tab_names[key], self._mark(tab)[0]))
        self.tabs.set_more(items)

    def close_tab(self, key: str) -> bool:
        tab = self._connections.get(key)
        if tab is None:
            return False  # the list's tab
        if tab.running and not self._close_asked([tab]):
            return False
        self._drop(key)
        return True

    def close_tabs(self, keys: Sequence[str]) -> None:
        """Several tabs; one question for the connections still open among them."""
        tabs = [self._connections[k] for k in keys if k in self._connections]
        live = [t for t in tabs if t.running]
        if live and not self._close_asked(live):
            return
        for key in keys:
            if key in self._connections:
                self._drop(key)

    def _close_asked(self, live: Sequence["TerminalTab"]) -> bool:
        """Before closing open connections: what runs on the server from them may stop. The
        words are Satya's (ssh-words.md); the title is the action's, as Hosts' Log off."""
        n = len(live)
        if n == 1:
            heading = _("Close the connection to {host}?").format(host=live[0].host)
        else:
            heading = ngettext(
                "Close {n} open connection?", "Close {n} open connections?", n
            ).format(n=n)
        # One ngettext for both: a language whose singular covers more than 1 (21 in some) still
        # gets "it on the server" with "{n} open connection" (Satya, build 618).
        text = ngettext(
            "Anything still running in it on the server may stop.",
            "Anything still running in them on the servers may stop.",
            n,
        )
        question = Question(
            self, _("Close"), heading, text, _("&Close"), place="ssh-work-in-the-terminal"
        )
        return run_modal(question) == QDialog.DialogCode.Accepted

    def _drop(self, key: str) -> None:
        """Ends the connection and takes its tab away."""
        tab = self._connections.pop(key)
        del self._tab_names[key]
        tab.close_connection()
        self.remove_page(key, tab)
        tab.deleteLater()
        self._show_more()

    def tab_menu(self, key: str, where: QPoint) -> None:
        tab = self._connections.get(key)
        if tab is None:
            return
        menu = QMenu(self)
        # No access keys, as in Profile cleanup's tab menu; the strip's button has one.
        reconnect = menu.addAction(plain(_("&Reconnect")), tab.view.restart)
        reconnect.setEnabled(tab.ended)
        menu.addSeparator()
        menu.addAction(_("Close"), lambda: self.close_tab(key))
        others = [k for k in self.tabs.tab_keys() if k != key]
        menu.addAction(_("Close the others"), lambda: self.close_tabs(others)).setEnabled(
            bool(others)
        )
        ended = [k for k, t in self._connections.items() if t.ended]
        menu.addAction(_("Close the ended ones"), lambda: self.close_tabs(ended)).setEnabled(
            bool(ended)
        )
        popup(menu, where)

    def quit_question(self, parent: QWidget) -> bool:
        """Before CapyPanel quits, or closes for an update: open connections ask once, and
        quitting closes them."""
        live = [t for t in self._connections.values() if t.running]
        if not live:
            return True
        n = len(live)
        question = Question(
            parent,
            _("Quit CapyPanel"),
            ngettext(
                "Quit CapyPanel with {n} connection open?",
                "Quit CapyPanel with {n} connections open?",
                n,
            ).format(n=n),
            ngettext(
                "It closes, and anything still running in it on the server may stop.",
                "They all close, and anything still running in them on the servers may stop.",
                n,
            ),
            _("&Quit"),
            place="ssh-work-in-the-terminal",
        )
        if run_modal(question) != QDialog.DialogCode.Accepted:
            return False
        for tab in self._connections.values():
            tab.close_connection()
        return True

    # ---- the terminal's text size ----

    def terminal_points(self) -> int:
        """The text size Ctrl+= and Ctrl+- left, for every tab, kept after a restart."""
        points = self.prefs.get(POINTS)
        if isinstance(points, int) and not isinstance(points, bool):
            return max(MIN_POINTS, min(MAX_POINTS, points))
        return DEFAULT_POINTS

    def _size_picked(self, points: int) -> None:
        self.prefs[POINTS] = points
        self._save_prefs()
        for tab in self._connections.values():
            tab.view.set_point_size(points)

    def _copy_address(self) -> None:
        hosts = self.selected_items()
        if hosts:
            QGuiApplication.clipboard().setText("\n".join(h.target for h in hosts))

    # ---- showing ----

    def matches(self, item: Host, needle: str) -> bool:
        """The name and notes, plus every column that shows: only what can be seen. Status
        ("Not checked" too) comes from the last check, in memory only."""
        if super().matches(item, needle):
            return True
        table = self.table
        texts = table.row_texts(item)
        texts[table.STATUS] = self._cell(item.id).text
        return any(
            needle in texts[column].casefold()
            for column in range(1, len(table.COLUMNS))
            if not table.isColumnHidden(column)
        )

    def show_details(self, items: Sequence[Host]) -> None:
        if len(items) == 1 and self._doc is not None:
            host = items[0]
            login, source = login_of(self._doc.hosts, host)
            details = SshDetails(
                host,
                group_path(self._doc.hosts, host.group),
                self._checked.get(host.id),
                reachable=bool(host.connect_address),
                hidden=self.hidden_parts(),
                login=login,
                login_group=source.name if source is not None else "",
            )
            self.details.show_host(details, 1, needle=self._needle())
        else:
            self.details.show_host(None, len(items), summary=self._summary())

    def status_extras(self, doc: OpenList) -> list[str]:
        """How many hosts took a connection on their SSH port, once any was checked."""
        found = [self._checked[h.id] for h in doc.hosts.hosts if h.id in self._checked]
        if not found:
            return []
        online = sum(1 for checked in found if checked.state is PortState.OPEN)
        return [ngettext("{n} online", "{n} online", online).format(n=online)]

    def details_parts(self) -> list[Part]:
        return [
            Part("connection", _("Connection"), _("Address, port, Log in as, group")),
            Part("tags", _("Tags"), _("The host's tags")),
            Part("notes", _("Notes"), _("The host's notes")),
        ]

    def details_always(self) -> str:
        return _("Always shown: the host's name and its status.")

    def _summary(self) -> str:
        """With nothing selected, the Details panel counts the hosts shown."""
        rows = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        shown = sum(1 for row in rows if row is not None and row.data(0, ROLE_ID))
        if not shown:
            return ""
        return ngettext("{n} host shown", "{n} hosts shown", shown).format(n=shown)

    def update_tool_state(self, writable: bool, selected: int) -> None:
        a = self.commands
        a.add_host.setEnabled(writable)
        for action in (a.connect_host, a.connect_window, a.copy_address):
            action.setEnabled(selected > 0)  # read-only lists can still connect
        self._show_more()  # the list's tab counts its hosts
        idle = self._run is None
        a.refresh_shown.setEnabled(idle and bool(self.visible_items()))  # read-only lists too
        a.refresh_selected.setEnabled(idle and selected > 0)

    # ---- right-click menus ----

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None  # keeps Ctrl+Shift+C

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        """Connect first, then Refresh, then Log in as under its own line (as Hosts has Commands
        run as), copy, then managing the hosts. Refresh says how many; Edit is for one host."""
        a = self.commands
        menu.addAction(a.connect_host)
        menu.setDefaultAction(a.connect_host)  # bold: what double-click and Enter do
        menu.addAction(a.connect_window)
        menu.setToolTipsVisible(True)  # says the separate window is outside CapyPanel
        menu.addSeparator()
        one = len(items) == 1
        a.refresh_selected.setText(
            _("Re&fresh host")
            if one
            else ngettext("Re&fresh {n} host", "Re&fresh {n} hosts", len(items)).format(
                n=len(items)
            )
        )
        menu.addAction(a.refresh_selected)
        menu.addSeparator()
        logins = menu.addMenu(_("&Log in as"))
        self._fill_host_login_menu(logins, items)
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        if one:
            menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        """Log in as, then Refresh group under its own line, as Hosts has Commands run as then
        Refresh group (Dante's check of build 630): its hosts, its subgroups' too."""
        assert self._doc is not None
        hosts = list(self._doc.hosts.hosts_in(group.id))
        menu.addSeparator()
        self._fill_group_login_menu(menu.addMenu(_("&Log in as")), group)
        menu.addSeparator()
        refresh = menu.addAction(_("Re&fresh group"))  # R is Remove's (Satya)
        refresh.setEnabled(bool(hosts) and self._run is None)
        refresh.triggered.connect(lambda: self.check_hosts(hosts))

    # ---- Log in as: Details' picker and the right-click menus ----

    def _login_shown(self, host: Host) -> str:
        """The table's Log in as: the host's own name, or its group's."""
        return login_of(self._doc.hosts, host)[0] if self._doc is not None else info_of(host).login

    def _fill_host_login_menu(self, menu: QMenu, hosts: Sequence[Host]) -> None:
        """Follow the group (with no name there, ssh.exe's own choice), each name the list
        uses, then Another name…; one is ticked when every host picked has it."""
        menu.clear()
        doc = self._doc
        hosts = [h for h in hosts if not is_sample(h.id)]  # a guide's sample is never changed
        if doc is None or not hosts:
            return
        follows = {_named(group_login_of(doc.hosts, h.group)) for h in hosts}
        if len(follows) == 1:
            login, group = next(iter(follows))
            follow, empty = follow_text(login, group), empty_text(login, group)
        else:
            follow = empty = _("From their groups")
        about = hosts[0].name if len(hosts) == 1 else self.details.selected_text(len(hosts))
        ids = [h.id for h in hosts]
        self._fill_login_menu(
            menu,
            {info_of(h).login for h in hosts},
            (follow, empty),
            about,
            lambda name: self.set_hosts_login(ids, name),
        )

    def _fill_group_login_menu(self, menu: QMenu, group: Group) -> None:
        """The name the group gives its hosts, as a host's menu: following its parent first."""
        doc = self._doc
        if doc is None:
            return
        login, parent = _named(group_login_of(doc.hosts, group.parent))
        about = _("Hosts in “{group}” without a name of their own log in with this one.")
        self._fill_login_menu(
            menu,
            {group_login(group)},
            (follow_text(login, parent), empty_text(login, parent)),
            about.format(group=group.name),
            lambda name: self.set_group_login(group.id, name),
        )

    def _fill_login_menu(
        self,
        menu: QMenu,
        current: set[str],
        follow: tuple[str, str],
        about: str,
        apply: Callable[[str], None],
    ) -> None:
        """`current`: the names picked now ("" follows); `follow`: the first choice's words and
        what Another name… says leaving its box empty gives."""
        doc = self._doc
        names = logins_in(doc.hosts) if doc is not None else []
        exclusive = QActionGroup(menu)
        for login, text in (("", follow[0]), *((name, name) for name in names)):
            item = menu.addAction(text.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current == {login})  # several that differ: none ticked
            exclusive.addAction(item)
            item.triggered.connect(lambda _checked=False, name=login: apply(name))
            if not login:
                menu.addSeparator()
        if names:
            menu.addSeparator()
        another = menu.addAction(_("&Another name…"))
        mine = next(iter(current)) if len(current) == 1 else ""
        another.triggered.connect(lambda: self._another_login(about, mine, follow[1], apply))
        writable = self._writable() is not None
        for action in menu.actions():
            action.setEnabled(writable)

    def _another_login(
        self, about: str, login: str, empty: str, apply: Callable[[str], None]
    ) -> None:
        dialog = LoginDialog(self, about, login, empty)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            apply(dialog.value())

    def set_hosts_login(self, host_ids: Sequence[str], login: str) -> None:
        """Their own name to log in as; "" follows their group again."""
        doc = self._writable()
        if doc is None:
            return
        wanted = set(host_ids)
        hosts = doc.hosts
        for host in hosts.hosts:
            if host.id in wanted:
                hosts = hosts.update_host(with_login(host, login))
        self._save_logins(hosts)

    def set_group_login(self, group_id: str, login: str) -> None:
        """The name the group gives its hosts that have none of their own."""
        doc = self._writable()
        if doc is not None and doc.hosts.group(group_id) is not None:
            self._save_logins(with_group_login(doc.hosts, group_id, login))

    def _save_logins(self, new: HostList) -> None:
        """Saved only when it changed (a ticked name picked again writes nothing); Details then
        shows the new name, as Hosts does after a profile is picked."""
        doc = self._doc
        if doc is not None and new != doc.hosts and self._commit(new):
            self._selection_changed()

    # ---- Refresh: the SSH port ----

    def check_hosts(self, hosts: Sequence[Host], *, quiet: bool = False) -> None:
        """One check of each host's SSH port, 8 at a time; a host with no address uses its name
        when that's a computer name, and is skipped otherwise."""
        hosts = [h for h in hosts if not is_sample(h.id)]  # a guide's samples: never checked
        if self._run is not None or not hosts:
            return
        targets = [Target(h.id, h.connect_address, info_of(h).port) for h in hosts
                   if h.connect_address]  # fmt: skip
        skipped = len(hosts) - len(targets)
        if skipped and not quiet:
            note = ngettext(
                "{n} host has no address and was skipped.",
                "{n} hosts have no address and were skipped.",
                skipped,
            )
            self._shell.show_message(note.format(n=skipped), 10_000)
        if not targets:
            return
        run = SshRun(targets)
        run.found.connect(self._found)
        run.finished.connect(self._run_finished)
        self._run = run
        self._show_progress()
        self._stop_button.setEnabled(True)
        self._update_state()
        self.checks_changed.emit()
        log.info("Refresh: %d SSH hosts", len(targets))
        run.start()

    def working(self) -> bool:
        """A Refresh is running, the button's or the one by itself: "Install and restart" waits
        for it."""
        return self._run is not None

    def stop_checks(self) -> None:
        if self._run is not None:
            self._run.stop()
            self._stop_button.setEnabled(False)  # hosts already being checked still finish

    def _found(self, host_id: str, checked: Checked) -> None:
        run = self._run
        if run is None:
            return
        run.done += 1
        self._checked[host_id] = checked
        self.table.show_cells(host_id)
        if self.table.selected_ids() in ([host_id], []):  # its details, or the summary
            self._selection_changed()
        self._show_progress()
        self.checks_changed.emit()

    def _forget_check(self, host_id: str) -> None:
        if self._checked.pop(host_id, None) is not None:
            self.table.show_cells(host_id)
            self._selection_changed()

    def _show_progress(self) -> None:
        run = self._run
        if run is not None:
            self._progress.setText(
                _("Checking {done} of {total}…").format(done=run.done, total=run.total)
            )
        self._progress.setVisible(run is not None)
        self._stop_button.setVisible(run is not None)

    def _run_finished(self) -> None:
        run = self._run
        if run is None:
            return
        self._run = None
        self._show_progress()
        self._update_state()
        self.checks_changed.emit()
        if run.stopped and run.done < run.total:
            left = run.total - run.done
            note = ngettext(
                "Stopped: {n} host wasn't checked.", "Stopped: {n} hosts weren't checked.", left
            )
            self._shell.show_message(note.format(n=left), 10_000)
        else:
            self._shell.show_message(
                ngettext("Checked {n} host.", "Checked {n} hosts.", run.done).format(n=run.done),
                5000,
            )

    def _cell(self, host_id: str) -> Cell:
        return status.cell(self._checked.get(host_id))
