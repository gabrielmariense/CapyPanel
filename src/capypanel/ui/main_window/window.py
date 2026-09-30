"""The main window: panes, menus, and opening and editing host lists."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QPoint
from PySide6.QtGui import QActionGroup, QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
)

from capypanel import __version__
from capypanel.core import settings
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.listfile import HostListChangedError, HostListFileError
from capypanel.core.hosts.locations import ListKind
from capypanel.core.hosts.model import Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.ui.hosts import HostDialog, confirm
from capypanel.ui.main_window.actions import create_actions
from capypanel.ui.main_window.host_views import (
    DetailsPane,
    HostTable,
    NavigationPane,
    group_path,
)
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)
LIST_FILTER = "Host lists (*.json);;All files (*)"


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: settings.Paths,
        prefs: dict[str, Any],
        *,
        registry: themes.Registry | None = None,
        open_last: bool = True,
    ):
        super().__init__()
        self._paths = paths
        self._prefs = prefs
        self.registry = registry if registry is not None else themes.Registry()
        self._doc: OpenList | None = None
        self._default_list = locations.default_list_path()
        self._personal_list = locations.personal_list_path(paths)

        self.commands = create_actions(self)
        self.nav = NavigationPane()
        self.table = HostTable()
        self.details = DetailsPane()
        self._splitter = QSplitter()
        for pane in (self.nav, self.table, self.details):
            self._splitter.addWidget(pane)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([220, 640, 280])
        self.setCentralWidget(self._splitter)
        self._list_label = QLabel()
        self.statusBar().addWidget(self._list_label, 1)

        self._build_menus()
        self._connect()
        self._restore_layout()
        if open_last:
            self._open_startup_list()
        self._refresh()

    # ---- building ----

    def _build_menus(self) -> None:
        a = self.commands
        file_menu = self.menuBar().addMenu(_("&File"))
        file_menu.addActions([a.new_list, a.open_list])
        self._recent_menu = file_menu.addMenu(_("&Recent lists"))
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(a.exit)

        inventory = self.menuBar().addMenu(_("&Inventory"))
        inventory.addActions([a.add_host, a.add_group])
        inventory.addSeparator()
        inventory.addActions([a.edit, a.remove])

        view = self.menuBar().addMenu(_("&View"))
        view.addActions([a.show_groups, a.show_details, a.show_status_bar])
        view.addSeparator()
        self._theme_menu = view.addMenu(_("&Theme"))
        self._theme_group = QActionGroup(self)
        previous_engine = None
        for theme in self.registry.all():
            if previous_engine and theme.engine != previous_engine:
                self._theme_menu.addSeparator()  # native themes, then the app's own looks
            previous_engine = theme.engine
            item = self._theme_menu.addAction(theme.title())
            item.setCheckable(True)
            item.setData(theme.id)
            item.setChecked(theme.id == themes.current().id)
            self._theme_group.addAction(item)
        self._theme_group.triggered.connect(lambda item: self.set_theme(item.data()))

    def _connect(self) -> None:
        a = self.commands
        a.new_list.triggered.connect(self.new_list)
        a.open_list.triggered.connect(self._ask_open_list)
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
        recent = locations.recent_lists(self._prefs)
        if recent and recent[0].exists() and self.open_list(recent[0], quiet=True):
            return
        if self._personal_list.exists():
            self.open_list(self._personal_list)
        else:
            self._create_list(self._personal_list, replace_existing=False)

    def open_list(self, path: Path, *, quiet: bool = False) -> bool:
        kind = self._kind(path)
        try:
            doc = OpenList.open(path, read_only=kind is ListKind.DEFAULT)
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
            self, _("New host list"), str(self._personal_list.parent), LIST_FILTER
        )
        if name:
            path = Path(name)
            # The file dialog already asked before choosing an existing file.
            self._create_list(path, replace_existing=path.exists())

    def _ask_open_list(self) -> None:
        start = self._doc.path.parent if self._doc else self._personal_list.parent
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Open host list"), str(start), LIST_FILTER
        )
        if name:
            self.open_list(Path(name))

    def _create_list(self, path: Path, *, replace_existing: bool) -> None:
        try:
            doc = OpenList.create(path, replace_existing=replace_existing)
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't create “{path}”: {error}").format(path=path, error=e))
            return
        self._use(doc)

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
        dialog = HostDialog(self, base, default_group=self.nav.selected_group_id())
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
        dialog = HostDialog(self, doc.hosts, host)
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
                "Its {n} host will be removed too.", "Its {n} hosts will be removed too.", count
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
            _("The list was changed"),
            _(
                "Someone else saved changes to this list after you opened it, so your change "
                "wasn't saved. You can save your version as a separate copy, or reload the list "
                "with their changes."
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
                LIST_FILTER,
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

    # ---- look ----

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)
        for item in self._theme_group.actions():
            item.setChecked(item.data() == theme.id)
        self._prefs["theme"] = theme.id
        self._save_prefs()
        log.info("Theme: %s", theme.id)

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
            self.details.show_host(hosts[0], group_path(self._doc.hosts, hosts[0].group), 1)
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
        if doc is None:
            self.setWindowTitle(f"CapyPanel {__version__}")
            self._list_label.setText(_("No host list is open."))
            return
        self.setWindowTitle(f"{doc.path.name} — CapyPanel {__version__}")
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
        menu = QMenu(self)
        menu.addActions([self.commands.edit, self.commands.remove])
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _group_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction(self.commands.add_group)
        if self.nav.selected_group_id():
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
