"""The Hosts tool: the list workspace with hosts, plus connecting, connection profiles, Refresh
(status and logged-on users), the host commands (opening a PC's folders, messaging or logging off
its users, restarting it, its printers and facts, scripts), importing and Report."""

import html
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import settings
from capypanel.core.hosts import accounts as account_links
from capypanel.core.hosts import commands as host_commands
from capypanel.core.hosts.accounts import WINDOWS, Scope
from capypanel.core.hosts.commands import GROUP_NAMES
from capypanel.core.hosts.commands import Group as CommandGroup
from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import access, checks
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Answer, Status
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.connect import SessionCredentials, Target
from capypanel.core.tools.profile_store import ProfileStore
from capypanel.ui import checks as check_texts
from capypanel.ui.checks import AccountDialog, CheckRun
from capypanel.ui.connect import Connector, Request
from capypanel.ui.dialogs import run_modal
from capypanel.ui.export_hosts import ExportDialog
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.hosts import HostDialog, ProfilePicker, confirm, group_path, list_file_filter
from capypanel.ui.hosts_tool.accounts import Accounts, used_for, windows_account
from capypanel.ui.hosts_tool.actions import create_actions, retranslate_actions
from capypanel.ui.hosts_tool.details import HostDetails, HostDetailsPanel
from capypanel.ui.hosts_tool.host_state import Facts, PendingPower
from capypanel.ui.hosts_tool.result_strip import ResultStrip
from capypanel.ui.hosts_tool.runner import HostTarget, Outcome, Report, Runner, folder_user
from capypanel.ui.hosts_tool.settings import HostsSettings, SettingsPrefs
from capypanel.ui.hosts_tool.table import Cells, HostTable
from capypanel.ui.hosts_tool.toolbar import HostsToolBar, RefreshPanel
from capypanel.ui.icons import STATUS_COLORS, dot_icon, tabler_icon
from capypanel.ui.import_hosts import ImportDialog
from capypanel.ui.list_workspace.texts import ListTexts
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.saved_credentials import KeptLogin, forget_failed

log = logging.getLogger(__name__)
MANY_USER_CHECKS = 50  # reading logged-on users on more hosts than this asks first
# Host commands' keys; the rest have none for now (a Keyboard shortcuts page comes later).
COMMAND_SHORTCUTS = {
    "c-share": "Ctrl+E",
    "path": "Ctrl+Shift+O",
    "user-folder": "Ctrl+Shift+U",
    "computer-management": "Ctrl+Shift+M",
}
RECENT_PATHS = 10  # Open a path… keeps the last folders opened
FACTS_AFTER = 1_500  # ms a host stays selected before its PC facts are read
WATCH_EVERY = 15_000  # ms between checks on a restarting PC, until it answers again
WATCH_FOR = timedelta(minutes=20)  # after the restart time; then CapyPanel stops watching


class HostsTool(ListWorkspace):
    TOOL_ID = "hosts"
    ICON = "device-desktop"
    INHERITS_TOP_LEVEL = True  # 0.19 kept the Hosts settings at the top level
    checks_changed = Signal()  # a Refresh started, found something, or ended
    host_changed = Signal(str)  # new results for one host (its id, or "@" and an address)

    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: HostTable = HostTable()
        self.details: HostDetailsPanel = HostDetailsPanel()
        self.toolbar: HostsToolBar = HostsToolBar(self.commands)
        super().__init__(
            shell,
            commands=self.commands,
            toolbar=self.toolbar,
            table=self.table,
            details=self.details,
        )
        for action in vars(self.commands).values():
            action.setParent(self)
        credentials = SessionCredentials()
        self.connector = Connector(self, Catalogs.for_paths(shell.paths), credentials)
        self.connector.open_settings = lambda: self._shell.open_settings("connections")
        self.details.profile_menu.aboutToShow.connect(
            lambda: self._fill_details_profile_menu(self.details.profile_menu)
        )
        self.details.account_menu.aboutToShow.connect(
            lambda: self._fill_hosts_account_menu(self.details.account_menu, self.selected_items())
        )

        # Refresh results, by host id: in memory only, since the list file is shared.
        self._status_found: dict[str, tuple[Status, datetime, Answer | None]] = {}
        self._users_found: dict[
            str, tuple[tuple[Session, ...] | None, RemoteError | None, datetime]
        ] = {}
        self._run: CheckRun | None = None
        self.accounts = Accounts(self)  # which account signs in to which PC
        self.accounts.changed.connect(self._accounts_changed)
        self._refused: list[str] = []  # hosts this run that didn't let the account read users
        self._reported: set[str] = set()
        self._targets: list[tuple[str, str]] = []

        # Host commands: what they found (in memory only), the runner and its answers.
        self._facts: dict[str, Facts] = {}
        self._pending: dict[str, PendingPower] = {}  # restarts and shutdowns CapyPanel asked for
        self._probing: set[str] = set()  # restarting PCs being checked right now
        self._back_online: str | None = None  # the host the last notification was about
        self.runner = Runner(self)
        self.runner.facts_changed.connect(self._facts_changed)
        self.result_strip = ResultStrip()
        column = self.items_pane.layout()
        assert isinstance(column, QVBoxLayout)
        column.insertWidget(1, self.result_strip)  # right under the search box
        self.host_actions = self._make_host_actions()
        self._commands_window: QDialog | None = None
        self._facts_timer = QTimer(self)
        self._facts_timer.setSingleShot(True)
        self._facts_timer.setInterval(FACTS_AFTER)
        self._facts_timer.timeout.connect(self._read_shown_facts)
        self._watch = QTimer(self)
        self._watch.setInterval(WATCH_EVERY)
        self._watch.timeout.connect(self._watch_power)

        self.refresh_panel = RefreshPanel(self)
        self.refresh_panel.set_choices(self.prefs.get("refresh"))
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.setText(_("Stop"))
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self.settings_pages = HostsSettings(self)  # its part of Settings
        self._auto_timer = QTimer(self)  # Settings: Status by itself, if switched on
        self._auto_timer.timeout.connect(self._auto_status_check)
        self._apply_auto_status()
        self.open_first_list()

    def status_widgets(self) -> list[QWidget]:
        """Shown on the right of the status bar: a Refresh's progress and Stop."""
        return [self._progress, self._stop_button]

    def _fill_inventory(self) -> None:
        a = self.commands
        inventory = self.toolbar.inventory_menu
        inventory.addActions([a.add_host, a.add_group, a.manage_groups])
        inventory.addAction(self.sort_groups_action)
        inventory.addSeparator()
        inventory.addAction(a.import_hosts)

    def _connect(self) -> None:
        a = self.commands
        a.add_host.triggered.connect(self.add_item)
        a.import_hosts.triggered.connect(self.import_hosts)
        a.export_hosts.triggered.connect(self.export_hosts)
        # Not in any menu bar menu, so their shortcuts (Ctrl+Shift+C, F5, Ctrl+N, Ctrl+M) live
        # here: toolbar menus only take keys while they're open.
        self.addActions([a.copy_address, a.refresh_shown, a.add_host, a.manual_connect])
        a.refresh_shown.triggered.connect(self._run_refresh_panel)  # F5
        a.show_domains.toggled.connect(self._show_domains)
        a.check_status.triggered.connect(
            lambda: self.check_hosts(self.selected_items(), status=True, users=False)
        )
        a.check_users.triggered.connect(
            lambda: self.check_hosts(self.selected_items(), status=False, users=True)
        )
        self.toolbar.refresh_panel_requested.connect(self._show_refresh_panel)
        self.refresh_panel.run_clicked.connect(self._run_refresh_panel)
        self.toolbar.connect_menu.aboutToShow.connect(self._fill_connect_menu)
        # Enter connects only from the host table, so it never fires while typing elsewhere.
        a.connect_host.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.connect_host)
        a.connect_host.triggered.connect(self.connect_selected)
        a.manual_connect.triggered.connect(self.manual_connect)
        a.copy_address.triggered.connect(lambda: self._copy(lambda h: h.target))
        a.connection_profiles.triggered.connect(lambda: self._shell.open_settings("connections"))
        a.saved_credentials.triggered.connect(lambda: self._shell.open_saved_credentials())
        # With no host picked, the window opens for an address typed in it.
        self.toolbar.commands_button.clicked.connect(
            lambda: self.open_commands(self.selected_target())
        )
        self.toolbar.commands_menu.aboutToShow.connect(
            lambda: self._fill_commands_menu(self.toolbar.commands_menu, window=True)
        )
        details = self.details
        details.command_clicked.connect(self.run_on_selected)
        details.session_menu_requested.connect(self._session_menu)
        details.read_facts.connect(self._read_facts_again)
        details.cancel_pending.connect(lambda: self.run_on_selected("cancel-restart"))
        details.users_menu.aboutToShow.connect(self._fill_users_menu)
        details.power_menu.aboutToShow.connect(self._fill_power_menu)
        details.more_menu.aboutToShow.connect(lambda: self._fill_commands_menu(details.more_menu))

    def restore_layout(self) -> None:
        super().restore_layout()
        check_texts.show_domains(self.commands.show_domains.isChecked())

    def view_choices(self) -> dict[str, QAction]:
        return {**super().view_choices(), "domains": self.commands.show_domains}

    def view_actions(self) -> list[list[QAction]]:
        return [*super().view_actions(), [self.commands.show_domains]]

    def save_state(self) -> None:
        super().save_state()
        if self._run is not None:
            self._run.stop()  # hosts already being read finish in the background
        self.prefs["refresh"] = self.refresh_panel.choices()

    @classmethod
    def prepare(cls, paths: settings.Paths) -> None:
        """The connection profiles every PC starts with."""
        try:
            ProfileStore(paths.profiles_dir).place_starters()
        except OSError:
            log.exception("Couldn't place the connection profiles in %s", paths.profiles_dir)

    # ---- texts ----

    def tool_name(self) -> str:
        return _("Hosts")

    def menu_name(self) -> str:
        return _("&Hosts")

    def list_texts(self) -> ListTexts:
        return ListTexts(
            kind=self.TOOL_ID,
            everything=_("All hosts"),
            lists=_("Host lists"),
            new=_("New host list"),
            add=_("Add a host list"),
            open=_("Open a host list"),
            remove=_("Remove host list"),
            manage=_("&Manage host lists…"),
            no_list=_("No host list is open."),
            choose_first=_("Open a host list to choose what it shows first."),
            not_this_kind=_("“{path}” isn't a host list."),
            file_filter=list_file_filter(),
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

    def search_fields(self) -> tuple[list[str], str]:
        """Address, user, tags: searched only while their columns show. Notes always are."""
        table = self.table
        # Each a lower-case word in the list "Search name, address, user, tags, notes".
        fields = [_("name")]
        fields += [_("address")] if not table.isColumnHidden(table.ADDRESS) else []
        fields += [_("user")] if not table.isColumnHidden(table.USER) else []
        fields += [_("tags")] if not table.isColumnHidden(table.TAGS) else []
        fields.append(_("notes"))  # no column, so always searched
        return fields, _("Searches every host in the list (Ctrl+F)")

    def selected_text(self, n: int) -> str:
        return ngettext("{n} selected", "{n} selected", n).format(n=n)

    def found_text(self, n: int) -> str:
        return ngettext("{n} found", "{n} found", n).format(n=n)

    def counted_text(self, name: str, n: int) -> str:
        return ngettext("{name} ({n} host)", "{name} ({n} hosts)", n).format(name=name, n=n)

    def selected_source_texts(self) -> tuple[str, str]:
        return _("Selected hosts"), _("the selected hosts")

    def lists_page(self) -> str:
        return "hosts"

    def only_tags_text(self, shown: int, total: int) -> str:
        return _("Only hosts with all of: {tags} · {shown} of {total} shown").format(
            tags="{tags}", shown=shown, total=total
        )

    def no_match_text(self) -> str:
        return _("No hosts in this group have all the picked tags.")

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self._retranslate_host_actions()
        self.result_strip.retranslate()
        self.toolbar.retranslate()
        self.refresh_panel.retranslate()
        self._stop_button.setText(_("Stop"))
        super().retranslate()

    # ---- adding and editing hosts ----

    def add_item_action(self) -> QAction:
        return self.commands.add_host

    def add_item(self) -> None:
        self._add_host()

    def _add_host(
        self, address: str = "", profile: str = "", parent: QWidget | None = None
    ) -> str | None:
        """Add host…, with the address and profile filled in when they're known. The new
        host's id, or None."""
        doc = self._writable()
        if doc is None:
            return None
        # Only a list with nothing in it starts with a group; any other keeps what it holds.
        base = doc.hosts if doc.hosts.groups or doc.hosts.hosts else starter_list()
        dialog = HostDialog(
            parent or self,
            base,
            default_group=self.nav.selected_group_id(),
            profiles=self._profile_picker(base),
        )
        if address:
            dialog.name.setText(address)
            dialog.address.setText(address)
            index = dialog.profile.findData(profile)
            if profile and index >= 0:
                dialog.profile.setCurrentIndex(index)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return None
        values = dialog.values()
        try:
            new, host = base.add_host(
                values.name,
                values.group,
                address=values.address,
                tags=values.tags,
                notes=values.notes,
                profile=values.profile,
            )
        except HostListRuleError as e:
            self._error(str(e))
            return None
        if not self._commit(new):
            return None
        self.table.select_ids([host.id])
        return host.id

    def edit_item(self, item: Host) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = HostDialog(self, doc.hosts, item, profiles=self._profile_picker(doc.hosts))
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
            profile=values.profile,
        )
        try:
            new = doc.hosts.update_host(edited)
        except HostListRuleError as e:
            self._error(str(e))
            return
        if edited.connect_address != item.connect_address:  # results were for the old address
            self._status_found.pop(item.id, None)
            self._users_found.pop(item.id, None)
            self._facts.pop(item.id, None)
        self._commit(new)

    def import_hosts(self) -> None:
        """Inventory > Import hosts…: many hosts at once; nothing is saved until Add."""
        doc = self._writable()
        if doc is None:
            return
        # Hosts without a group of their own get none, unless a group is picked.
        dialog = ImportDialog(self, doc.hosts, self.nav.selected_group_id() or NO_GROUP)
        new = dialog.imported_list() if run_modal(dialog) == QDialog.DialogCode.Accepted else None
        if new is not None and self._commit(new):
            added = dialog.added()
            note = ngettext("Added {n} host.", "Added {n} hosts.", added).format(n=added)
            self._shell.show_message(note, 10_000)

    def export_hosts(self) -> None:
        """The toolbar's Report: pick hosts and columns, then save a CSV file or copy the
        rows. Works on read-only lists too: it changes nothing."""
        doc = self._doc
        if doc is None or not doc.hosts.hosts:
            return
        sources, current = self.report_sources(doc.hosts)

        def results(host_id: str) -> tuple[str, str]:
            cells = self._cells(host_id)
            return cells.status[0], cells.user[0]

        def checked_at(host_id: str) -> tuple[datetime | None, datetime | None]:
            status, users = self._status_found.get(host_id), self._users_found.get(host_id)
            return (status[1] if status else None), (users[2] if users else None)

        def progress() -> tuple[int, int] | None:
            return (self._run.done, self._run.total) if self._run is not None else None

        dialog = ExportDialog(
            self,
            doc.hosts,
            sources,
            current,
            list_name=doc.path.stem,
            prefs=self.prefs,
            save_prefs=self._save_prefs,
            results=results,
            refresh=lambda hosts, status, users: self.check_hosts(
                hosts, status=status, users=users
            ),
            stop=self.stop_checks,
            progress=progress,
            checked_at=checked_at,
        )
        self.checks_changed.connect(dialog.checks_changed)
        try:
            run_modal(dialog)
        finally:
            self.checks_changed.disconnect(dialog.checks_changed)
        if dialog.outcome:
            self._shell.show_message(dialog.outcome, 10_000)

    def _copy(self, value: Callable[[Host], str]) -> None:
        hosts = self.selected_items()
        if hosts:
            QGuiApplication.clipboard().setText("\n".join(value(h) for h in hosts))

    # ---- connecting ----

    def activate_selected(self) -> None:
        self.connect_selected()

    def connect_selected(self, profile: str | None = None) -> None:
        """With the hosts' own profiles, or once with `profile` (the toolbar's Connect arrow)."""
        hosts = self.selected_items()
        if not hosts or self._doc is None:
            return
        # A name like "Ward 2A - Desk" isn't a computer name, so it can't stand in for an address.
        missing = [h for h in hosts if not h.connect_address]
        if len(hosts) == 1 and missing:
            self._ask_for_address(missing[0])
            return
        host_list = self._doc.hosts
        requests = [
            Request(
                h.name,
                Target(h.connect_address),
                profile or host_list.profile_of(h, self._profile_exists)[0],
            )
            for h in hosts
            if h.connect_address
        ]
        started = self.connector.connect(requests) if requests else 0
        if started:
            self._shell.show_message(
                ngettext("Opened {n} remote screen.", "Opened {n} remote screens.", started).format(
                    n=started
                ),
                5000,
            )
        if missing:
            names = ", ".join(h.name for h in missing[:5]) + (" …" if len(missing) > 5 else "")
            self._error(
                ngettext(
                    "{n} host has no address and was skipped: {names}",
                    "{n} hosts have no address and were skipped: {names}",
                    len(missing),
                ).format(n=len(missing), names=names)
            )

    def _ask_for_address(self, host: Host) -> None:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("No address"),
            _(
                "“{name}” has no address, and its name can't be used as one: a computer name "
                "has no spaces or symbols other than - and _."
            ).format(name=host.name),
            parent=self,
        )
        edit = box.addButton(_("&Edit host…"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(edit)
        edit.setEnabled(self._writable() is not None)
        run_modal(box)
        if box.clickedButton() is edit:
            self.edit_item(host)

    def manual_connect(self) -> None:
        """Manual connection: the Commands window, for an address typed there."""
        self.open_commands(None)

    def open_commands(self, target: HostTarget | None) -> None:
        """The Commands window, for `target` (None: an address typed there). One at a time."""
        from capypanel.ui.hosts_tool.commands_window import CommandsWindow

        if self._commands_window is not None:
            self._commands_window.close()
            self._commands_window.deleteLater()
        window = CommandsWindow(self, target, self.profile_for(target))
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        window.destroyed.connect(lambda: setattr(self, "_commands_window", None))
        self._commands_window = window
        # Over the main window, where it opened from; it isn't owned by it, so Windows wouldn't.
        window.move(self.window().frameGeometry().center() - window.rect().center())
        window.show()

    def _fill_connect_menu(self) -> None:
        """The toolbar's Connect: connect the selection, or once with another profile, then the
        connection commands that aren't about the selection."""
        a = self.commands
        menu = self.toolbar.connect_menu
        menu.clear()
        menu.addAction(a.connect_host)  # each host's own profile, as Enter does
        menu.setDefaultAction(a.connect_host)
        for profile_id, name in self.connector.choices():
            item = menu.addAction(
                _("Connect with {profile}").format(profile=name.replace("&", "&&"))
            )
            item.setEnabled(bool(self.table.selected_ids()))
            item.triggered.connect(lambda _c=False, p=profile_id: self.connect_selected(p))
        menu.addSeparator()
        menu.addActions([a.manual_connect, a.connection_profiles, a.saved_credentials])

    def _forgot(self, forget: Callable[[], object]) -> bool:
        """Runs `forget`; says so when Windows didn't delete a saved password."""
        try:
            forget()
        except OSError as e:
            forget_failed(self, e)
            return False
        return True

    # ---- saved passwords ----

    def kept_logins(self) -> list[KeptLogin]:
        """Each profile's typed password, then the account typed for logged-on users."""
        catalogs = self.connector.catalogs
        logins = []
        for profile_id, credential, saved in self.connector.credentials.kept():
            profile = catalogs.profiles.find(profile_id)
            entry = catalogs.tools.find(profile.tool) if profile else None
            logins.append(
                KeptLogin(
                    profile.name if profile else profile_id,  # a deleted profile: its id
                    entry.item.name if entry else "—",
                    credential.user or _("(password only)"),
                    saved,
                    lambda p=profile_id: self._forget_kept(p),
                )
            )
        return [*logins, *self.accounts.kept_logins()]

    def _forget_kept(self, profile_id: str) -> None:
        """One profile's password: from memory and from Credential Manager. Raises OSError."""
        try:
            self.connector.credentials.forget(profile_id)
        finally:
            self._update_state()

    def every_kept_login(self) -> list[KeptLogin]:
        """Every tool's, for Settings' Saved credentials row."""
        return self._shell.kept_logins()

    def open_saved_credentials(self, parent: QWidget) -> None:
        self._shell.open_saved_credentials(parent)

    # ---- connection profiles ----

    def _profile_picker(self, host_list: HostList) -> ProfilePicker:
        connector = self.connector
        return ProfilePicker(
            choices=connector.choices(),
            inherited=lambda group_id: connector.inherited_label(
                *host_list.group_profile(group_id or None, self._profile_exists)
            ),
            label=connector.label,
        )

    def _profile_exists(self, profile_id: str) -> bool:
        """A profile this PC has: a host or group naming another one follows its group instead."""
        return self.connector.catalogs.profiles.find(profile_id) is not None

    def _add_profile_menu(
        self, menu: QMenu, current: set[str], follow_text: str, apply: Callable[[str], None]
    ) -> None:
        """A "Connection profile" submenu: follow the group, or one of the profiles."""
        submenu = menu.addMenu(_("Connection &profile"))
        submenu.setEnabled(self._writable() is not None)
        self._fill_profile_menu(submenu, current, follow_text, apply)

    def _fill_profile_menu(
        self, submenu: QMenu, current: set[str], follow_text: str, apply: Callable[[str], None]
    ) -> None:
        exclusive = QActionGroup(submenu)
        choices = [("", follow_text), *self.connector.choices()]
        if len(current) == 1 and next(iter(current)) not in dict(choices):
            # Its own profile isn't on this PC: show it, checked, so it's clear why the group's
            # profile doesn't apply.
            own = next(iter(current))
            choices.insert(1, (own, self.connector.label(own)))
        for profile_id, text in choices:
            item = submenu.addAction(text.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current == {profile_id})  # several hosts that differ: none checked
            exclusive.addAction(item)
            item.triggered.connect(lambda _checked=False, p=profile_id: apply(p))
            if not profile_id:
                submenu.addSeparator()

    def set_group_profile(self, group_id: str, profile: str) -> None:
        doc = self._writable()
        if doc is not None and doc.hosts.group(group_id) is not None:
            self._commit(doc.hosts.set_group_profile(group_id, profile))
            self._selection_changed()

    def set_host_profile(self, host_id: str, profile: str) -> None:
        """An empty profile: the host follows its group again."""
        doc = self._writable()
        if doc is not None and doc.hosts.host(host_id) is not None:
            self._commit(doc.hosts.set_hosts_profile([host_id], profile))
            self._selection_changed()

    def _fill_details_profile_menu(self, menu: QMenu) -> None:
        """The arrow by Profile in the Details panel: the group's choices, for this host."""
        menu.clear()
        doc = self._doc
        ids = self.table.selected_ids()
        host = doc.hosts.host(ids[0]) if doc is not None and len(ids) == 1 else None
        if doc is None or host is None:
            return
        follow = self.connector.inherited_label(
            *doc.hosts.group_profile(host.group or None, self._profile_exists)
        )
        self._fill_profile_menu(
            menu, {host.profile}, follow, lambda p: self.set_host_profile(host.id, p)
        )
        for action in menu.actions():
            action.setEnabled(self._writable() is not None)

    # ---- which account commands run as: Details' arrow and the right-click menus ----

    def _host_targets(self, hosts: Sequence[Host]) -> list[HostTarget]:
        return [HostTarget(h.id, h.name, h.connect_address) for h in hosts if h.connect_address]

    def _fill_account_menu(
        self,
        menu: QMenu,
        current: set[str | None],
        follow_text: str,
        apply: Callable[[str | None], None],
        another: Callable[[], None],
    ) -> None:
        """Follow Accounts (None), your Windows account, each account in the Accounts table,
        then Another account…; `current` ticks one when every PC picked has it."""
        menu.clear()
        exclusive = QActionGroup(menu)
        mine = _("Your Windows account ({user})").format(user=windows_account())
        choices: list[tuple[str | None, str]] = [(None, follow_text), (WINDOWS, mine)]
        choices += [(user, user) for user in account_links.users(self.accounts.links)]
        for user, text in choices:
            item = menu.addAction(text.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current == {user})
            exclusive.addAction(item)
            item.triggered.connect(lambda _checked=False, u=user: apply(u))
            if user is None:
                menu.addSeparator()
        menu.addSeparator()
        menu.addAction(_("&Another account…"), another)

    def _follow_text(self, targets: Sequence[HostTarget]) -> str:
        """ "Follow Accounts", with what it gives for one PC: an account, or Windows'."""
        if len(targets) != 1:
            return _("Follow Accounts")
        own = self.accounts.own(targets[0])
        rest = [lk for lk in self.accounts.links if lk is not own]
        link = account_links.pick(rest, self.accounts.place(targets[0]))
        user = link.user if link is not None and link.user else _("your Windows account")
        return _("Follow Accounts: {user}").format(user=user)

    def _fill_hosts_account_menu(self, menu: QMenu, hosts: Sequence[Host]) -> None:
        targets = self._host_targets(hosts)
        menu.clear()
        if not targets:
            return
        current = {own.user if (own := self.accounts.own(t)) else None for t in targets}

        def another() -> None:
            account = self._ask_another(targets[0].name if len(targets) == 1 else "")
            if account is not None:
                self.accounts.set_pcs(targets, account.user)

        self._fill_account_menu(menu, current, self._follow_text(targets),
                                lambda u: self.accounts.set_pcs(targets, u), another)  # fmt: skip

    def _fill_group_account_menu(self, menu: QMenu, group: Group) -> None:
        row = self.accounts.group_row(group.id)

        def another() -> None:
            account = self._ask_another(group.name)
            if account is not None:
                self.accounts.set_group(group.id, account.user)

        current = {row.user if row else None}
        apply = lambda u: self.accounts.set_group(group.id, u)  # noqa: E731
        self._fill_account_menu(menu, current, _("Follow Accounts"), apply, another)

    def _ask_another(self, where: str) -> Account | None:
        """Another account…: the login window, for the PCs the menu was opened on."""
        text = (_("Use an account that is an administrator of {host}, such as a domain admin.")
                .format(host=where) if where else
                _("Use an account that is an administrator of these PCs, such as a domain "
                  "admin."))  # fmt: skip
        dialog = AccountDialog(self, text)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return None
        account = dialog.account()
        self.accounts.keep(account, remember=dialog.remember.isChecked())
        return account

    # ---- settings ----

    def settings_group(self) -> HostsSettings:
        return self.settings_pages

    def profiles_changed(self) -> None:
        """Settings changed the connection profiles or tool paths."""
        self._selection_changed()  # the Details panel names the profile; Connect's menu follows

    def apply_prefs(self, prefs: SettingsPrefs) -> None:
        """A choice made in Settings, kept and applied at once."""
        self.apply_list_prefs(
            prefs.start_list, prefs.start_view, prefs.added_lists, prefs.hidden_lists
        )
        on, minutes = prefs.auto_status
        self.prefs["auto_status"] = {"on": on, "minutes": minutes}
        self._apply_auto_status()
        self._save_prefs()
        self._update_state()  # the list's name may change with the lists kept

    # ---- showing ----

    def list_switched(self) -> None:
        self._status_found.clear()  # another list's hosts: old results don't apply
        self._users_found.clear()
        self._facts.clear()

    def fill_table(self, items: Sequence[Host]) -> None:
        self.table.show_hosts(items, {h.id: self._cells(h.id) for h in items})

    def matches(self, item: Host, needle: str) -> bool:
        """The name, plus the address, users and tags when their columns show: only what can be
        seen. Notes are the exception: they have no column, so they're always searched. Users
        come from the last logged-on users check (memory only)."""
        table = self.table
        if super().matches(item, needle):
            return True
        if not table.isColumnHidden(table.ADDRESS) and needle in item.address.casefold():
            return True
        if not table.isColumnHidden(table.TAGS) and any(needle in t.casefold() for t in item.tags):
            return True
        if table.isColumnHidden(table.USER):
            return False
        sessions = (self._users_found.get(item.id) or ((), None, None))[0] or ()
        return any(needle in check_texts.user_name(s).casefold() for s in sessions)

    def _show_domains(self, shown: bool) -> None:
        check_texts.show_domains(shown)
        self._show_items()  # the User column, the search and the Details panel

    def show_details(self, items: Sequence[Host]) -> None:
        if len(items) == 1 and self._doc is not None:
            host_list, host = self._doc.hosts, items[0]
            status = self._status_found.get(host.id)
            details = HostDetails(
                host,
                group_path(host_list, host.group),
                self.connector.label(host_list.profile_of(host, self._profile_exists)[0]),
                status=(status[0], status[1]) if status else None,
                users=self._users_found.get(host.id),
                facts=self._facts.get(host.id),
                pending=self._pending.get(host.id),
                profile_user=self._profile_user(
                    host_list.profile_of(host, self._profile_exists)[0]
                ),
                commands_as=self._commands_as(host),
            )
            self.details.show_host(details, 1, needle=self._needle())
            if host.connect_address and host.id not in self._facts:
                self._facts_timer.start()  # read once it stays selected a moment
        else:
            self.details.show_host(None, len(items), summary=self._summary())

    def _profile_user(self, profile_id: str) -> str:
        """The login kept for a profile (typed this session or saved); "" when none is."""
        try:
            kept = self.connector.credentials.get(profile_id or self._default_profile())
        except OSError:
            return ""
        return kept.user if kept is not None else ""

    def _default_profile(self) -> str:
        return self.connector.catalogs.profiles.default_id()

    def _commands_as(self, host: Host) -> tuple[str, bool, str]:
        """Details' Commands run as: the account, whether this PC overrides its group (its own
        Accounts row), and why that one."""
        used = _("Used for Refresh's logged-on users and the commands run on this PC, not for "
                 "Connect.")  # fmt: skip
        link = self.accounts.link_for(HostTarget(host.id, host.name, host.connect_address))
        if link is None:
            why = _("No row of Settings › Hosts › Credentials names this PC, so it's "
                    "the Windows account you're signed in with.")  # fmt: skip
            return windows_account(), False, f"{used}\n{why}"
        own = link.scope is Scope.PC
        where = _("Settings › Hosts › Credentials: {uses}").format(uses=used_for(link, self._doc))
        user = windows_account() if link.user == WINDOWS else link.user
        return user, own, f"{used}\n{where}"

    def _summary(self) -> str:
        """With nothing selected, the Details panel sums up the hosts shown."""
        items = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        shown = [item.data(0, ROLE_ID) for item in items if item is not None]
        if not shown:
            return ""
        counts: dict[Status | None, int] = {}
        for host_id in shown:
            state = found[0] if (found := self._status_found.get(host_id)) else None
            counts[state] = counts.get(state, 0) + 1
        lines = [ngettext("{n} host shown", "{n} hosts shown", len(shown)).format(n=len(shown))]
        texts: tuple[tuple[Status | None, Callable[[int], str]], ...] = (
            (Status.ONLINE, lambda n: ngettext("{n} online", "{n} online", n)),
            (Status.OFFLINE, lambda n: ngettext("{n} offline", "{n} offline", n)),
            (Status.NOT_FOUND, lambda n: ngettext("{n} not found", "{n} not found", n)),
            (None, lambda n: ngettext("{n} not checked", "{n} not checked", n)),
        )  # literal texts, so the translation script finds them
        for state, text in texts:
            if n := counts.get(state, 0):
                lines.append(text(n).format(n=n))
        return "\n".join(lines)

    def update_tool_state(self, writable: bool, selected: int) -> None:
        doc = self._doc
        a = self.commands
        a.add_host.setEnabled(writable)
        a.import_hosts.setEnabled(writable)
        a.export_hosts.setEnabled(doc is not None and bool(doc.hosts.hosts))  # read-only too
        for action in (a.connect_host, a.copy_address):
            action.setEnabled(selected > 0)  # read-only lists can still connect
        for action in (a.check_status, a.check_users):
            action.setEnabled(selected > 0 and self._run is None)  # one Refresh at a time
        self._update_host_actions()
        shown = self.table.topLevelItemCount() > 0
        a.refresh_shown.setEnabled(shown and self._run is None)
        self.toolbar.refresh_button.setEnabled(shown and self._run is None)

    def status_extras(self, doc: OpenList) -> list[str]:
        # Hosts still in the list: a removed host's result stays in memory.
        if not self._status_found:  # once anything was checked; results are this list's only
            return []
        found = (self._status_found.get(h.id) for h in doc.hosts.hosts)
        online = sum(1 for f in found if f is not None and f[0] is Status.ONLINE)
        return [ngettext("{n} online", "{n} online", online).format(n=online)]

    # ---- right-click menus ----

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None  # keeps Ctrl+Shift+C

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        a = self.commands
        # Use first, then copy, then managing the host: edit, move, remove.
        menu.addAction(a.connect_host)
        menu.setDefaultAction(a.connect_host)  # bold: what double-click and Enter do
        menu.addSeparator()
        menu.addActions([a.check_status, a.check_users])
        menu.addSeparator()
        self._add_command_menus(menu)
        account = menu.addMenu(_("Commands run &as"))  # this person's own rows: never read-only
        self._fill_hosts_account_menu(account, items)
        account.setEnabled(bool(account.actions()))
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        assert self._doc is not None
        menu.addSeparator()
        follow = self.connector.inherited_label(
            *self._doc.hosts.group_profile(group.parent, self._profile_exists)
        )
        self._add_profile_menu(
            menu, {group.profile}, follow, lambda p: self.set_group_profile(group.id, p)
        )
        self._fill_group_account_menu(menu.addMenu(_("Commands run &as")), group)
        # The group's hosts, including those in the groups inside it.
        hosts = list(self._doc.hosts.hosts_in(group.id))
        menu.addSeparator()
        for text, status, users in (
            (_("Refresh &status"), True, False),
            (_("Refresh &logged-on users"), False, True),
        ):
            item = menu.addAction(text)
            item.setEnabled(bool(hosts) and self._run is None)
            item.triggered.connect(
                lambda _c=False, s=status, u=users: self.check_hosts(hosts, status=s, users=u)
            )

    # ---- Refresh: status and logged-on users ----

    def check_hosts(self, hosts: Sequence[Host], *, status: bool, users: bool) -> None:
        if self._run is not None or not (status or users):
            return
        targets = [(h.id, h.connect_address) for h in hosts if h.connect_address]
        skipped = len(hosts) - len(targets)
        if skipped:
            note = ngettext(
                "{n} host has no address and was skipped.",
                "{n} hosts have no address and were skipped.",
                skipped,
            )
            self._shell.show_message(note.format(n=skipped), 10_000)
        if (
            users
            and len(targets) > MANY_USER_CHECKS
            and not confirm(
                self,
                _("Refresh logged-on users"),
                _("Check who is logged on to {n} hosts?").format(n=len(targets)),
                _("Refresh"),
            )
        ):
            return
        accounts = self._accounts_of(targets) if users and targets else {}
        if targets and accounts is not None:
            self._start(targets, Checks(status, users, self._ports()), accounts)

    def checking(self) -> bool:
        """A Refresh is running (another one waits for it to end)."""
        return self._run is not None

    def check_progress(self) -> tuple[int, int] | None:
        """(hosts checked so far, hosts to check) while a Refresh runs."""
        return (self._run.done, self._run.total) if self._run is not None else None

    def auto_status(self) -> tuple[bool, int]:
        saved = self.prefs.get("auto_status")
        saved = saved if isinstance(saved, dict) else {}
        minutes = saved.get("minutes", 5)
        minutes = minutes if isinstance(minutes, int) and 1 <= minutes <= 120 else 5
        return saved.get("on") is True, minutes

    def _apply_auto_status(self) -> None:
        on, minutes = self.auto_status()
        if on:
            self._auto_timer.start(minutes * 60_000)
        else:
            self._auto_timer.stop()

    def _auto_status_check(self) -> None:
        """Status only (ping and ports) on the hosts shown; skipped while a Refresh runs."""
        hosts = self.visible_items()
        if self._run is None and hosts:
            self.check_hosts(hosts, status=True, users=False)

    def _accounts_of(self, targets: Sequence[tuple[str, str]]) -> dict[str, Account | None] | None:
        """Each host's account; a password not typed yet is asked first. None: cancelled."""
        found: dict[str, Account | None] = {}
        for key, address in targets:
            go, account = self.accounts.account_for(self._target(key, address), self)
            if not go:
                return None
            found[key] = account
        return found

    def _target(self, key: str, address: str) -> HostTarget:
        host = self._doc.hosts.host(key) if self._doc else None
        return HostTarget(key, host.name if host else address, address)

    def _start(
        self,
        targets: list[tuple[str, str]],
        wanted: Checks,
        accounts: dict[str, Account | None] | None = None,
    ) -> None:
        accounts = accounts or {}
        run = CheckRun(targets, wanted, accounts.get)
        run.found.connect(self._found)
        run.finished.connect(self._run_finished)
        self._run, self._refused, self._reported = run, [], set()
        self._targets = targets
        self._show_progress()
        self._stop_button.setEnabled(True)
        self._update_state()
        self.checks_changed.emit()
        log.info(
            "Refresh: %d hosts (status=%s, users=%s, typed accounts=%d)",
            len(targets), wanted.status, wanted.users, len({a for a in accounts.values() if a}),
        )  # fmt: skip
        run.start()

    def stop_checks(self) -> None:
        if self._run is not None:
            self._run.stop()
            self._stop_button.setEnabled(False)  # hosts already being read still finish

    def _found(self, host_id: str, found: Found) -> None:
        run = self._run
        if run is None:
            return
        run.done += 1
        self._reported.add(host_id)
        if found.status is not None:
            self._status_found[host_id] = (found.status, found.when, found.answered)
        if run.wanted.users and (found.sessions is not None or found.users_error is not None):
            self._users_found[host_id] = (found.sessions, found.users_error, found.when)
            error = found.users_error
            if error is not None and error.reason in (Reason.NOT_ADMIN, Reason.REJECTED):
                self._refused.append(host_id)
        self.table.show_cells(host_id, self._cells(host_id))
        self.host_changed.emit(host_id)
        if self.table.selected_ids() in ([host_id], []):  # its details, or the summary
            self._selection_changed()
        else:
            self._update_state()  # the online count
        self._show_progress()
        self.checks_changed.emit()

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
        if run.wanted.users and (self._refused or run.halted):
            self._ask_account(run)

    def _ask_account(self, run: CheckRun) -> None:
        """A host didn't let its account read who is logged on: offer another, once per run,
        and the PCs to use it for."""
        rejected = run.rejected[-1] if run.rejected else None
        account = rejected or next((a for a in map(run.account_of, self._refused) if a), None)
        first = self._name_of(self._refused[-1]) if self._refused else ""
        if rejected is not None:
            first = next((self._name_of(k) for k in reversed(self._refused)
                          if run.account_of(k) == rejected), first)  # fmt: skip
            text = _(
                "“{host}” rejected the account “{user}”, so CapyPanel stopped before trying it "
                "on other computers. Type the password again, or use another account."
            ).format(host=first, user=rejected.user)
        elif account is None:
            text = ngettext(
                "{n} computer didn't let your Windows account see who is logged on. Use another "
                "account, such as an administrator of those computers?",
                "{n} computers didn't let your Windows account see who is logged on. Use another "
                "account, such as an administrator of those computers?",
                len(self._refused),
            ).format(n=len(self._refused))
        else:
            text = ngettext(
                "{n} computer didn't let “{user}” see who is logged on. Use another account?",
                "{n} computers didn't let “{user}” see who is logged on. Use another account?",
                len(self._refused),
            ).format(n=len(self._refused), user=account.user)
        # Again: the hosts that refused, and those a rejection kept from being tried.
        again = [t for t in self._targets if t[0] in self._refused or t[0] not in self._reported]
        uses = self.accounts.uses_for([self._target(*t) for t in again or self._targets])
        dialog = AccountDialog(self, text, account.user if account else "",
                               uses=uses)  # fmt: skip
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        link = dialog.link()
        assert link is not None  # "Every PC" at least
        self.accounts.use(link, dialog.account(), remember=dialog.remember.isChecked())
        accounts = self._accounts_of(again) if again else None
        if accounts is not None:
            self._start(again, Checks(False, True, run.wanted.ports), accounts)

    def _name_of(self, host_id: str) -> str:
        host = self._doc.hosts.host(host_id) if self._doc else None
        return host.name if host else host_id

    def _ports(self) -> tuple[int, ...]:
        """The ports CapyPanel's tools connect to: one answering proves the computer is on."""
        return checks.tool_ports(e.item.port for e in self.connector.catalogs.tools.all())

    def _cells(self, host_id: str) -> Cells:
        status = self._status_found.get(host_id)
        users = self._users_found.get(host_id)
        unchecked = ("", _("Not checked: use Refresh"), None, True)
        status_cell: tuple[str, str, Any, bool] = unchecked
        if status is not None:
            state, when, answered = status
            status_cell = (
                check_texts.status_text(state),
                check_texts.status_tip(state, when, answered),
                dot_icon(STATUS_COLORS[state]),
                state is not Status.ONLINE,
            )
        pending = self._pending.get(host_id)
        if pending is not None and pending.at > datetime.now(UTC):
            when = check_texts.clock_text(pending.at)
            status_cell = (
                _("Restart at {when}").format(when=when)
                if pending.restart
                else _("Shutdown at {when}").format(when=when),
                _("CapyPanel asked for it at {when}.").format(
                    when=check_texts.clock_text(pending.asked)
                ),
                tabler_icon("clock", QColor(STATUS_COLORS["attention"]), 14),
                False,
            )
        user_cell: tuple[str, str, Any, bool] = unchecked
        if users is not None:
            found, error, when = users
            text, tip = check_texts.users_text(found, error), check_texts.users_tip(error, when)
            if found:  # every name, when the column is too narrow; always with the domain
                tip = f"{check_texts.users_text(found, error, full=True)}\n{tip}"
            user_cell = (text, tip, None, error is not None or not found)
        return Cells(status_cell, user_cell)

    def _show_refresh_panel(self, where: QPoint) -> None:
        panel = self.refresh_panel
        panel.run_button.setEnabled(self._run is None)
        panel.adjustSize()
        panel.move(where)
        panel.show()

    def _run_refresh_panel(self) -> None:
        choices = self.refresh_panel.choices()
        self.prefs["refresh"] = choices
        self._save_prefs()
        self.check_hosts(self.visible_items(), status=choices["status"], users=choices["users"])

    # ---- host commands ----

    def _make_host_actions(self) -> dict[str, QAction]:
        """One action per command in the lists (not the per-person ones), shared by the host
        menu, Commands ▾ and the Details panel's … button."""
        made = {}
        for command in host_commands.COMMANDS:
            if command.per_person:
                continue
            action = QAction(self)
            if command.id in COMMAND_SHORTCUTS:
                action.setShortcut(QKeySequence(COMMAND_SHORTCUTS[command.id]))
            action.triggered.connect(lambda _c=False, c=command.id: self.run_on_selected(c))
            made[command.id] = action
        self.addActions(list(made.values()))  # their shortcuts work while Hosts shows
        self._retranslate_host_actions(made)
        return made

    def _retranslate_host_actions(self, actions: dict[str, QAction] | None = None) -> None:
        for command_id, action in (actions or self.host_actions).items():
            command = host_commands.command(command_id)
            action.setText(_(command.name).replace("&", "&&"))
            action.setToolTip(_(command.description))
            action.setStatusTip(_(command.description))

    def _update_host_actions(self) -> None:
        """A command needs one host with an address; Cancel the pending restart, one waiting."""
        target = self.selected_target()
        for command_id, action in self.host_actions.items():
            enabled = target is not None
            if command_id == "cancel-restart":
                enabled = enabled and target is not None and target.key in self._pending
            action.setEnabled(enabled)
        if target is not None:
            who = folder_user(self._known_sessions(target.key))
            name = _("{user}'s folder").format(user=who.user) if who else _("User's folder")
            self.host_actions["user-folder"].setText(name.replace("&", "&&"))

    def selected_target(self) -> HostTarget | None:
        hosts = self.selected_items()
        if len(hosts) != 1 or not hosts[0].connect_address:
            return None
        host = hosts[0]
        return HostTarget(host.id, host.name, host.connect_address)

    def run_on_selected(self, command_id: str) -> None:
        target = self.selected_target()
        if target is not None:
            self.runner.run(command_id, target, self.show_outcome)

    def show_outcome(self, _command_id: str, outcome: Outcome) -> None:
        if outcome.running:  # the answer comes later; meanwhile a line in the status bar
            self.say(html.unescape(re.sub(r"<[^>]+>", "", outcome.text)))
            return
        self.result_strip.show_outcome(outcome)

    def save_prefs(self) -> None:
        self._save_prefs()

    def open_settings(self, page: str) -> None:
        self._shell.open_settings(page)

    def _add_command_menus(self, menu: QMenu) -> None:
        """Check ▸, Folders ▸… Power ▸ with the selected host's commands, in the list's groups;
        a line before each command set apart."""
        self._update_host_actions()
        target = self.selected_target()
        for group in CommandGroup:
            submenu = menu.addMenu(_(GROUP_NAMES[group]))
            for command in host_commands.in_group(group):
                if command.apart:
                    submenu.addSeparator()
                submenu.addAction(self.host_actions[command.id])
            submenu.setEnabled(target is not None)

    def _fill_commands_menu(self, menu: QMenu, *, window: bool = False) -> None:
        """Commands ▾ and the Details panel's …: every command, by group; Commands ▾ ends with
        All commands…, the Commands window (`window`)."""
        menu.clear()
        self._add_command_menus(menu)
        if window:
            menu.addSeparator()
            every = menu.addAction(_("&All commands…"))
            every.setEnabled(self.selected_target() is not None)
            every.triggered.connect(lambda: self.open_commands(self.selected_target()))

    def _known_sessions(self, key: str) -> tuple[Session, ...]:
        found = self._users_found.get(key)
        return tuple(found[0] or ()) if found is not None else ()

    def _fill_users_menu(self) -> None:
        """Users ▾: each person signed in as a heading, then Log off… and Disconnect…"""
        menu = self.details.users_menu
        menu.clear()
        target = self.selected_target()
        if target is None:
            return
        amber = QColor(STATUS_COLORS["attention"])
        from capypanel.ui.hosts_tool.command_windows import where_text

        for index, session in enumerate(check_texts.by_state(self._known_sessions(target.key))):
            if index:
                menu.addSeparator()
            heading = menu.addAction(f"{session.user}  ({where_text(session)})")
            heading.setEnabled(False)
            for command_id, text, icon in (
                ("log-off", _("Log off {user}…"), "logout"),
                ("disconnect", _("Disconnect {user}…"), "plug-connected-x"),
            ):
                item = menu.addAction(
                    tabler_icon(icon, amber), text.format(user=session.user).replace("&", "&&")
                )
                item.triggered.connect(
                    lambda _c=False, c=command_id, s=session: self.runner.run(
                        c, target, self.show_outcome, session=s
                    )
                )

    def _fill_power_menu(self) -> None:
        """Power ▾: Restart…, Shut down…, then Cancel the pending restart."""
        menu = self.details.power_menu
        menu.clear()
        self._update_host_actions()
        amber = QColor(STATUS_COLORS["attention"])
        text = self.palette().color(self.foregroundRole())
        for command_id, color in (("restart", amber), ("shut-down", amber),
                                  ("cancel-restart", text)):  # fmt: skip
            if command_id == "cancel-restart":
                menu.addSeparator()
            action = self.host_actions[command_id]
            item = menu.addAction(
                tabler_icon(host_commands.command(command_id).icon, color), action.text()
            )
            item.setEnabled(action.isEnabled())
            item.triggered.connect(action.trigger)

    def _session_menu(self, session: Session, where: QPoint) -> None:
        target = self.selected_target()
        if target is not None:
            self.session_menu(session, where, target, self.show_outcome)

    def session_menu(
        self,
        session: Session,
        where: QPoint,
        target: HostTarget,
        report: Report,
        parent: QWidget | None = None,
    ) -> None:
        """A right-click on a person: message, disconnect or log them off, then Copy."""
        menu = QMenu(parent or self)
        name = session.user.replace("&", "&&")
        for command_id, text in (
            ("message", _("Send a message to {user}…")),
            (None, ""),
            ("disconnect", _("Disconnect {user}…")),
            ("log-off", _("Log off {user}…")),
        ):
            if command_id is None:
                menu.addSeparator()
                continue
            item = menu.addAction(text.format(user=name))
            item.triggered.connect(
                lambda _c=False, c=command_id: self.runner.run(
                    c, target, report, parent=parent, session=session
                )
            )
        if parent is None:  # the host's columns: only from the host's own Details
            menu.addSeparator()
            self.add_copy_menu(menu)
        menu.exec(where)

    # ---- what the commands keep ----

    def status_found(self, key: str) -> tuple[Status, datetime] | None:
        found = self._status_found.get(key)
        return (found[0], found[1]) if found is not None else None

    def profile_for(self, target: HostTarget | None) -> str:
        """The connection profile a host of the list uses; the default one for a typed address."""
        if target is not None and self._doc is not None:
            host = self._doc.hosts.host(target.key)
            if host is not None:
                return self._doc.hosts.profile_of(host, self._profile_exists)[0]
        return self.connector.default_profile()

    def host_choices(self) -> list[HostTarget]:
        """The Commands window's host list: what the Hosts panel shows, in its order."""
        return self._host_targets(self.table.in_shown_order(self.visible_items()))

    def host_named(self, typed: str) -> HostTarget | None:
        """The open list's host with that name or address, as typed in the Commands window."""
        wanted = typed.strip().casefold()
        hosts = self._doc.hosts.hosts if self._doc is not None else ()
        found = next((h for h in hosts if h.connect_address and wanted in
                      (h.name.casefold(), h.connect_address.casefold())), None)  # fmt: skip
        return self._host_targets([found])[0] if found is not None else None

    def recent_addresses(self) -> list[str]:
        saved = self.prefs.get("recent_addresses")
        return [a for a in saved if isinstance(a, str)] if isinstance(saved, list) else []

    def remember_address(self, typed: str) -> None:
        kept = [typed, *(a for a in self.recent_addresses() if a.casefold() != typed.casefold())]
        self.prefs["recent_addresses"] = kept[:RECENT_PATHS]
        self._save_prefs()

    def where_in_list(self, address: str) -> list[tuple[str, str]]:
        """Each host of the open list reached at `address`: its group's path and its name."""
        doc = self._doc
        if doc is None:
            return []
        wanted = address.strip().casefold()
        return [
            (group_path(doc.hosts, h.group), h.name)
            for h in doc.hosts.hosts
            if h.connect_address.casefold() == wanted
        ]

    def can_add_hosts(self) -> bool:
        return self._doc is not None and not self._doc.read_only

    def add_typed_host(self, address: str, profile: str) -> str | None:
        """Add to list…: Add host… with the address typed in the Commands window."""
        return self._add_host(address, profile, parent=self._commands_window)

    def keep_pref(self, key: str, value: object) -> None:
        """One of this person's own settings, written at once (the accounts' links)."""
        self.prefs[key] = value
        self._save_prefs()

    def _accounts_changed(self) -> None:
        """Details says which account signs in; Settings' Saved credentials row counts them."""
        self._update_state()
        if len(self.selected_items()) == 1:
            self._selection_changed()

    def users_found(
        self, key: str
    ) -> tuple[tuple[Session, ...] | None, RemoteError | None, datetime] | None:
        return self._users_found.get(key)

    def keep_users(
        self, key: str, found: tuple[Session, ...] | None, error: RemoteError | None
    ) -> None:
        self._users_found[key] = (found, error, datetime.now(UTC))
        self._result_changed(key)

    def check_target(
        self, target: HostTarget, *, status: bool, users: bool, report: Report | None
    ) -> None:
        """Refresh's checks on one PC of the list, or a typed address."""
        if self._run is not None:
            if report is not None:
                report(
                    "status" if status else "users",
                    Outcome(
                        _("A Refresh is running. Try again once it ends."), RuntimeError("busy")
                    ),  # fmt: skip
                )
            return
        targets = [(target.key, target.address)]
        accounts = self._accounts_of(targets) if users else {}
        if accounts is not None:
            self._start(targets, Checks(status, users, self._ports()), accounts)

    def say(self, text: str) -> None:
        self._shell.show_message(text, 5000)

    def recent_paths(self) -> list[str]:
        saved = self.prefs.get("recent_paths")
        return [p for p in saved if isinstance(p, str)] if isinstance(saved, list) else []

    def remember_path(self, typed: str) -> None:
        kept = [typed, *(p for p in self.recent_paths() if p.casefold() != typed.casefold())]
        self.prefs["recent_paths"] = kept[:RECENT_PATHS]
        self._save_prefs()

    def csv_folder(self, folder: str | None) -> str:
        """Where Installed programs last saved a CSV file; `folder` keeps a new one."""
        if folder is not None:
            self.prefs["programs_folder"] = folder
            self._save_prefs()
            return folder
        saved = self.prefs.get("programs_folder")
        return saved if isinstance(saved, str) else ""

    def facts_reading(self, key: str) -> None:
        self._facts[key] = Facts(when=datetime.now(UTC))

    def keep_facts(
        self,
        key: str,
        *,
        quick: tuple[Any, datetime] | None = None,
        quick_error: BaseException | None = None,
        slow: Any = None,
        slow_error: BaseException | None = None,
    ) -> None:
        facts = self._facts.get(key) or Facts(when=datetime.now(UTC))
        if quick is not None:
            facts = replace(facts, space=quick[0], restarted=quick[1])
        if quick_error is not None:
            facts = replace(facts, quick_error=quick_error)
        if slow is not None:
            facts = replace(facts, pc=slow)
        if slow_error is not None:
            facts = replace(facts, pc_error=slow_error)
        waiting = (facts.space is None and facts.quick_error is None) or (
            facts.pc is None and facts.pc_error is None
        )
        self._facts[key] = replace(facts, reading=waiting, when=datetime.now(UTC))

    def facts_of(self, key: str) -> Facts | None:
        return self._facts.get(key)

    def _facts_changed(self, key: str) -> None:
        self._result_changed(key)

    def _result_changed(self, key: str) -> None:
        """New results for one host: its row, and Details if it's the one shown."""
        self.table.show_cells(key, self._cells(key))
        if self.table.selected_ids() == [key]:
            self._selection_changed()
        self.host_changed.emit(key)

    def _read_shown_facts(self) -> None:
        """PC facts are read once, when a host has stayed selected a moment (never on Refresh:
        no extra load on PCs nobody looks at)."""
        target = self.selected_target()
        if target is not None and target.key not in self._facts:
            self.runner.read_facts(target)

    def _read_facts_again(self) -> None:
        target = self.selected_target()
        if target is not None:
            self.runner.read_facts(target)

    # ---- a restart or shutdown that's waiting ----

    def power_started(
        self,
        target: HostTarget,
        *,
        restart: bool,
        at: datetime,
        asked: datetime,
        told: Sequence[str],
    ) -> None:
        self._pending[target.key] = PendingPower(
            restart, at, asked, tuple(told), name=target.name, address=target.address
        )
        if restart:
            self._watch.start()  # until it's back online
        # When the time comes, the Status column and Details stop showing it as waiting.
        wait = max(0, int((at - datetime.now(UTC)).total_seconds() * 1000)) + 500
        QTimer.singleShot(wait, self, lambda: self._power_time(target.key))
        self._result_changed(target.key)

    def _power_time(self, key: str) -> None:
        pending = self._pending.get(key)
        if pending is not None and not pending.restart:
            self._pending.pop(key)  # a PC that shut down stays off: nothing to watch
        self._result_changed(key)

    def power_cancelled(self, target: HostTarget) -> None:
        if self._pending.pop(target.key, None) is not None:
            self._result_changed(target.key)

    def pending_power(self, key: str) -> PendingPower | None:
        return self._pending.get(key)

    def _watch_power(self) -> None:
        """Every few seconds while a restart is on its way: once its time has come, whether the
        PC answers on file sharing; when it went away and answers again, it's back online."""
        now = datetime.now(UTC)
        for key, pending in list(self._pending.items()):
            if now < pending.at:
                continue
            if not pending.restart:
                continue
            if now > pending.at + WATCH_FOR:
                self._pending.pop(key)  # it never came back: no notification
                self._result_changed(key)
                continue
            if key not in self._probing:
                self._probe(key, pending)
        if not any(p.restart for p in self._pending.values()):
            self._watch.stop()

    def _probe(self, key: str, pending: PendingPower) -> None:
        self._probing.add(key)

        def answered(_value: object) -> None:
            self._probing.discard(key)
            if self._pending.get(key) is not pending:
                return  # cancelled, or asked again, meanwhile
            if pending.went_down:
                self._pending.pop(key)
                self._back(key, pending)
            self._result_changed(key)

        def silent(_error: BaseException) -> None:
            self._probing.discard(key)
            if self._pending.get(key) is pending:
                self._pending[key] = replace(pending, went_down=True)

        self.runner.call(lambda _account: access.check_reachable(pending.address),
                         answered, silent)  # fmt: skip

    def _back(self, key: str, pending: PendingPower) -> None:
        """A Windows notification: a click on it shows the host."""
        self._back_online = key
        self.notify_requested.emit(
            _("{host} is back online").format(host=pending.name),
            _("It restarted at {at} and answered again at {now}. Click to show it.").format(
                at=check_texts.clock_text(pending.at),
                now=check_texts.clock_text(datetime.now(UTC)),
            ),
        )

    def show_attention(self) -> None:
        """A click on "back online": that host, if it's in the list shown."""
        if self._back_online is not None:
            self.table.select_ids([self._back_online])
