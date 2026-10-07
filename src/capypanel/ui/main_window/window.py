"""The main window: panes, menus, and opening and editing host lists."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QActionGroup,
    QCloseEvent,
    QGuiApplication,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QToolButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel import BUILD
from capypanel.core import i18n, settings, winsec
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.listfile import HostListChangedError, HostListFileError
from capypanel.core.hosts.locations import ListKind
from capypanel.core.hosts.model import Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import checks
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import Answer, Status
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.connect import SessionCredentials, Target
from capypanel.core.tools.profiles import ProfileError
from capypanel.ui import checks as check_texts
from capypanel.ui import language
from capypanel.ui.checks import AccountDialog, CheckRun
from capypanel.ui.connect import Connector, ManualConnectDialog, Request
from capypanel.ui.groups import ROLE_ID, ManageGroupsDialog
from capypanel.ui.host_lists import HostListsDialog
from capypanel.ui.hosts import (
    HostDialog,
    ProfilePicker,
    confirm,
    group_path,
    list_file_filter,
)
from capypanel.ui.icons import STATUS_COLORS, dot_icon
from capypanel.ui.main_window.actions import create_actions, retranslate_actions
from capypanel.ui.main_window.host_views import (
    Cells,
    DetailsPane,
    HostTable,
    NavigationPane,
    SearchBox,
)
from capypanel.ui.main_window.toolbar import MainToolBar, RefreshPanel
from capypanel.ui.menus import StayOpenMenu, section
from capypanel.ui.settings import connections
from capypanel.ui.settings.connections import ConnectionChanges
from capypanel.ui.settings.window import SettingsChoices, SettingsDialog
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)
MANY_USER_CHECKS = 50  # reading logged-on users on more hosts than this asks first


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: settings.Paths,
        prefs: dict[str, Any],
        *,
        registry: themes.Registry | None = None,
    ):
        super().__init__()
        self._paths = paths
        self._prefs = prefs
        self.registry = registry if registry is not None else themes.Registry()
        self._doc: OpenList | None = None
        self._default_list = paths.default_list
        self._personal_list = paths.personal_list
        self.connector = Connector(
            self, Catalogs.for_paths(paths), SessionCredentials(), self._prefs
        )
        self.connector.open_settings = lambda: self.open_settings("connections")

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

        self.commands = create_actions(self)
        self.toolbar = MainToolBar(self.commands)
        self.addToolBar(self.toolbar)
        self.refresh_panel = RefreshPanel(self)
        self.refresh_panel.set_choices(self._prefs.get("refresh"))
        self.nav = NavigationPane()
        self.table = HostTable()
        self.search = SearchBox()
        self._search_timer = QTimer(self)  # waits for a pause in typing, then filters
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        hosts_pane = QWidget()
        column = QVBoxLayout(hosts_pane)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.search)
        column.addWidget(self.table)
        self.details = DetailsPane()
        self._splitter = QSplitter()
        for pane in (self.nav, hosts_pane, self.details):
            self._splitter.addWidget(pane)
        self._splitter.setStretchFactor(1, 1)
        # Dragged all the way, a pane would vanish; View hides panes on purpose instead.
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setSizes([220, 640, 280])
        central = QWidget()
        margins = QVBoxLayout(central)
        margins.setContentsMargins(8, 4, 8, 4)  # the same gap above and below the panes
        margins.addWidget(self._splitter)
        self.setCentralWidget(central)
        self._list_label = QLabel()
        self._list_label.setContentsMargins(6, 0, 6, 0)
        self.statusBar().addWidget(self._list_label, 1)
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
            self.statusBar().addPermanentWidget(widget)

        self._build_menus()
        self._connect()
        self._restore_layout()
        self._auto_timer = QTimer(self)  # Settings > General: Status by itself, if switched on
        self._auto_timer.timeout.connect(self._auto_status_check)
        self._apply_auto_status()
        self._open_startup_list()
        self._refresh()

    # ---- building ----

    def _build_menus(self) -> None:
        """Menus are built without text; retranslate() fills it in, now and on every switch."""
        a = self.commands
        bar = self.menuBar()
        self._file_menu = bar.addMenu("")
        self._file_menu.addActions([a.new_list, a.open_list])
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.settings)
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.exit)

        self._inventory_menu = bar.addMenu("")
        # What acts on a host or group (edit, remove, copy, open) is in its right-click menu.
        self._inventory_menu.addActions([a.add_host, a.add_group])
        self._inventory_menu.addSeparator()
        self._inventory_menu.addAction(a.manage_groups)

        self._connect_menu = bar.addMenu("")
        self._connect_menu.addActions([a.manual_connect, a.connection_profiles])
        self._connect_menu.addSeparator()
        self._connect_menu.addAction(a.forget_passwords)

        # It stays open while parts are ticked, so several can be shown or hidden in one go.
        self._view_menu = StayOpenMenu(self)
        bar.addMenu(self._view_menu)
        self._bars_heading = section(self._view_menu, "")
        self._view_menu.addActions([a.show_toolbar, a.show_status_bar])
        self._panes_heading = section(self._view_menu, "")
        self._view_menu.addActions([a.show_groups, a.show_tags, a.show_details])
        self._users_heading = section(self._view_menu, "")
        self._view_menu.addAction(a.show_domains)
        self._view_menu.addSeparator()
        self._theme_menu = self._view_menu.addMenu("")
        self._theme_group = QActionGroup(self)
        previous_engine = None
        for theme in self.registry.all():
            if previous_engine and theme.engine != previous_engine:
                self._theme_menu.addSeparator()  # native themes, then the app's own looks
            previous_engine = theme.engine
            item = self._theme_menu.addAction("")
            item.setCheckable(True)
            item.setData(theme.id)
            item.setChecked(theme.id == themes.current().id)
            self._theme_group.addAction(item)
        self._theme_group.triggered.connect(lambda item: self.set_theme(item.data()))

        # Each language is named in its own language, so these texts never change.
        self._language_menu = self._view_menu.addMenu("")
        self._language_group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            item = self._language_menu.addAction(name)
            item.setCheckable(True)
            item.setData(code)
            item.setChecked(code == i18n.language())
            self._language_group.addAction(item)
        self._language_group.triggered.connect(lambda item: self.set_language(item.data()))
        self._retranslate_menus()

    def _retranslate_menus(self) -> None:
        retranslate_actions(self.commands)
        self.toolbar.retranslate()
        self.refresh_panel.retranslate()
        self._stop_button.setText(_("Stop"))
        self.search.retranslate()
        self._file_menu.setTitle(_("&File"))
        self._inventory_menu.setTitle(_("&Inventory"))
        self._connect_menu.setTitle(_("&Connect"))
        self._view_menu.setTitle(_("&View"))
        self._bars_heading.setText(_("Bars"))
        self._panes_heading.setText(_("Panes"))
        self._users_heading.setText(_("Users"))
        self._theme_menu.setTitle(_("&Theme"))
        self._language_menu.setTitle(_("&Language"))
        for item in self._theme_group.actions():
            item.setText(self.registry.find(item.data()).title())

    def _connect(self) -> None:
        a = self.commands
        a.new_list.triggered.connect(self.new_list)
        a.open_list.triggered.connect(self.manage_lists)
        a.settings.triggered.connect(lambda: self.open_settings())
        a.exit.triggered.connect(self.close)
        a.add_host.triggered.connect(self.add_host)
        a.add_group.triggered.connect(self.add_group)
        a.manage_groups.triggered.connect(self.manage_groups)
        a.edit.triggered.connect(self.edit_selected)
        a.remove.triggered.connect(self.remove_selected)
        # Not in any menu bar menu, so their shortcuts (F2, Del, Ctrl+Shift+C) live here.
        self.addActions([a.edit, a.remove, a.copy_address])
        a.show_toolbar.toggled.connect(self.toolbar.setVisible)
        a.show_groups.toggled.connect(self.nav.setVisible)
        a.show_tags.toggled.connect(self.nav.set_tags_visible)
        a.show_details.toggled.connect(self.details.setVisible)
        a.show_status_bar.toggled.connect(self.statusBar().setVisible)
        a.show_domains.toggled.connect(self._show_domains)
        # Refresh follows the end of the host table, wherever the panes are.
        for toggled in (a.show_groups.toggled, a.show_details.toggled, a.show_toolbar.toggled):
            toggled.connect(self._align_refresh_later)
        self._splitter.splitterMoved.connect(self._align_refresh_later)
        a.check_status.triggered.connect(
            lambda: self.check_hosts(self._selected_hosts(), status=True, users=False)
        )
        a.check_users.triggered.connect(
            lambda: self.check_hosts(self._selected_hosts(), status=False, users=True)
        )
        self.toolbar.refresh_panel_requested.connect(self._show_refresh_panel)
        self.toolbar.refresh_requested.connect(self._refresh_shown)
        self.refresh_panel.run_clicked.connect(self._run_refresh_panel)
        self.toolbar.connect_menu.aboutToShow.connect(self._fill_connect_menu)
        self.nav.add_group_button.clicked.connect(self.add_group)
        self.nav.filter_changed.connect(self._filter_picked)
        self.search.textChanged.connect(self._search_timer.start)
        self._search_timer.timeout.connect(self._show_hosts)
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        self.nav.groups.customContextMenuRequested.connect(self._group_menu)
        self.nav.groups.rearranged.connect(self._groups_dragged)
        self.nav.groups.hosts_dropped.connect(self.move_hosts)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._host_menu)
        self.table.columns_changed.connect(self._save_columns)
        self.table.columns_changed.connect(self._show_hosts)  # a search covers only what's shown
        # Enter connects only from the host table, so it never fires while typing elsewhere.
        a.connect_host.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.connect_host)
        self.table.itemDoubleClicked.connect(self._double_clicked)
        a.connect_host.triggered.connect(self.connect_selected)
        a.manual_connect.triggered.connect(self.manual_connect)
        a.copy_address.triggered.connect(lambda: self._copy(lambda h: h.target))
        a.copy_name.triggered.connect(lambda: self._copy(lambda h: h.name))
        a.forget_passwords.triggered.connect(self.forget_passwords)
        a.connection_profiles.triggered.connect(lambda: self.open_settings("connections"))

    def _restore_layout(self) -> None:
        geometry = self._prefs.get("window_geometry")
        if not (
            isinstance(geometry, str)
            and self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        ):
            self.resize(1100, 700)
        splitter = self._prefs.get("main_splitter")
        if isinstance(splitter, str):
            self._splitter.restoreState(QByteArray.fromBase64(splitter.encode()))
        view = self._prefs.get("view")
        view = view if isinstance(view, dict) else {}
        for key, action in (
            ("toolbar", self.commands.show_toolbar),
            ("groups", self.commands.show_groups),
            ("tags", self.commands.show_tags),
            ("details", self.commands.show_details),
            ("status_bar", self.commands.show_status_bar),
            ("domains", self.commands.show_domains),
        ):
            action.setChecked(bool(view.get(key, True)))
        check_texts.show_domains(self.commands.show_domains.isChecked())
        self.nav.set_tags_visible(self.commands.show_tags.isChecked())
        self.toolbar.setVisible(self.commands.show_toolbar.isChecked())
        self.table.set_hidden_columns(self._prefs.get("hidden_columns"))
        self.nav.setVisible(self.commands.show_groups.isChecked())
        self.details.setVisible(self.commands.show_details.isChecked())
        self.statusBar().setVisible(self.commands.show_status_bar.isChecked())

    # ---- opening lists ----

    @property
    def document(self) -> OpenList | None:
        return self._doc

    def _open_startup_list(self) -> None:
        """The chosen list (normally the last used), else the default, else the personal one."""
        prefs = self._prefs
        order = locations.startup_order(
            prefs, default=self._default_list, personal=self._personal_list
        )
        # On a first start there's nothing to miss; otherwise say when the expected list failed.
        expected = prefs.get(locations.START_KEY, locations.START_LAST) != locations.START_LAST
        expected = expected or bool(locations.recent_lists(prefs))
        for index, path in enumerate(order):
            if not path.exists() and self._kind(path) is ListKind.SHARED:
                continue  # a missing list isn't an error at start: try the next one
            if self.open_list(path, quiet=True):
                if index and expected:
                    note = _("Couldn't open “{wanted}”, so “{opened}” was opened instead.")
                    self._error(note.format(wanted=order[0], opened=path), quiet=True)
                return

    def open_list(self, path: Path, *, quiet: bool = False) -> bool:
        kind = self._kind(path)
        if kind is not ListKind.SHARED and not path.exists():
            return self._create_list(path, replace_existing=False, quiet=quiet)
        if kind is ListKind.DEFAULT and not winsec.made_by_trusted(path):
            note = _(
                "The default list was made by another user, so CapyPanel won't open it. An "
                "administrator can replace or delete “{path}”."
            )
            self._error(note.format(path=path), quiet)
            return False
        try:
            doc = OpenList.open(path)
        except FileNotFoundError:
            locations.forget_list(self._prefs, path)
            self._error(_("The list “{path}” doesn't exist anymore.").format(path=path), quiet)
            return False
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't open “{path}”: {error}").format(path=path, error=e), quiet)
            return False
        self._use(doc)
        return True

    def new_list(self) -> None:
        name, _filter = QFileDialog.getSaveFileName(
            self, _("New host list"), str(self._personal_list.parent), list_file_filter()
        )
        if name:
            path = Path(name)
            # The file dialog already asked before choosing an existing file.
            self._create_list(path, replace_existing=path.exists())

    def manage_lists(self) -> None:
        """File > Host lists…: every list this user works with; open one from there."""
        dialog = HostListsDialog(
            self,
            default_list=self._default_list,
            personal_list=self._personal_list,
            added=locations.added_lists(self._prefs),
            document=self._doc,
        )
        opened = dialog.exec() == QDialog.DialogCode.Accepted
        locations.set_added_lists(self._prefs, dialog.view.added)  # added or forgotten there
        self._save_prefs()
        path = dialog.view.selected()
        if opened and path is not None:
            current = self._doc.path if self._doc else None
            rewritten = any(locations.same_path(path, p) for p in dialog.view.written)
            if current is None or rewritten or not locations.same_path(path, current):
                self.open_list(path)

    def _create_list(self, path: Path, *, replace_existing: bool, quiet: bool = False) -> bool:
        try:
            doc = OpenList.create(path, replace_existing=replace_existing)
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't create “{path}”: {error}").format(path=path, error=e), quiet)
            return False
        self._use(doc)
        return True

    def _use(self, doc: OpenList) -> None:
        if self._doc is None or not locations.same_path(self._doc.path, doc.path):
            self._status_found.clear()  # another list's hosts: old results don't apply
            self._users_found.clear()
            self._clear_search()
        self._doc = doc
        locations.remember_list(self._prefs, doc.path)
        if self._kind(doc.path) is ListKind.SHARED:  # it shows in File > Host lists… from now on
            added = locations.added_lists(self._prefs)
            locations.set_added_lists(self._prefs, [*added, doc.path])
        self._save_prefs()
        log.info("Opened host list %s (read-only=%s)", doc.path, doc.read_only)
        self._refresh()

    # ---- editing ----

    def add_host(self) -> None:
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
        if dialog.exec() != QDialog.DialogCode.Accepted:
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

    def edit_host(self, host: Host) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = HostDialog(self, doc.hosts, host, profiles=self._profile_picker(doc.hosts))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        edited = replace(
            host,
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
        if edited.connect_address != host.connect_address:  # results were for the old address
            self._status_found.pop(host.id, None)
            self._users_found.pop(host.id, None)
        self._commit(new)

    def add_group(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        parent = self.nav.selected_group_id()
        where = group_path(doc.hosts, parent) if parent else ""
        prompt = (
            _("Name of the new group inside “{group}”:").format(group=where)
            if parent
            else _("Name of the new group:")
        )
        name, ok = QInputDialog.getText(self, _("Add group"), prompt)
        if not ok or not name.strip():
            return
        try:
            new, _group = doc.hosts.add_group(name, parent)
        except HostListRuleError as e:
            self._error(str(e))
            return
        self._commit(new)

    def rename_group(self, group_id: str) -> None:
        doc = self._writable()
        group = doc.hosts.group(group_id) if doc else None
        if doc is None or group is None:
            return
        name, ok = QInputDialog.getText(self, _("Rename group"), _("New name:"), text=group.name)
        if ok and name.strip() and name.strip() != group.name:
            self._commit(doc.hosts.rename_group(group_id, name))

    def edit_selected(self) -> None:
        if self._doc is None:
            return
        group_id = self.nav.selected_group_id()
        hosts = self._selected_hosts()
        if self.nav.groups.hasFocus() and group_id:
            self.rename_group(group_id)
        elif len(hosts) == 1:
            self.edit_host(hosts[0])
        elif group_id and not hosts:
            self.rename_group(group_id)

    def remove_selected(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        group_id = self.nav.selected_group_id()
        hosts = self._selected_hosts()
        if (self.nav.groups.hasFocus() or not hosts) and group_id:
            self.remove_group(group_id)
        elif hosts:
            self.remove_hosts(hosts)

    def remove_hosts(self, hosts: list[Host]) -> None:
        doc = self._writable()
        if doc is None or not hosts:
            return
        if len(hosts) == 1:
            text = _("Remove “{name}” from the list?").format(name=hosts[0].name)
        else:
            text = ngettext(
                "Remove {n} host from the list?", "Remove {n} hosts from the list?", len(hosts)
            ).format(n=len(hosts))
        if confirm(self, _("Remove hosts"), text, _("Remove")):
            self._commit(doc.hosts.remove_hosts(h.id for h in hosts))

    def remove_group(self, group_id: str) -> None:
        doc = self._writable()
        group = doc.hosts.group(group_id) if doc else None
        if doc is None or group is None:
            return
        count = len(doc.hosts.hosts_in(group_id))
        text = _("Remove the group “{name}” and the groups inside it?").format(name=group.name)
        if count:
            text += " " + ngettext(
                "This will also remove {n} host.", "This will also remove {n} hosts.", count
            ).format(n=count)
        if confirm(self, _("Remove group"), text, _("Remove")):
            self._commit(doc.hosts.remove_group(group_id))

    def _commit(self, new: HostList) -> bool:
        """Save an edit. If someone else changed the file meanwhile, ask what to do with ours."""
        doc = self._doc
        if doc is None:
            return False
        try:
            doc.commit(new)
        except HostListChangedError:
            self._resolve_conflict(new)
            return False
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't save the list: {error}").format(error=e))
            return False
        self._refresh()
        return True

    def _resolve_conflict(self, mine: HostList) -> None:
        doc = self._doc
        if doc is None:
            return
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("The list has changed"),
            _(
                "Someone else saved changes to this list after you opened it. Your change wasn't "
                "saved. You can save your version as a separate copy or reload the list with "
                "their changes."
            ),
            parent=self,
        )
        copy = box.addButton(_("Save my version as a copy…"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Reload the list"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(copy)
        box.exec()
        if box.clickedButton() is copy:
            name, _filter = QFileDialog.getSaveFileName(
                self,
                _("Save a copy"),
                str(doc.path.with_name(doc.path.stem + " (copy).json")),
                list_file_filter(),
            )
            if name:
                path = Path(name)
                try:
                    self._use(OpenList.save_as(path, mine, replace_existing=path.exists()))
                    return
                except (HostListFileError, OSError) as e:
                    self._error(_("Couldn't save the copy: {error}").format(error=e))
        try:
            doc.reload()
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't reload the list: {error}").format(error=e))
        self._refresh()

    # ---- connecting ----

    def connect_selected(self, profile: str | None = None) -> None:
        """With the hosts' own profiles, or once with `profile` (the toolbar's Connect arrow)."""
        hosts = self._selected_hosts()
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
            self.statusBar().showMessage(
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
        box.exec()
        if box.clickedButton() is edit:
            self.edit_host(host)

    def manual_connect(self) -> None:
        connector = self.connector
        dialog = ManualConnectDialog(self, connector.choices(), connector.default_profile())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            connector.connect([dialog.request()])

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

    def _connection_text(self, host_list: HostList, host: Host) -> str:
        profile_id, source = host_list.profile_of(host, self._profile_exists)
        name = self.connector.label(profile_id)
        if profile_id and source is None:  # the host's own
            return name
        if source is not None:
            return _("{profile} (from group “{group}”)").format(profile=name, group=source.name)
        return _("{profile} (default)").format(profile=name)

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

    def set_hosts_profile(self, host_ids: list[str], profile: str) -> None:
        doc = self._writable()
        if doc is not None:
            self._commit(doc.hosts.set_hosts_profile(host_ids, profile))
            self._selection_changed()

    def manage_groups(self) -> None:
        """Inventory > Manage groups…: reorder and nest every group at once."""
        doc = self._writable()
        if doc is None:
            return
        dialog = ManageGroupsDialog(self, doc.hosts)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._arrange(dialog.order())

    def _groups_dragged(self) -> None:
        self._arrange(self.nav.groups.order())

    def _arrange(self, order: list[tuple[str, str | None]]) -> None:
        doc = self._writable()
        if doc is None:
            return
        try:
            new = doc.hosts.arrange_groups(order)
        except HostListRuleError as e:
            self._error(str(e))
            self._refresh()  # puts the tree back as it was
            return
        self._commit(new)

    def move_hosts(self, host_ids: list[str], group_id: str) -> None:
        """Hosts dragged from the table onto a group."""
        doc = self._writable()
        if doc is None or doc.hosts.group(group_id) is None:
            return
        self._commit(doc.hosts.move_hosts(host_ids, group_id))

    def set_group_profile(self, group_id: str, profile: str) -> None:
        doc = self._writable()
        if doc is not None and doc.hosts.group(group_id) is not None:
            self._commit(doc.hosts.set_group_profile(group_id, profile))
            self._selection_changed()

    def forget_passwords(self) -> None:
        self.connector.credentials.forget()
        self._account = None
        self.statusBar().showMessage(_("Typed passwords forgotten."), 5000)
        self._update_state()

    def _copy(self, value: Callable[[Host], str]) -> None:
        hosts = self._selected_hosts()
        if hosts:
            QGuiApplication.clipboard().setText("\n".join(value(h) for h in hosts))

    # ---- settings ----

    def open_settings(self, page: str | None = None) -> None:
        dialog = self.settings_dialog()
        geometry = self._prefs.get("settings_geometry")
        if isinstance(geometry, str):
            dialog.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        if page:
            dialog.show_page(page)
        dialog.saved.connect(lambda choices: self._settings_saved(dialog, choices))
        dialog.exec()
        self._prefs["settings_geometry"] = dialog.saveGeometry().toBase64().toStdString()
        self._save_prefs()

    def _settings_saved(self, dialog: SettingsDialog, choices: SettingsChoices) -> None:
        """OK or Save in Settings: apply now; after Save the window stays open."""
        self.apply_settings(choices)
        self._selection_changed()  # profiles may have changed
        dialog.after_save(self._doc)

    def settings_dialog(self) -> SettingsDialog:
        return SettingsDialog(
            self,
            paths=self._paths,
            start_list=self._prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=self._default_list,
            personal_list=self._personal_list,
            document=self._doc,
            added=locations.added_lists(self._prefs),
            registry=self.registry,
            catalogs=self.connector.catalogs,
            auto_status=self._auto_status(),
        )

    def apply_settings(self, choices: SettingsChoices) -> None:
        self._prefs[locations.START_KEY] = choices.start_list
        locations.set_added_lists(self._prefs, choices.added_lists)
        current = self._doc.path if self._doc else None
        if (
            current is None
            or choices.rewritten
            or not locations.same_path(choices.host_list, current)
        ):
            self.open_list(choices.host_list)
        if choices.theme_id != themes.current().id:
            self.set_theme(choices.theme_id)
        if choices.language != i18n.language():
            self.set_language(choices.language)
        self._apply_connections(choices.connections)
        on, minutes = choices.auto_status
        self._prefs["auto_status"] = {"on": on, "minutes": minutes}
        self._apply_auto_status()
        self._save_prefs()

    def _apply_connections(self, changes: ConnectionChanges) -> None:
        try:
            connections.apply(self.connector.catalogs, changes)
        except (ProfileError, OSError) as e:
            self._error(_("Couldn't save the connection profiles: {error}").format(error=e))

    # ---- look ----

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)
        self.toolbar.restyle()  # icon colour and caption capitals follow the theme
        for item in self._theme_group.actions():
            item.setChecked(item.data() == theme.id)
        self._prefs["theme"] = theme.id
        self._save_prefs()
        log.info("Theme: %s", theme.id)

    def set_language(self, code: str) -> None:
        """Switches live: Qt then sends every window a LanguageChange event (see changeEvent)."""
        code = language.apply(code)
        for item in self._language_group.actions():
            item.setChecked(item.data() == code)
        self._prefs["language"] = code
        self._save_prefs()
        log.info("Language: %s", code)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        """Every text this window shows, in the current language."""
        self._retranslate_menus()
        self.nav.retranslate()
        self.table.retranslate()
        self.details.retranslate()
        self._refresh()  # rebuilds the lists ("All hosts"), details hint and status bar

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)  # the window handle only exists once it's shown
        self._align_refresh_later()

    # ---- showing ----

    def _refresh(self) -> None:
        self.nav.show_list(self._doc.hosts if self._doc else None)
        editable = self._writable() is not None  # read-only lists can't be rearranged
        self.nav.groups.set_editable(editable)
        self.table.set_editable(editable)
        self._show_hosts()

    def _show_hosts(self) -> None:
        self._search_timer.stop()
        needle = self._needle()
        hosts = self._visible_hosts()
        groups = {}
        if needle and self._doc is not None:  # results come from every group: say which
            groups = {h.id: group_path(self._doc.hosts, h.group) for h in hosts}
        self.nav.set_searching(bool(needle))
        self.table.show_hosts(hosts, {h.id: self._cells(h.id) for h in hosts}, groups)
        self.table.set_search(needle)  # after the rows, so Group fits their paths

    def _visible_hosts(self) -> tuple[Host, ...]:
        """The hosts the table shows: the search's results, or the group or tag picked."""
        if self._doc is None:
            return ()
        hosts, current = self._doc.hosts, self.nav.current_filter()
        if needle := self._needle():
            return tuple(h for h in hosts.hosts if self._matches(h, needle))
        if current.kind == "group" and current.value:
            return hosts.hosts_in(current.value)
        if current.kind == "tag":
            return tuple(h for h in hosts.hosts if current.value in h.tags)
        return hosts.hosts

    # ---- searching ----

    def _needle(self) -> str:
        return self.search.text().strip().casefold()

    def _matches(self, host: Host, needle: str) -> bool:
        """The name, plus the address and users when their columns show: only what can be
        seen. Users come from the last logged-on users check (memory only)."""
        table = self.table
        if needle in host.name.casefold():
            return True
        if not table.isColumnHidden(table.ADDRESS) and needle in host.address.casefold():
            return True
        if table.isColumnHidden(table.USER):
            return False
        sessions = (self._users_found.get(host.id) or ((), None, None))[0] or ()
        return any(needle in check_texts.user_name(s).casefold() for s in sessions)

    def _show_domains(self, shown: bool) -> None:
        check_texts.show_domains(shown)
        self._show_hosts()  # the User column, the search and the details pane

    def _focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _clear_search(self) -> None:
        self.search.blockSignals(True)  # the caller shows the hosts once, right after
        self.search.clear()
        self.search.blockSignals(False)

    def _filter_picked(self) -> None:
        """Picking a group or tag on the left ends a search: it means browsing again."""
        self._clear_search()
        self._show_hosts()

    def _double_clicked(self, item: QTreeWidgetItem) -> None:
        """Connects; on a search result, opens the host's group and ends the search instead."""
        if self._needle():
            self.show_in_group(item.data(0, ROLE_ID))
        else:
            self.connect_selected()

    def show_in_group(self, host_id: str) -> None:
        host = self._doc.hosts.host(host_id) if self._doc else None
        if host is None:
            return
        self._clear_search()
        self.nav.select_group(host.group)
        self._show_hosts()
        self.table.select_ids([host.id])

    def _selected_hosts(self) -> list[Host]:
        if self._doc is None:
            return []
        found = (self._doc.hosts.host(i) for i in self.table.selected_ids())
        return [h for h in found if h is not None]

    def _selection_changed(self) -> None:
        hosts = self._selected_hosts()
        if len(hosts) == 1 and self._doc is not None:
            host_list, host = self._doc.hosts, hosts[0]
            self.details.show_host(
                host,
                group_path(host_list, host.group),
                1,
                self._connection_text(host_list, host),
                *self._details_found(host.id),
            )
        else:
            self.details.show_host(None, "", len(hosts))
        self._update_state()

    def _update_state(self) -> None:
        doc = self._doc
        writable = doc is not None and not doc.read_only
        selected = len(self.table.selected_ids())
        group_picked = self.nav.selected_group_id() is not None
        a = self.commands
        a.add_host.setEnabled(writable)
        a.add_group.setEnabled(writable)
        self.nav.add_group_button.setEnabled(writable)
        a.edit.setEnabled(writable and (selected == 1 or group_picked))
        a.remove.setEnabled(writable and (selected > 0 or group_picked))
        for action in (a.connect_host, a.copy_address, a.copy_name):
            action.setEnabled(selected > 0)  # read-only lists can still connect
        for action in (a.check_status, a.check_users):
            action.setEnabled(selected > 0 and self._run is None)  # one Refresh at a time
        shown = self.table.topLevelItemCount() > 0
        for action in (self.toolbar.refresh_status, self.toolbar.refresh_users):
            action.setEnabled(shown and self._run is None)
        a.forget_passwords.setEnabled(bool(self.connector.credentials) or bool(self._account))
        if doc is None:
            self.setWindowTitle(f"CapyPanel {BUILD}")
            self._list_label.setText(_("No host list is open."))
            return
        self.setWindowTitle(f"{doc.path.name} — CapyPanel {BUILD}")
        total = len(doc.hosts.hosts)
        parts = [
            f"{self._kind_label(self._kind(doc.path))} — {doc.path}",
            ngettext("{n} host", "{n} hosts", total).format(n=total),
            ngettext("{n} selected", "{n} selected", selected).format(n=selected),
        ]
        if self._needle():
            found = self.table.topLevelItemCount()
            parts.insert(2, ngettext("{n} found", "{n} found", found).format(n=found))
        if doc.read_only:
            parts.append(_("read-only"))
        if self._paths.portable:
            parts.append(_("portable mode"))
        self._list_label.setText(" · ".join(parts))

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
            self.statusBar().showMessage(note.format(n=skipped), 10_000)
        if (
            users
            and len(targets) > MANY_USER_CHECKS
            and not confirm(
                self,
                _("Check logged-on users"),
                _("Check who is logged on to {n} hosts?").format(n=len(targets)),
                _("Check"),
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
        hosts = self._visible_hosts()
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
        if self.table.selected_ids() == [host_id]:
            self._selection_changed()
        self._show_progress()

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
        if run.stopped and run.done < run.total:
            left = run.total - run.done
            note = ngettext(
                "Stopped: {n} host wasn't checked.", "Stopped: {n} hosts weren't checked.", left
            )
            self.statusBar().showMessage(note.format(n=left), 10_000)
        else:
            self.statusBar().showMessage(
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
                "{n} computer didn't let your Windows login see who is logged on. Use another "
                "account, such as an administrator of those computers?",
                "{n} computers didn't let your Windows login see who is logged on. Use another "
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
        if dialog.exec() != QDialog.DialogCode.Accepted:
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
        unchecked = ("", _("Not checked yet: use Refresh"), None, True)
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
            if found:
                tip = f"{text}\n{tip}"  # every name, when the column is too narrow
            user_cell = (text, tip, None, error is not None or not found)
        return Cells(status_cell, user_cell)

    def _details_found(self, host_id: str) -> tuple[str, str]:
        """The Status and Logged on lines of the details pane."""
        status, users = "", ""
        if (found := self._status_found.get(host_id)) is not None:
            status = f"{check_texts.status_text(found[0])} ({check_texts.when_text(found[1])})"
        if (read := self._users_found.get(host_id)) is not None:
            sessions, error, when = read
            if error is None and sessions:
                users = check_texts.session_lines(sessions)
            else:
                users = check_texts.users_text(sessions, error)
            users += "\n" + _("As of {when}").format(when=check_texts.when_text(when))
        return status, users

    def _show_refresh_panel(self, where: QPoint) -> None:
        panel = self.refresh_panel
        panel.run_button.setEnabled(self._run is None)
        panel.adjustSize()
        panel.move(where)
        panel.show()

    def _refresh_shown(self, status: bool, users: bool) -> None:
        """Refresh: every host the table shows (the search's results, or the group or tag)."""
        self.check_hosts(self._visible_hosts(), status=status, users=users)

    def _run_refresh_panel(self) -> None:
        choices = self.refresh_panel.choices()
        self._prefs["refresh"] = choices
        self._save_prefs()
        self.check_hosts(self._visible_hosts(), status=choices["status"], users=choices["users"])

    def _fill_connect_menu(self) -> None:
        """The toolbar's Connect arrow: connect the selection once with another profile."""
        menu = self.toolbar.connect_menu
        menu.clear()
        section(menu, _("Connect once with"))
        for profile_id, name in self.connector.choices():
            item = menu.addAction(name.replace("&", "&&"))
            item.setEnabled(bool(self.table.selected_ids()))
            item.triggered.connect(lambda _c=False, p=profile_id: self.connect_selected(p))

    def _save_columns(self) -> None:
        self._prefs["hidden_columns"] = self.table.hidden_columns()
        self._save_prefs()

    def _align_refresh_later(self) -> None:
        QTimer.singleShot(0, self._align_refresh)  # once the panes have their new sizes

    def _align_refresh(self) -> None:
        if self.toolbar.isVisible():
            right = self.table.mapTo(self, QPoint(self.table.width(), 0)).x()
            self.toolbar.align_end(right - self.toolbar.x())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._align_refresh_later()

    # ---- right-click menus ----

    def _host_menu(self, position: QPoint) -> None:
        a = self.commands
        menu = QMenu(self)
        if self.table.itemAt(position) is None:  # empty space: what can be added here
            self.table.clearSelection()
            menu.addActions([a.add_host, a.add_group])
            menu.exec(self.table.viewport().mapToGlobal(position))
            return
        section(menu, _("Connect"))
        menu.addAction(a.connect_host)
        menu.setDefaultAction(a.connect_host)  # bold: what double-click and Enter do
        hosts = self._selected_hosts()
        if hosts and self._doc is not None:
            groups = {h.group for h in hosts}
            follow = (
                self.connector.inherited_label(
                    *self._doc.hosts.group_profile(groups.pop(), self._profile_exists)
                )
                if len(groups) == 1
                else _("From each host's group")
            )
            ids = [h.id for h in hosts]
            self._add_profile_menu(
                menu, {h.profile for h in hosts}, follow, lambda p: self.set_hosts_profile(ids, p)
            )
        section(menu, _("Check"))
        menu.addActions([a.check_status, a.check_users])
        section(menu, _("Copy"))
        menu.addActions([a.copy_address, a.copy_name])
        menu.addSeparator()
        menu.addActions([a.edit, a.remove])
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _group_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self.commands.add_group)
        # Only the group under the mouse: empty space never acts on the one picked before.
        group_id = self.nav.group_at(position)
        if group_id is not None:
            self.nav.select_group(group_id)
        group = self._doc.hosts.group(group_id) if self._doc and group_id else None
        if group is not None and self._doc is not None:
            section(menu, _("Connect"))
            follow = self.connector.inherited_label(
                *self._doc.hosts.group_profile(group.parent, self._profile_exists)
            )
            self._add_profile_menu(
                menu, {group.profile}, follow, lambda p: self.set_group_profile(group.id, p)
            )
            # The group's hosts, including those in the groups inside it.
            hosts = list(self._doc.hosts.hosts_in(group.id))
            section(menu, _("Check"))
            for text, status, users in (
                (_("&Status"), True, False),
                (_("&Logged-on users"), False, True),
            ):
                item = menu.addAction(text)
                item.setEnabled(bool(hosts) and self._run is None)
                item.triggered.connect(
                    lambda _c=False, s=status, u=users: self.check_hosts(hosts, status=s, users=u)
                )
            menu.addSeparator()
            menu.addActions([self.commands.edit, self.commands.remove])
        menu.exec(self.nav.groups.viewport().mapToGlobal(position))

    # ---- helpers ----

    def _writable(self) -> OpenList | None:
        return self._doc if self._doc is not None and not self._doc.read_only else None

    def _kind(self, path: Path) -> ListKind:
        return locations.list_kind(path, default=self._default_list, personal=self._personal_list)

    @staticmethod
    def _kind_label(kind: ListKind) -> str:
        return {
            ListKind.DEFAULT: _("Default"),
            ListKind.PERSONAL: _("Personal"),
            ListKind.SHARED: _("Shared"),
        }[kind]

    def _error(self, message: str, quiet: bool = False) -> None:
        log.warning("%s", message)
        if quiet:
            self.statusBar().showMessage(message, 10_000)
        else:
            QMessageBox.warning(self, "CapyPanel", message)

    def _save_prefs(self) -> None:
        try:
            settings.save_settings(self._paths.settings_file, self._prefs)
        except OSError:
            log.exception("Couldn't save settings")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._prefs["window_geometry"] = self.saveGeometry().toBase64().toStdString()
        self._prefs["main_splitter"] = self._splitter.saveState().toBase64().toStdString()
        if self._run is not None:
            self._run.stop()  # hosts already being read finish in the background
        self._prefs["refresh"] = self.refresh_panel.choices()
        self._prefs["view"] = {
            "toolbar": self.commands.show_toolbar.isChecked(),
            "groups": self.commands.show_groups.isChecked(),
            "tags": self.commands.show_tags.isChecked(),
            "details": self.commands.show_details.isChecked(),
            "status_bar": self.commands.show_status_bar.isChecked(),
            "domains": self.commands.show_domains.isChecked(),
        }
        self._save_prefs()
        super().closeEvent(event)
