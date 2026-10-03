"""The main window: panes, menus, and opening and editing host lists."""

import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QPoint, Qt
from PySide6.QtGui import QActionGroup, QCloseEvent, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
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
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.connect import SessionCredentials, Target
from capypanel.core.tools.profiles import ProfileError
from capypanel.ui import language
from capypanel.ui.connect import Connector, ManualConnectDialog, Request
from capypanel.ui.hosts import (
    HostDialog,
    ProfilePicker,
    confirm,
    group_path,
    list_file_filter,
)
from capypanel.ui.main_window.actions import create_actions, retranslate_actions
from capypanel.ui.main_window.host_views import (
    DetailsPane,
    HostTable,
    NavigationPane,
)
from capypanel.ui.settings import connections
from capypanel.ui.settings.connections import ConnectionChanges
from capypanel.ui.settings.window import SettingsChoices, SettingsDialog
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)


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

        self.commands = create_actions(self)
        self.nav = NavigationPane()
        self.table = HostTable()
        self.details = DetailsPane()
        self._splitter = QSplitter()
        for pane in (self.nav, self.table, self.details):
            self._splitter.addWidget(pane)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([220, 640, 280])
        central = QWidget()
        margins = QVBoxLayout(central)
        margins.setContentsMargins(8, 4, 8, 2)
        margins.addWidget(self._splitter)
        self.setCentralWidget(central)
        self._list_label = QLabel()
        self._list_label.setContentsMargins(6, 0, 6, 0)
        self.statusBar().addWidget(self._list_label, 1)

        self._build_menus()
        self._connect()
        self._restore_layout()
        self._open_startup_list()
        self._refresh()

    # ---- building ----

    def _build_menus(self) -> None:
        """Menus are built without text; retranslate() fills it in, now and on every switch."""
        a = self.commands
        bar = self.menuBar()
        self._file_menu = bar.addMenu("")
        self._file_menu.addActions([a.new_list, a.open_list])
        self._recent_menu = self._file_menu.addMenu("")
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.settings)
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.exit)

        self._inventory_menu = bar.addMenu("")
        self._inventory_menu.addActions([a.add_host, a.add_group])
        self._inventory_menu.addSeparator()
        self._inventory_menu.addActions([a.edit, a.remove])

        self._connect_menu = bar.addMenu("")
        self._connect_menu.addAction(a.connect_vnc)
        self._connect_menu.addAction(a.manual_connect)
        self._connect_menu.addSeparator()
        self._connect_menu.addActions([a.copy_address, a.copy_name])
        self._connect_menu.addSeparator()
        self._connect_menu.addAction(a.forget_passwords)
        self._connect_menu.addSeparator()
        self._connect_menu.addAction(a.connection_profiles)
        self._connect_menu.aboutToShow.connect(self._update_state)

        self._view_menu = bar.addMenu("")
        self._view_menu.addActions([a.show_groups, a.show_details, a.show_status_bar])
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
        self._file_menu.setTitle(_("&File"))
        self._recent_menu.setTitle(_("&Recent lists"))
        self._inventory_menu.setTitle(_("&Inventory"))
        self._connect_menu.setTitle(_("&Connect"))
        self._view_menu.setTitle(_("&View"))
        self._theme_menu.setTitle(_("&Theme"))
        self._language_menu.setTitle(_("&Language"))
        for item in self._theme_group.actions():
            item.setText(self.registry.find(item.data()).title())

    def _connect(self) -> None:
        a = self.commands
        a.new_list.triggered.connect(self.new_list)
        a.open_list.triggered.connect(self._ask_open_list)
        a.settings.triggered.connect(lambda: self.open_settings())
        a.exit.triggered.connect(self.close)
        a.add_host.triggered.connect(self.add_host)
        a.add_group.triggered.connect(self.add_group)
        a.edit.triggered.connect(self.edit_selected)
        a.remove.triggered.connect(self.remove_selected)
        a.show_groups.toggled.connect(self.nav.setVisible)
        a.show_details.toggled.connect(self.details.setVisible)
        a.show_status_bar.toggled.connect(self.statusBar().setVisible)
        self.nav.add_group_button.clicked.connect(self.add_group)
        self.nav.filter_changed.connect(self._show_hosts)
        self.nav.groups.customContextMenuRequested.connect(self._group_menu)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._host_menu)
        # Enter connects only from the host table, so it never fires while typing elsewhere.
        a.connect_vnc.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.connect_vnc)
        self.table.itemDoubleClicked.connect(lambda *_args: self.connect_selected())
        a.connect_vnc.triggered.connect(self.connect_selected)
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
            ("groups", self.commands.show_groups),
            ("details", self.commands.show_details),
            ("status_bar", self.commands.show_status_bar),
        ):
            action.setChecked(bool(view.get(key, True)))
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

    def _ask_open_list(self) -> None:
        start = self._doc.path.parent if self._doc else self._personal_list.parent
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Open host list"), str(start), list_file_filter()
        )
        if name:
            self.open_list(Path(name))

    def _create_list(self, path: Path, *, replace_existing: bool, quiet: bool = False) -> bool:
        try:
            doc = OpenList.create(path, replace_existing=replace_existing)
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't create “{path}”: {error}").format(path=path, error=e), quiet)
            return False
        self._use(doc)
        return True

    def _use(self, doc: OpenList) -> None:
        self._doc = doc
        locations.remember_list(self._prefs, doc.path)
        self._save_prefs()
        log.info("Opened host list %s (read-only=%s)", doc.path, doc.read_only)
        self._refresh()

    def _fill_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = locations.recent_lists(self._prefs)
        if not recent:
            self._recent_menu.addAction(_("No recent lists")).setEnabled(False)
            return
        for path in recent:
            text = f"{self._kind_label(self._kind(path))} — {path}".replace("&", "&&")
            item = self._recent_menu.addAction(text)
            item.setCheckable(True)
            item.setChecked(self._doc is not None and locations.same_path(path, self._doc.path))
            item.triggered.connect(lambda _checked=False, p=path: self.open_list(p))

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

    def connect_selected(self) -> None:
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
                h.name, Target(h.connect_address), host_list.profile_of(h, self._profile_exists)[0]
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

    def set_group_profile(self, group_id: str, profile: str) -> None:
        doc = self._writable()
        if doc is not None and doc.hosts.group(group_id) is not None:
            self._commit(doc.hosts.set_group_profile(group_id, profile))
            self._selection_changed()

    def forget_passwords(self) -> None:
        self.connector.credentials.forget()
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
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._prefs["settings_geometry"] = dialog.saveGeometry().toBase64().toStdString()
        if accepted:
            self.apply_settings(dialog.choices())
        else:
            self._save_prefs()
        self._selection_changed()  # Save may have changed profiles

    def settings_dialog(self) -> SettingsDialog:
        return SettingsDialog(
            self,
            paths=self._paths,
            start_list=self._prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=self._default_list,
            personal_list=self._personal_list,
            document=self._doc,
            recent=locations.recent_lists(self._prefs),
            registry=self.registry,
            catalogs=self.connector.catalogs,
        )

    def apply_settings(self, choices: SettingsChoices) -> None:
        self._prefs[locations.START_KEY] = choices.start_list
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
        self._refresh()  # rebuilds the lists ("All computers"), details hint and status bar

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)  # the window handle only exists once it's shown

    # ---- showing ----

    def _refresh(self) -> None:
        self.nav.show_list(self._doc.hosts if self._doc else None)
        self._show_hosts()

    def _show_hosts(self) -> None:
        self.table.show_hosts(self._visible_hosts())

    def _visible_hosts(self) -> tuple[Host, ...]:
        if self._doc is None:
            return ()
        hosts, current = self._doc.hosts, self.nav.current_filter()
        if current.kind == "group" and current.value:
            return hosts.hosts_in(current.value)
        if current.kind == "tag":
            return tuple(h for h in hosts.hosts if current.value in h.tags)
        return hosts.hosts

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
        for action in (a.connect_vnc, a.copy_address, a.copy_name):
            action.setEnabled(selected > 0)  # read-only lists can still connect
        a.forget_passwords.setEnabled(bool(self.connector.credentials))
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
        if doc.read_only:
            parts.append(_("read-only"))
        if self._paths.portable:
            parts.append(_("portable mode"))
        self._list_label.setText(" · ".join(parts))

    # ---- right-click menus ----

    def _host_menu(self, position: QPoint) -> None:
        a = self.commands
        menu = QMenu(self)
        menu.addAction(a.connect_vnc)
        menu.setDefaultAction(a.connect_vnc)  # bold: what double-click and Enter do
        menu.addSeparator()
        menu.addActions([a.copy_address, a.copy_name])
        hosts = self._selected_hosts()
        if hosts and self._doc is not None:
            menu.addSeparator()
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
        menu.addSeparator()
        menu.addActions([a.edit, a.remove])
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _group_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self.commands.add_group)
        group_id = self.nav.selected_group_id()
        group = self._doc.hosts.group(group_id) if self._doc and group_id else None
        if group is not None and self._doc is not None:
            menu.addSeparator()
            follow = self.connector.inherited_label(
                *self._doc.hosts.group_profile(group.parent, self._profile_exists)
            )
            self._add_profile_menu(
                menu, {group.profile}, follow, lambda p: self.set_group_profile(group.id, p)
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
        self._prefs["view"] = {
            "groups": self.commands.show_groups.isChecked(),
            "details": self.commands.show_details.isChecked(),
            "status_bar": self.commands.show_status_bar.isChecked(),
        }
        self._save_prefs()
        super().closeEvent(event)
