"""The list workspace: the Groups panel, the items (search above the table) and the Details panel,
with everything about lists and groups. A list tool subclasses it and fills in its own parts: its
table, Details panel, texts, add and edit dialog, search fields and right-click items."""

import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import files, winsec
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.listfile import HostListChangedError, HostListFileError
from capypanel.core.hosts.locations import ListKind
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ManageGroupsDialog, TreeMenu, fill_host_move_menu, fill_move_menu
from capypanel.ui.hosts import confirm, group_path, list_file_filter
from capypanel.ui.list_workspace.actions import ListActions
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import ItemTable, NavigationPane, SearchBox
from capypanel.ui.list_workspace.splitter import PaneSplitter
from capypanel.ui.main_window.tool import Shell, Tool
from capypanel.ui.main_window.toolbar import ToolBar
from capypanel.ui.menus import MenuCombo, popup
from capypanel.ui.new_list import ask_new_list

log = logging.getLogger(__name__)


class ListWorkspace(Tool):
    # Panel widths at a normal font size; a bigger font scales them up.
    PANES_DEFAULT = (220, 340)  # Groups, Details
    PANES_MINIMUM = (180, 300, 260)  # Groups, the table, Details

    def __init__(
        self,
        shell: Shell,
        *,
        commands: ListActions,
        toolbar: ToolBar,
        table: ItemTable,
        details: DetailsPanel,
    ):
        super().__init__(shell, toolbar)
        self._paths = shell.paths
        self._list_commands = commands
        self._doc: OpenList | None = None
        self._default_list = shell.paths.default_list
        self._personal_list = shell.paths.personal_list
        self.search = SearchBox()
        self.nav = NavigationPane(self.all_items_text)
        # The list dropdown, on top of the Groups panel: switch lists, make or open one.
        self.list_picker = MenuCombo()
        self.list_picker.setObjectName("listPicker")
        self.list_picker.menu().setToolTipsVisible(True)  # each list's path
        self.list_picker.menu().aboutToShow.connect(self._fill_list_menu)
        nav_layout = self.nav.layout()
        assert isinstance(nav_layout, QVBoxLayout)
        nav_layout.insertWidget(0, self.list_picker)
        self.table = table
        self._search_timer = QTimer(self)  # waits for a pause in typing, then filters
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self.details = details
        self.details.copied.connect(
            lambda text: shell.show_message(_("Copied: {text}").format(text=text), 5000)
        )
        self.splitter = PaneSplitter()
        # The search box is a box of its own above the table, styled like the panels.
        self.items_pane = QWidget()
        column = QVBoxLayout(self.items_pane)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.search)
        column.addWidget(self.table)
        for pane in (self.nav, self.items_pane, self.details):
            self.splitter.addWidget(pane)
        self.splitter.setStretchFactor(1, 1)
        # Dragged all the way, a panel would vanish; View hides panels on purpose instead.
        self.splitter.setChildrenCollapsible(False)
        self._size_panes()
        self._default_pane_sizes(1100)
        margins = QVBoxLayout(self)
        margins.setContentsMargins(8, 4, 8, 4)  # the same gap above and below the panels
        margins.addWidget(self.splitter)
        self._connect_list()

    def _connect_list(self) -> None:
        a = self._list_commands
        a.new_list.triggered.connect(self.new_list)
        a.open_list.triggered.connect(self.open_list_file)
        a.add_group.triggered.connect(self.add_group)
        a.manage_groups.triggered.connect(self.manage_groups)
        a.edit.triggered.connect(self.edit_selected)
        a.remove.triggered.connect(self.remove_selected)
        # Not in any menu bar menu, so their shortcuts (F2, Del, Ctrl+Shift+N, Ctrl+O) live
        # here: toolbar menus only take keys while they're open.
        self.addActions([a.edit, a.remove, a.add_group, a.open_list])
        a.show_groups.toggled.connect(self.nav.setVisible)
        a.show_tags.toggled.connect(self.nav.set_tags_visible)
        a.show_details.toggled.connect(self.details.setVisible)
        # The toolbar follows the end of the panels, wherever they are.
        for toggled in (a.show_groups.toggled, a.show_details.toggled):
            toggled.connect(self.align_toolbar_later)
        self.splitter.splitterMoved.connect(self.align_toolbar_later)
        self.splitter.edge_double_clicked.connect(self._fit_pane)
        self.nav.add_group_button.clicked.connect(self.add_top_group)  # on the Groups heading
        self.nav.filter_changed.connect(self._filter_picked)
        self.search.textChanged.connect(self._search_timer.start)
        self._search_timer.timeout.connect(self._show_items)
        self.search.to_results.connect(self._to_results)
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        # Esc ends a search wherever the focus is, not only in the box.
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._end_search)
        self.nav.groups.customContextMenuRequested.connect(self._group_menu)
        self.nav.groups.rearranged.connect(self._groups_dragged)
        self.nav.groups.hosts_dropped.connect(self.move_items)
        self.nav.everything.hosts_dropped.connect(self.move_items)  # onto "No group"
        self.nav.groups_heading.group_dropped.connect(lambda g: self.move_group(g, None))
        self.nav.groups_heading.customContextMenuRequested.connect(self._heading_menu)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._item_menu)
        self.table.columns_changed.connect(self._save_columns)
        self.table.columns_changed.connect(self._columns_shown)  # a search covers only those
        self.table.itemDoubleClicked.connect(lambda *_args: self.activate_selected())

    # ---- what a tool says: texts ----

    def all_items_text(self) -> str:
        """Pinned on top of the Groups panel: "All hosts"."""
        raise NotImplementedError

    def items_text(self, n: int) -> str:
        """A count of items: "{n} hosts"."""
        raise NotImplementedError

    def remove_items_text(self, items: Sequence[Host]) -> tuple[str, str]:
        """Removing items: the question's title and text."""
        raise NotImplementedError

    def no_list_text(self) -> str:
        """The status bar with no list open: "No host list is open."."""
        raise NotImplementedError

    def open_list_title(self) -> str:
        """The title of Open list…'s file dialog."""
        raise NotImplementedError

    def manage_lists_text(self) -> str:
        """The list dropdown's last item, which opens the tool's lists page in Settings."""
        raise NotImplementedError

    def search_fields(self) -> tuple[list[str], str]:
        """What the search box searches, each a lower-case word, and its tooltip."""
        raise NotImplementedError

    # ---- what a tool says: behaviour ----

    def add_item(self) -> None:
        raise NotImplementedError

    def add_item_action(self) -> QAction:
        """Offered on the table's empty space, before Add group."""
        raise NotImplementedError

    def edit_item(self, item: Host) -> None:
        raise NotImplementedError

    def activate_selected(self) -> None:
        """A double-click (and Enter, where the tool adds it): what the items are for."""

    def matches(self, item: Host, needle: str) -> bool:
        """Whether a search finds an item: only what can be seen, and the notes."""
        return needle in item.name.casefold() or needle in item.notes.casefold()

    def show_details(self, items: Sequence[Host]) -> None:
        """The Details panel for the items selected."""

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        """Right-click on items: use, copy, then managing them (add_copy_menu, add_move_menu)."""

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        """A group's right-click menu, between Add group and Show this group first."""

    def copy_action(self, key: str) -> QAction | None:
        """Copy ▸ uses this command for column `key` (to show its shortcut), if there is one."""
        return None

    def list_switched(self) -> None:
        """Another list was opened: anything kept about the last one's items is stale."""

    def update_tool_state(self, writable: bool, selected: int) -> None:
        """Enables the tool's own commands."""

    def status_extras(self, doc: OpenList) -> list[str]:
        """Parts of the status bar after the item count."""
        return []

    # ---- layout ----

    def restore_layout(self) -> None:
        splitter = self.prefs.get("main_splitter")
        if isinstance(splitter, str):
            self.splitter.restoreState(QByteArray.fromBase64(splitter.encode()))
            # Restoring turns collapsing back on: a panel dragged to the edge vanished.
            self.splitter.setChildrenCollapsible(False)
        view = self.prefs.get("view")
        view = view if isinstance(view, dict) else {}
        for key, action in self.view_choices().items():
            action.setChecked(bool(view.get(key, True)))
        a = self._list_commands
        self.nav.set_tags_visible(a.show_tags.isChecked())
        self.table.set_widths(self.prefs.get("column_widths"))
        self.table.set_hidden_columns(self.prefs.get("hidden_columns"))
        self._columns_shown()
        self.nav.setVisible(a.show_groups.isChecked())
        self.details.setVisible(a.show_details.isChecked())

    def view_choices(self) -> dict[str, QAction]:
        """View menu ticks, by the key they're saved under."""
        a = self._list_commands
        return {"groups": a.show_groups, "tags": a.show_tags, "details": a.show_details}

    def view_actions(self) -> list[list[QAction]]:
        a = self._list_commands
        return [[a.show_groups, a.show_tags, a.show_details]]

    def _scale(self) -> float:
        return max(1.0, self.fontMetrics().height() / 16)

    def _size_panes(self) -> None:
        """Minimum widths, so no panel can be dragged too narrow to read."""
        for pane, width in zip(
            (self.nav, self.items_pane, self.details), self.PANES_MINIMUM, strict=True
        ):
            pane.setMinimumWidth(round(width * self._scale()))

    def _default_pane_sizes(self, total: int) -> None:
        groups, details = (round(w * self._scale()) for w in self.PANES_DEFAULT)
        self.splitter.setSizes([groups, max(total - groups - details, 1), details])

    def _fit_pane(self, edge: int) -> None:
        """A double-click on the Groups panel's or the items panel's right edge: that panel as
        wide as its content, the panel on its right taking the rest, never below its minimum."""
        left, right = self.splitter.widget(edge - 1), self.splitter.widget(edge)
        if left is None or right is None:
            return
        if left is self.nav:
            natural = self.nav.natural_width()
        elif left is self.items_pane:
            natural = self.table.natural_width()
        else:
            return
        sizes = self.splitter.sizes()
        total = sizes[edge - 1] + sizes[edge]
        wanted = min(max(natural, left.minimumWidth()), total - right.minimumWidth())
        sizes[edge - 1], sizes[edge] = wanted, total - wanted
        self.splitter.setSizes(sizes)
        self.align_toolbar_later()

    def restyle(self) -> None:
        """After a theme switch: its font may be bigger, and it pads the toolbar differently."""
        self._size_panes()
        super().restyle()

    def toolbar_anchor(self) -> QWidget:
        return self.splitter

    def save_state(self) -> None:
        self.prefs["view"] = {k: a.isChecked() for k, a in self.view_choices().items()}
        self.prefs["main_splitter"] = self.splitter.saveState().toBase64().toStdString()
        self.prefs["column_widths"] = self.table.widths()
        self._remember_view()

    def _save_columns(self) -> None:
        self.prefs["hidden_columns"] = self.table.hidden_columns()
        self._save_prefs()

    # ---- opening lists ----

    @property
    def document(self) -> OpenList | None:
        return self._doc

    def open_startup_list(self) -> None:
        """The chosen list (normally the last used), else the default, else the personal one."""
        prefs = self.prefs
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
            locations.forget_list(self.prefs, path)
            self._error(_("The list “{path}” doesn't exist anymore.").format(path=path), quiet)
            return False
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't open “{path}”: {error}").format(path=path, error=e), quiet)
            return False
        self._use(doc)
        return True

    def new_list(self) -> None:
        """The list dropdown's New list…: shared, personal or elsewhere, as in Settings."""
        path = ask_new_list(
            self, shared_dir=self._paths.shared_lists_dir, user_dir=self._paths.user_lists_dir
        )
        if path is not None:  # replacing an existing file was asked already
            self._create_list(path, replace_existing=path.exists())

    def open_list_file(self) -> None:
        """The list dropdown's Open list… (Ctrl+O): any list file, which then stays in the
        dropdown."""
        shared = self._paths.shared_lists_dir
        start = shared if shared.is_dir() else self._personal_list.parent
        name, _filter = QFileDialog.getOpenFileName(
            self, self.open_list_title(), str(start), list_file_filter()
        )
        if name:
            self.open_list(Path(name))

    # ---- the list dropdown ----

    def found_lists(self, *, hidden: bool = False) -> list[Path]:
        """The lists in the lists folders; the ones removed in Settings only when `hidden`."""
        found = locations.found_lists(self._paths.shared_lists_dir, self._paths.user_lists_dir)
        return found if hidden else locations.without_hidden(self.prefs, found)

    def _available_lists(self) -> list[Path]:
        return locations.available_lists(
            self.prefs,
            default=self._default_list,
            personal=self._personal_list,
            found=self.found_lists(),
        )

    def _list_name(self, path: Path) -> str:
        lists = self._available_lists()
        if not any(locations.same_path(path, p) for p in lists):
            lists.append(path)
        names = locations.list_names(
            lists, default=self._default_list, personal=self._personal_list
        )
        return next(n for p, n in zip(lists, names, strict=True) if locations.same_path(p, path))

    def _fill_list_menu(self) -> None:
        """Every list, the open one ticked (its path in the tooltip), then making or opening
        one, and managing them in Settings."""
        a = self._list_commands
        menu = self.list_picker.menu()
        menu.clear()
        lists = self._available_lists()
        names = locations.list_names(
            lists, default=self._default_list, personal=self._personal_list
        )
        current = self._doc.path if self._doc else None
        picks = QActionGroup(menu)
        for path, name in zip(lists, names, strict=True):
            item = menu.addAction(name.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current is not None and locations.same_path(path, current))
            item.setToolTip(str(path))
            picks.addAction(item)
            item.triggered.connect(lambda _c=False, p=path: self._pick_list(p))
        menu.addSeparator()
        menu.addActions([a.new_list, a.open_list])
        menu.addSeparator()
        manage = menu.addAction(self.manage_lists_text())
        manage.triggered.connect(lambda: self._shell.open_settings("host_lists"))

    def _pick_list(self, path: Path) -> None:
        current = self._doc.path if self._doc else None
        if current is None or not locations.same_path(path, current):
            self.open_list(path)

    def _create_list(self, path: Path, *, replace_existing: bool, quiet: bool = False) -> bool:
        try:
            if self._kind(path) is ListKind.DEFAULT and not path.parent.exists():
                files.make_shared_folder(path.parent)  # read by all, changed only by admins
            doc = OpenList.create(path, replace_existing=replace_existing)
        except (HostListFileError, OSError) as e:
            self._error(_("Couldn't create “{path}”: {error}").format(path=path, error=e), quiet)
            return False
        self._use(doc)
        return True

    def _use(self, doc: OpenList) -> None:
        switched = self._doc is None or not locations.same_path(self._doc.path, doc.path)
        if switched:
            self._remember_view()  # where the list being left was
            self.list_switched()
            self._clear_search()
        self._doc = doc
        locations.remember_list(self.prefs, doc.path)
        hidden = locations.hidden_lists(self.prefs)
        if any(locations.same_path(doc.path, p) for p in hidden):  # opened again: listed again
            locations.set_hidden_lists(
                self.prefs, [p for p in hidden if not locations.same_path(doc.path, p)]
            )
        in_folder = any(locations.same_path(doc.path, p) for p in self.found_lists(hidden=True))
        if self._kind(doc.path) is ListKind.SHARED and not in_folder:  # in the dropdown now
            # Only lists from elsewhere: before any was added, this falls back to the recent ones.
            added = [
                p for p in locations.added_lists(self.prefs) if self._kind(p) is ListKind.SHARED
            ]
            locations.set_added_lists(self.prefs, [*added, doc.path])
        self._save_prefs()
        log.info("Opened list %s (read-only=%s)", doc.path, doc.read_only)
        self.refresh()
        if switched:
            self._show_first(doc)

    # ---- what a list shows first ----

    def _show_first(self, doc: OpenList) -> None:
        """Everything, where this list was left, or its chosen group (Settings)."""
        view = locations.list_view(self.prefs, doc.path)
        if view.show == locations.SHOW_GROUP:
            self.nav.select_group(view.group)
        elif view.show == locations.SHOW_LAST:
            self.nav.show_view(*view.last)
        else:
            self.nav.show_view("all", "")
        self._show_items()
        self._selection_changed()

    def _remember_view(self) -> None:
        if self._doc is None:
            return
        shown = self.nav.current_filter()
        view = locations.list_view(self.prefs, self._doc.path)
        last = (shown.kind, shown.value or "")
        locations.set_list_view(self.prefs, self._doc.path, replace(view, last=last))

    def start_view(self) -> tuple[str, str] | None:
        """What the open list shows first, for Settings."""
        if self._doc is None:
            return None
        view = locations.list_view(self.prefs, self._doc.path)
        return view.show, view.group

    def set_first_group(self, group_id: str, first: bool) -> None:
        """Right-click a group > Show this group first: ticked, the list opens on it."""
        if self._doc is None:
            return
        view = locations.list_view(self.prefs, self._doc.path)
        if first:
            view = replace(view, show=locations.SHOW_GROUP, group=group_id)
        elif view.show == locations.SHOW_GROUP and view.group == group_id:
            view = replace(view, show=locations.SHOW_ALL)
        locations.set_list_view(self.prefs, self._doc.path, view)
        self._save_prefs()

    def apply_list_prefs(
        self,
        start_list: str,
        start_view: tuple[str, str] | None,
        added_lists: list[Path],
        hidden_lists: list[Path],
    ) -> None:
        """Choices made in Settings about lists, kept at once (the caller saves them)."""
        self.prefs[locations.START_KEY] = start_list
        if start_view is not None and self._doc is not None:  # for the list open now
            show, group = start_view
            view = locations.list_view(self.prefs, self._doc.path)
            locations.set_list_view(
                self.prefs, self._doc.path, replace(view, show=show, group=group)
            )
        locations.set_added_lists(self.prefs, added_lists)
        locations.set_hidden_lists(self.prefs, hidden_lists)

    # ---- editing groups and removing ----

    def add_group(self) -> None:
        """Inside the picked group, or at the top level when none is."""
        self._add_group(self.nav.selected_group_id())

    def add_top_group(self) -> None:
        """The + by the Groups heading, its right-click menu, and the empty space below."""
        self._add_group(None)

    def _add_group(self, parent: str | None) -> None:
        doc = self._writable()
        if doc is None:
            return
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
        items = self.selected_items()
        if self.nav.groups.hasFocus() and group_id:
            self.rename_group(group_id)
        elif len(items) == 1:
            self.edit_item(items[0])
        elif group_id and not items:
            self.rename_group(group_id)

    def remove_selected(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        group_id = self.nav.selected_group_id()
        items = self.selected_items()
        if (self.nav.groups.hasFocus() or not items) and group_id:
            self.remove_group(group_id)
        elif items:
            self.remove_items(items)

    def remove_items(self, items: Sequence[Host]) -> None:
        doc = self._writable()
        if doc is None or not items:
            return
        title, text = self.remove_items_text(items)
        if confirm(self, title, text, _("Remove")):
            self._commit(doc.hosts.remove_hosts(h.id for h in items))

    def remove_group(self, group_id: str) -> None:
        doc = self._writable()
        group = doc.hosts.group(group_id) if doc else None
        if doc is None or group is None:
            return
        items = len(doc.hosts.hosts_in(group_id))
        groups = len(doc.hosts.subtree(group_id)) - 1
        if not items and not groups:
            text = _("Remove the empty group “{name}”?").format(name=group.name)
            if confirm(self, _("Remove group"), text, _("Remove")):
                self._commit(doc.hosts.remove_group(group_id))
            return
        choice = self._ask_how_to_remove(group_id, groups, items)
        if choice is None:
            return
        how, into = choice
        try:
            new = doc.hosts.remove_group(group_id, keep_contents=how == "move", into=into)
        except HostListRuleError as e:
            self._error(str(e))
            return
        self._commit(new)

    def _ask_how_to_remove(
        self, group_id: str, groups: int, items: int
    ) -> tuple[str, str | None] | None:
        """Move what's inside somewhere (its parent is ticked) or remove everything.
        Returns ("move", group id, or NO_GROUP for the top level), ("all", None), or None for
        Cancel."""
        assert self._doc is not None
        host_list = self._doc.hosts
        group = host_list.group(group_id)
        assert group is not None
        inside = [
            ngettext("{n} group", "{n} groups", groups).format(n=groups) if groups else "",
            self.items_text(items) if items else "",
        ]
        box = QMessageBox(
            QMessageBox.Icon.Question,
            _("Remove group"),
            _("“{name}” holds {inside}. What should happen to them?").format(
                name=group.name, inside=_(" and ").join(i for i in inside if i)
            ),
            parent=self,
        )
        if groups:
            box.setInformativeText(
                _("With No group, the groups inside it go directly under Groups.")
            )
        chosen: list[tuple[str, str | None]] = []
        move = box.addButton(_("&Move them to"), QMessageBox.ButtonRole.ActionRole)
        menu = TreeMenu("", move)
        # The same menu as moving items, without what's being removed.
        fill_host_move_menu(
            menu,
            host_list,
            lambda target: chosen.append(("move", target)),
            skip=host_list.subtree(group_id),
        )
        parent = group.parent or NO_GROUP  # where things go when a group goes
        for item in menu.actions():
            if item.data() == parent:
                item.setChecked(True)
                menu.marked = item
        menu.triggered.connect(lambda _item: box.done(0))
        move.setMenu(menu)
        everything = box.addButton(_("Remove everything"), QMessageBox.ButtonRole.DestructiveRole)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        run_modal(box)
        if chosen:
            return chosen[0]
        return ("all", None) if box.clickedButton() is everything else None

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
        self.refresh()
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
        run_modal(box)
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
        self.refresh()

    def manage_groups(self) -> None:
        """Inventory > Manage groups…: reorder and nest every group at once."""
        doc = self._writable()
        if doc is None:
            return
        dialog = ManageGroupsDialog(self, doc.hosts)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
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
            self.refresh()  # puts the tree back as it was
            return
        self._commit(new)

    def move_group(self, group_id: str, parent: str | None) -> None:
        """Into `parent`, or the top level (None), with everything inside it."""
        doc = self._writable()
        if doc is None:
            return
        try:
            new = doc.hosts.move_group(group_id, parent)
        except HostListRuleError as e:
            self._error(str(e))
            return
        if new is not doc.hosts and self._commit(new):
            self.nav.select_group(group_id)
            self._show_items()

    def move_items(self, ids: list[str], group_id: str) -> None:
        """Items dragged onto a group, or moved with right-click > Move to (NO_GROUP: out of
        every group)."""
        doc = self._writable()
        if doc is None or (group_id != NO_GROUP and doc.hosts.group(group_id) is None):
            return
        self._commit(doc.hosts.move_hosts(ids, group_id))

    # ---- showing ----

    def retranslate(self) -> None:
        """Every text the panels show, in the current language."""
        self.nav.retranslate()
        self.table.retranslate()
        self.details.retranslate()
        self._columns_shown()
        self.refresh()  # rebuilds the lists ("All hosts"), details hint and status bar

    def refresh(self) -> None:
        self.nav.show_list(self._doc.hosts if self._doc else None)
        editable = self._writable() is not None  # read-only lists can't be rearranged
        self.nav.groups.set_editable(editable)
        self.table.set_editable(editable)
        self._show_items()

    def _show_items(self) -> None:
        self._search_timer.stop()
        needle = self._needle()
        items = self.visible_items()
        self.nav.set_searching(bool(needle))
        self.fill_table(items)
        self.table.set_search(needle)

    def fill_table(self, items: Sequence[Host]) -> None:
        self.table.show_items(items)

    def visible_items(self) -> tuple[Host, ...]:
        """The items the table shows: the search's results, or the group or tag picked."""
        if self._doc is None:
            return ()
        hosts, current = self._doc.hosts, self.nav.current_filter()
        if needle := self._needle():
            return tuple(h for h in hosts.hosts if self.matches(h, needle))
        if current.kind == "group" and current.value:
            return hosts.hosts_in(current.value)
        if current.kind == "nogroup":
            return tuple(h for h in hosts.hosts if h.group == NO_GROUP)
        if current.kind == "tag":
            return tuple(h for h in hosts.hosts if current.value in h.tags)
        return hosts.hosts

    # ---- searching ----

    def _needle(self) -> str:
        return self.search.text().strip().casefold()

    def _focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _clear_search(self) -> None:
        self.search.blockSignals(True)  # the caller shows the items once, right after
        self.search.clear()
        self.search.blockSignals(False)

    def _filter_picked(self) -> None:
        """Picking a group or tag on the left ends a search: it means browsing again."""
        self._clear_search()
        self._show_items()

    def _end_search(self) -> None:
        if self.search.text():
            self._clear_search()
            self._show_items()  # back to the group or tag picked before, selection kept

    def _columns_shown(self) -> None:
        self.search.set_fields(*self.search_fields())
        if self._needle():
            self._show_items()

    def _to_results(self) -> None:
        """Down or Enter in the search box: the first result gets the focus, never an action."""
        first = self.table.topLevelItem(0)
        if first is not None:
            self.table.setCurrentItem(first)
            self.table.setFocus(Qt.FocusReason.TabFocusReason)

    def selected_items(self) -> list[Host]:
        if self._doc is None:
            return []
        found = (self._doc.hosts.host(i) for i in self.table.selected_ids())
        return [h for h in found if h is not None]

    def _selection_changed(self) -> None:
        self.show_details(self.selected_items())
        self._update_state()

    def _update_state(self) -> None:
        doc = self._doc
        writable = doc is not None and not doc.read_only
        selected = len(self.table.selected_ids())
        group_picked = self.nav.selected_group_id() is not None
        a = self._list_commands
        a.add_group.setEnabled(writable)
        self.nav.add_group_button.setEnabled(writable)
        a.edit.setEnabled(writable and (selected == 1 or group_picked))
        a.remove.setEnabled(writable and (selected > 0 or group_picked))
        self.update_tool_state(writable, selected)
        if doc is None:
            self.title_changed.emit("")
            self.status_label.setText(self.no_list_text())
            self.list_picker.setText(_("No list open"))
            return
        name = self._list_name(doc.path)
        self.title_changed.emit(name)
        self.list_picker.setText(name)
        self.list_picker.setToolTip(str(doc.path))
        parts = [
            f"{self._kind_label(self._kind(doc.path))} — {doc.path}",
            self.items_text(len(doc.hosts.hosts)),
            *self.status_extras(doc),
        ]
        if self._needle():
            found = self.table.topLevelItemCount()
            parts.append(ngettext("{n} found", "{n} found", found).format(n=found))
        parts.append(ngettext("{n} selected", "{n} selected", selected).format(n=selected))
        if doc.read_only:
            parts.append(_("read-only"))
        if self._paths.portable:
            parts.append(_("portable mode"))
        self.status_label.setText(" · ".join(parts))

    def title(self) -> str:
        """The open list's name, or "" with none open."""
        return self._list_name(self._doc.path) if self._doc is not None else ""

    # ---- right-click menus ----

    def _item_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        if self.table.itemAt(position) is None:  # empty space: what can be added here
            self.table.clearSelection()
            menu.addActions([self.add_item_action(), self._list_commands.add_group])
        else:
            self.fill_item_menu(menu, self.selected_items())
        popup(menu, self.table.viewport().mapToGlobal(position))

    def add_copy_menu(self, menu: QMenu) -> None:
        """Copy ▸ every column the table shows, one line per selected item. Wherever the menu
        was opened (also from the keyboard), the same items."""
        copy = menu.addMenu(_("Co&py"))
        rows = sorted(self.table.selectedItems(), key=self.table.indexOfTopLevelItem)
        for column, key in enumerate(self.table.COLUMNS):
            if self.table.isColumnHidden(column):
                continue
            if (action := self.copy_action(key)) is not None:
                copy.addAction(action)
                continue
            item = copy.addAction(self.table.headerItem().text(column))
            item.triggered.connect(
                lambda _c=False, n=column: QGuiApplication.clipboard().setText(
                    "\n".join(r.text(n) for r in rows)
                )
            )

    def add_move_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        """Move to: "No group", then the groups as a tree; where they all are is ticked."""
        if not items or self._doc is None:
            return
        move = TreeMenu(_("&Move to"), menu)
        menu.addMenu(move)
        move.setEnabled(self._writable() is not None)
        ids = [h.id for h in items]
        places = {h.group for h in items}
        current = places.pop() if len(places) == 1 else None
        fill_host_move_menu(
            move, self._doc.hosts, lambda g: self.move_items(ids, g), current=current
        )

    def _heading_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        self._add_top_group_item(menu)
        menu.addAction(self._list_commands.manage_groups)
        popup(menu, self.nav.groups_heading.mapToGlobal(position))

    def _add_top_group_item(self, menu: QMenu) -> None:
        # Not the Add group command: that one adds inside the picked group.
        item = menu.addAction(self._list_commands.add_group.text())
        item.setEnabled(self._writable() is not None)
        item.triggered.connect(self.add_top_group)

    def _group_menu(self, position: QPoint) -> None:
        a = self._list_commands
        menu = QMenu(self)
        # Only the group under the mouse: empty space never acts on the one picked before.
        group_id = self.nav.group_at(position)
        if group_id is None:
            self._add_top_group_item(menu)
            menu.addAction(a.manage_groups)
            popup(menu, self.nav.groups.viewport().mapToGlobal(position))
            return
        self.nav.select_group(group_id)
        menu.addAction(a.add_group)  # inside the group under the mouse
        group = self._doc.hosts.group(group_id) if self._doc else None
        if group is not None and self._doc is not None:
            self.fill_group_menu(menu, group)
            menu.addSeparator()
            view = locations.list_view(self.prefs, self._doc.path)
            first = menu.addAction(_("Show this group &first"))
            first.setToolTip(_("The list opens on this group"))
            first.setCheckable(True)
            first.setChecked(view.show == locations.SHOW_GROUP and view.group == group.id)
            first.toggled.connect(lambda on: self.set_first_group(group.id, on))
            menu.addSeparator()  # managing it, in the item menu's order: edit, move, remove
            menu.addAction(a.edit)
            move = TreeMenu(_("&Move to"), menu)
            menu.addMenu(move)
            move.setEnabled(self._writable() is not None)
            fill_move_menu(move, self._doc.hosts, group.id, lambda p: self.move_group(group.id, p))
            menu.addAction(a.remove)
        popup(menu, self.nav.groups.viewport().mapToGlobal(position))

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
            self._shell.show_message(message, 10_000)
        else:
            QMessageBox.warning(self, "CapyPanel", message)

    def _save_prefs(self) -> None:
        self._shell.save_prefs()
