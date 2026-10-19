"""The Hosts tool: the list workspace with hosts, plus connecting, connection profiles, Refresh
(status and logged-on users), importing and Report."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QMenu, QMessageBox, QToolButton, QWidget

from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import checks
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import Answer, Status
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.connect import SessionCredentials, Target
from capypanel.ui import checks as check_texts
from capypanel.ui.checks import AccountDialog, CheckRun
from capypanel.ui.connect import Connector, ManualConnectDialog, Request
from capypanel.ui.dialogs import run_modal
from capypanel.ui.export_hosts import ExportDialog, Source
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.hosts import HostDialog, ProfilePicker, confirm, group_path
from capypanel.ui.hosts_tool.actions import create_actions, retranslate_actions
from capypanel.ui.hosts_tool.details import HostDetails, HostDetailsPanel
from capypanel.ui.hosts_tool.table import Cells, HostTable
from capypanel.ui.hosts_tool.toolbar import HostsToolBar, RefreshPanel
from capypanel.ui.icons import STATUS_COLORS, dot_icon
from capypanel.ui.import_hosts import ImportDialog
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.settings.window import SettingsDialog, SettingsPrefs

log = logging.getLogger(__name__)
MANY_USER_CHECKS = 50  # reading logged-on users on more hosts than this asks first


class HostsTool(ListWorkspace):
    checks_changed = Signal()  # a Refresh started, found something, or ended

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
        self.connector = Connector(self, Catalogs.for_paths(shell.paths), SessionCredentials())
        self.connector.open_settings = lambda: self._shell.open_settings("connections")

        # Refresh results, by host id: in memory only, since the list file is shared.
        self._status_found: dict[str, tuple[Status, datetime, Answer | None]] = {}
        self._users_found: dict[
            str, tuple[tuple[Session, ...] | None, SessionsError | None, datetime]
        ] = {}
        self._run: CheckRun | None = None
        self._account: Account | None = None  # typed for logged-on users; memory only
        self._refused: list[str] = []  # hosts this run that didn't let the account read users
        self._reported: set[str] = set()
        self._targets: list[tuple[str, str]] = []

        self.refresh_panel = RefreshPanel(self)
        self.refresh_panel.set_choices(self._prefs.get("refresh"))
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.setText(_("Stop"))
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self._auto_timer = QTimer(self)  # Settings: Status by itself, if switched on
        self._auto_timer.timeout.connect(self._auto_status_check)
        self._apply_auto_status()
        self.open_startup_list()
        self.refresh()

    def status_widgets(self) -> list[QWidget]:
        """Shown on the right of the status bar: a Refresh's progress and Stop."""
        return [self._progress, self._stop_button]

    def _fill_inventory(self) -> None:
        a = self.commands
        inventory = self.toolbar.inventory_menu
        inventory.addActions([a.add_host, a.add_group, a.manage_groups])
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
        self.toolbar.refresh_requested.connect(self._refresh_shown)
        self.refresh_panel.run_clicked.connect(self._run_refresh_panel)
        self.toolbar.connect_menu.aboutToShow.connect(self._fill_connect_menu)
        # Enter connects only from the host table, so it never fires while typing elsewhere.
        a.connect_host.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.connect_host)
        a.connect_host.triggered.connect(self.connect_selected)
        a.manual_connect.triggered.connect(self.manual_connect)
        a.copy_address.triggered.connect(lambda: self._copy(lambda h: h.target))
        a.forget_passwords.triggered.connect(self.forget_passwords)
        a.connection_profiles.triggered.connect(lambda: self._shell.open_settings("connections"))

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
        self._prefs["refresh"] = self.refresh_panel.choices()

    # ---- texts ----

    def all_items_text(self) -> str:
        return _("All hosts")

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

    def no_list_text(self) -> str:
        return _("No host list is open.")

    def open_list_title(self) -> str:
        return _("Open a host list")

    def manage_lists_text(self) -> str:
        return _("&Manage host lists…")

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

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self.toolbar.retranslate()
        self.refresh_panel.retranslate()
        self._stop_button.setText(_("Stop"))
        super().retranslate()

    # ---- adding and editing hosts ----

    def add_item_action(self) -> QAction:
        return self.commands.add_host

    def add_item(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        base = doc.hosts if doc.hosts.groups else starter_list()
        dialog = HostDialog(
            self,
            base,
            default_group=self.nav.selected_group_id(),
            profiles=self._profile_picker(base),
        )
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
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
            return
        if self._commit(new):
            self.table.select_ids([host.id])

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
        sources, current = self._export_sources(doc.hosts)

        def results(host_id: str) -> tuple[str, str]:
            cells = self._cells(host_id)
            return cells.status[0], cells.user[0]

        def progress() -> tuple[int, int] | None:
            return (self._run.done, self._run.total) if self._run is not None else None

        dialog = ExportDialog(
            self,
            doc.hosts,
            sources,
            current,
            list_name=doc.path.stem,
            prefs=self._prefs,
            save_prefs=self._save_prefs,
            results=results,
            refresh=lambda hosts, status, users: self.check_hosts(
                hosts, status=status, users=users
            ),
            stop=self.stop_checks,
            progress=progress,
        )
        self.checks_changed.connect(dialog.checks_changed)
        try:
            run_modal(dialog)
        finally:
            self.checks_changed.disconnect(dialog.checks_changed)
        if dialog.outcome:
            self._shell.show_message(dialog.outcome, 10_000)

    def _export_sources(self, host_list: HostList) -> tuple[list[Source], int]:
        """What can be exported, and which one is shown now: the search's results, the hosts
        picked, everything, no group, each group (with its subgroups) and each tag."""

        def counted(name: str, n: int) -> str:
            return ngettext("{name} ({n} host)", "{name} ({n} hosts)", n).format(name=name, n=n)

        sources: list[Source] = []
        current = self.nav.current_filter()
        start = 0
        if self._needle():
            found = self.visible_items()
            sources.append(Source(counted(_("Search results"), len(found)),
                                  _("the search results"), found))  # fmt: skip
        selected = self.selected_items()
        if len(selected) > 1:
            picked = tuple(selected)
            sources.append(Source(counted(_("Selected hosts"), len(picked)),
                                  _("the selected hosts"), picked))  # fmt: skip
        every = host_list.hosts
        sources.append(Source(counted(_("All hosts"), len(every)), _("All hosts"), every))
        if not self._needle() and current.kind == "all":
            start = len(sources) - 1
        loose = tuple(h for h in every if h.group == NO_GROUP)
        sources.append(Source(counted(_("No group"), len(loose)), _("No group"), loose))
        if not self._needle() and current.kind == "nogroup":
            start = len(sources) - 1

        def visit(parent: str | None, depth: int) -> None:
            nonlocal start
            for group in host_list.children(parent):
                hosts = host_list.hosts_in(group.id)
                sources.append(Source(counted(group.name, len(hosts)), group.name, hosts, depth))
                if not self._needle() and current.kind == "group" and current.value == group.id:
                    start = len(sources) - 1
                visit(group.id, depth + 1)

        visit(None, 0)
        for tag in sorted(host_list.all_tags(), key=str.casefold):
            hosts = tuple(h for h in every if tag in h.tags)
            name = _("tag “{tag}”").format(tag=tag)
            sources.append(
                Source(counted(_("Tag: {tag}").format(tag=tag), len(hosts)), name, hosts)
            )
            if not self._needle() and current.kind == "tag" and current.value == tag:
                start = len(sources) - 1
        return sources, start

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
        connector = self.connector
        dialog = ManualConnectDialog(self, connector.choices(), connector.default_profile())
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            connector.connect([dialog.request()])

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
        menu.addActions([a.manual_connect, a.connection_profiles, a.forget_passwords])

    def forget_passwords(self) -> None:
        self.connector.credentials.forget()
        self._account = None
        self._shell.show_message(_("Typed passwords forgotten."), 5000)
        self._update_state()

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

    # ---- settings ----

    def settings_values(self) -> dict[str, Any]:
        """What Settings shows about Hosts."""
        return {
            "start_list": self._prefs.get(locations.START_KEY, locations.START_LAST),
            "default_list": self._default_list,
            "personal_list": self._personal_list,
            "document": self._doc,
            "added": locations.added_lists(self._prefs),
            "found": self.found_lists(hidden=True),
            "hidden": locations.hidden_lists(self._prefs),
            "catalogs": self.connector.catalogs,
            "auto_status": self._auto_status(),
            "start_view": self.start_view(),
            "host_list": self._doc.hosts if self._doc else None,
        }

    def wire_settings(self, dialog: SettingsDialog) -> None:
        """Choices made in Settings about Hosts apply at once."""
        dialog.prefs_changed.connect(self.apply_prefs)
        dialog.open_requested.connect(lambda path: self._open_from_settings(dialog, path))
        dialog.profiles_changed.connect(self._selection_changed)  # Connect's menu follows

    def _open_from_settings(self, dialog: SettingsDialog, path: Path) -> None:
        """A list opened from Settings > Host lists: Settings then shows it as the open one."""
        self.open_list(path)
        dialog.list_opened(self._doc, self.start_view(), self._doc.hosts if self._doc else None)

    def apply_prefs(self, prefs: SettingsPrefs) -> None:
        """A choice made in Settings, kept and applied at once."""
        self.apply_list_prefs(
            prefs.start_list, prefs.start_view, prefs.added_lists, prefs.hidden_lists
        )
        on, minutes = prefs.auto_status
        self._prefs["auto_status"] = {"on": on, "minutes": minutes}
        self._apply_auto_status()
        self._save_prefs()
        self._update_state()  # the list's name may change with the lists kept

    # ---- showing ----

    def list_switched(self) -> None:
        self._status_found.clear()  # another list's hosts: old results don't apply
        self._users_found.clear()

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
            )
            self.details.show_host(details, 1, needle=self._needle())
        else:
            self.details.show_host(None, len(items), summary=self._summary())

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
        shown = self.table.topLevelItemCount() > 0
        for action in (self.toolbar.refresh_status, self.toolbar.refresh_users):
            action.setEnabled(shown and self._run is None)
        a.forget_passwords.setEnabled(bool(self.connector.credentials) or bool(self._account))

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
        if targets:
            wanted = Checks(status, users, self._ports(), self._account if users else None)
            self._start(targets, wanted)

    def _auto_status(self) -> tuple[bool, int]:
        saved = self._prefs.get("auto_status")
        saved = saved if isinstance(saved, dict) else {}
        minutes = saved.get("minutes", 5)
        minutes = minutes if isinstance(minutes, int) and 1 <= minutes <= 120 else 5
        return saved.get("on") is True, minutes

    def _apply_auto_status(self) -> None:
        on, minutes = self._auto_status()
        if on:
            self._auto_timer.start(minutes * 60_000)
        else:
            self._auto_timer.stop()

    def _auto_status_check(self) -> None:
        """Status only (ping and ports) on the hosts shown; skipped while a Refresh runs."""
        hosts = self.visible_items()
        if self._run is None and hosts:
            self.check_hosts(hosts, status=True, users=False)

    def _start(self, targets: list[tuple[str, str]], wanted: Checks) -> None:
        run = CheckRun(targets, wanted)
        run.found.connect(self._found)
        run.finished.connect(self._run_finished)
        self._run, self._refused, self._reported = run, [], set()
        self._targets = targets
        self._show_progress()
        self._stop_button.setEnabled(True)
        self._update_state()
        self.checks_changed.emit()
        log.info(
            "Refresh: %d hosts (status=%s, users=%s, account=%s)",
            len(targets), wanted.status, wanted.users, "typed" if wanted.account else "Windows",
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
        """A host didn't let the account read who is logged on: offer another, once per run."""
        account = run.wanted.account
        first = self._name_of(self._refused[-1]) if self._refused else ""
        if run.halted and account is not None:
            text = _(
                "“{host}” rejected the account “{user}”, so CapyPanel stopped before trying it "
                "on other computers. Type the password again, or use another account."
            ).format(host=first, user=account.user)
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
        dialog = AccountDialog(self, text, account.user if account else "")
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        self._account = dialog.account()
        # Again: the hosts that refused, and those a rejection kept from being tried.
        again = [t for t in self._targets if t[0] in self._refused or t[0] not in self._reported]
        if again:
            self._start(again, Checks(False, True, run.wanted.ports, self._account))

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

    def _refresh_shown(self, status: bool, users: bool) -> None:
        """Refresh: every host the table shows (the search's results, or the group or tag)."""
        self.check_hosts(self.visible_items(), status=status, users=users)

    def _run_refresh_panel(self) -> None:
        choices = self.refresh_panel.choices()
        self._prefs["refresh"] = choices
        self._save_prefs()
        self.check_hosts(self.visible_items(), status=choices["status"], users=choices["users"])
