"""The SSH tool: the list workspace with servers and switches, each with its port and the name to
log in as. Refresh checks each one's SSH port, and Connect opens Windows' ssh.exe on it in a
console window of its own; CapyPanel never sees a password."""

import logging
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QMenu, QMessageBox, QToolButton, QWidget

from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.model import Group, Host, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.status import PortState
from capypanel.core.ssh import launch
from capypanel.core.ssh.host import SshInfo, info_of, with_info
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.hosts import group_path
from capypanel.ui.list_workspace.customize import Part
from capypanel.ui.list_workspace.panels import is_sample, offers_typed
from capypanel.ui.list_workspace.texts import EmptyTexts, ListTexts
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.shortcuts import KeyCommand
from capypanel.ui.ssh_tool import status
from capypanel.ui.ssh_tool.actions import create_actions, retranslate_actions
from capypanel.ui.ssh_tool.details import SshDetails, SshDetailsPanel
from capypanel.ui.ssh_tool.dialog import SshHostDialog
from capypanel.ui.ssh_tool.refresh import SshRun, Target
from capypanel.ui.ssh_tool.settings import SshSettings
from capypanel.ui.ssh_tool.status import Cell, Checked
from capypanel.ui.ssh_tool.table import SshTable
from capypanel.ui.ssh_tool.toolbar import SshToolBar

log = logging.getLogger(__name__)
AT_ONCE = 10  # more selected connect only the first ones: a window each
AUTO_STATUS = "auto_status"  # Settings' Refresh status by itself: {"on": bool, "minutes": int}


def missing_text() -> str:
    """When Windows' SSH client isn't installed. Its page moved between Windows versions, so
    only its name is given."""
    return _("Windows' SSH client (ssh.exe) isn't installed on this PC. Add it in Optional "
             "features: “OpenSSH Client”.")  # fmt: skip


class SshTool(ListWorkspace):
    TOOL_ID = "ssh"
    ICON = "terminal-2"
    checks_changed = Signal()  # a Refresh started, found something, or ended

    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: SshTable = SshTable()
        self.details: SshDetailsPanel = SshDetailsPanel()
        self.toolbar: SshToolBar = SshToolBar(self.commands)
        self._checked: dict[str, Checked] = {}  # each host's last check, in memory only
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
        a.copy_address.triggered.connect(self._copy_address)
        # Details' buttons act on the one host it shows: the one selected.
        self.details.connect_clicked.connect(self.connect_selected)
        self.details.refresh_clicked.connect(lambda: self.check_hosts(self.selected_items()))

    # ---- texts ----

    def tool_name(self) -> str:
        return _("SSH")

    def menu_name(self) -> str:
        """No access key: View's S is the Status bar's and its H is Hosts'."""
        return _("SSH")

    def list_texts(self) -> ListTexts:
        return ListTexts(
            kind=self.TOOL_ID,
            everything=_("All hosts"),
            lists=_("SSH lists"),
            new=_("New SSH list"),
            add=_("Add an SSH list"),
            open=_("Open an SSH list"),
            remove=_("Remove SSH list"),
            manage=_("&Manage SSH lists…"),
            no_list=_("No SSH list is open."),
            choose_first=_("Open an SSH list to choose what it shows first."),
            not_this_kind=_("“{path}” isn't an SSH list."),
            file_filter=_("SSH lists (*.json);;All files (*)"),
        )

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
        return "ssh"

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
            replace(c, name=lambda: _("&Refresh host")) if c.id == fixed else c
            for c in super().key_commands()
        ]

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self._stop_button.setText(_("Stop"))
        self.toolbar.retranslate()
        super().retranslate()

    def restyle(self) -> None:
        """After a theme switch: the dots and Details were drawn in the old theme's colours."""
        super().restyle()
        self.table.refill()
        self._selection_changed()

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
        """A choice made in Settings was kept: save it, and show the list's new name."""
        self._save_prefs()
        self._update_state()

    # ---- Connect ----

    def activate_selected(self) -> None:
        self.connect_selected()

    def connect_selected(self) -> None:
        """ssh.exe on each selected host, at most 10 at once: a console window each."""
        hosts = [h for h in self.selected_items() if not is_sample(h.id)]  # never connected
        if not hosts:
            return
        reachable = [h for h in hosts if h.connect_address]
        notes = []
        for host in reachable[:AT_ONCE]:
            if not self._open_ssh(host.connect_address, info_of(host), host.name):
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
            self._open_ssh(self._typed_host, SshInfo(), self._typed_host)

    def _open_ssh(self, destination: str, info: SshInfo, name: str) -> bool:
        """False when ssh.exe isn't installed, after saying so."""
        try:
            launch.connect(destination, info)
        except launch.SshMissing:
            QMessageBox.warning(self, "CapyPanel", missing_text())
            return False
        except ValueError:
            log.warning("Not connecting to %s: an address or login ssh.exe would misread", name)
            self._shell.show_message(
                _("Can't connect to “{host}”: its address or Log in as has a space or starts "
                  "with “-”.").format(host=name),
                10_000,
            )  # fmt: skip
        except OSError as e:
            log.warning("Couldn't start ssh.exe for %s: %s", name, e)
            self._shell.show_message(
                _("Couldn't start ssh.exe: {error}").format(error=e.strerror or e), 10_000
            )
        return True

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
            details = SshDetails(
                host,
                group_path(self._doc.hosts, host.group),
                self._checked.get(host.id),
                reachable=bool(host.connect_address),
                hidden=self.hidden_parts(),
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
        for action in (a.connect_host, a.copy_address):
            action.setEnabled(selected > 0)  # read-only lists can still connect
        idle = self._run is None
        a.refresh_shown.setEnabled(idle and bool(self.visible_items()))  # read-only lists too
        a.refresh_selected.setEnabled(idle and selected > 0)

    # ---- right-click menus ----

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None  # keeps Ctrl+Shift+C

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        """Connect first, then Refresh, copy, then managing the hosts. Refresh says how many;
        Edit is for one host only."""
        a = self.commands
        menu.addAction(a.connect_host)
        menu.setDefaultAction(a.connect_host)  # bold: what double-click and Enter do
        menu.addSeparator()
        one = len(items) == 1
        a.refresh_selected.setText(
            _("&Refresh host")
            if one
            else ngettext("&Refresh {n} host", "&Refresh {n} hosts", len(items)).format(
                n=len(items)
            )
        )
        menu.addAction(a.refresh_selected)
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        if one:
            menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        """Refresh group last, under a separator, as in Hosts: its hosts, its subgroups' too."""
        assert self._doc is not None
        hosts = list(self._doc.hosts.hosts_in(group.id))
        menu.addSeparator()
        refresh = menu.addAction(_("&Refresh group"))
        refresh.setEnabled(bool(hosts) and self._run is None)
        refresh.triggered.connect(lambda: self.check_hosts(hosts))

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
