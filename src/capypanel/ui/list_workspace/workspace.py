import logging
from collections.abc import Sequence
from dataclasses import fields, replace
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QByteArray, QPoint, QRect, Qt, QTimer, Signal
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

from capypanel.core import files, settings, winsec
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.listfile import (
    HostListChangedError,
    HostListFileError,
    HostListKindError,
)
from capypanel.core.hosts.locations import ListKind
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostList, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.ui import help_links
from capypanel.ui.dialogs import run_modal
from capypanel.ui.export_hosts import Source
from capypanel.ui.groups import (
    ROLE_ID,
    ManageGroupsDialog,
    TreeMenu,
    fill_host_move_menu,
    fill_move_menu,
)
from capypanel.ui.hosts import MAX_TAG, confirm, group_path
from capypanel.ui.list_workspace.actions import ListActions
from capypanel.ui.list_workspace.customize import CustomizeDialog, Part, PartsTab
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import (
    SAMPLE_ID,
    ItemTable,
    NavigationPane,
    SearchBox,
    TagStrip,
    is_sample,
)
from capypanel.ui.list_workspace.splitter import PaneSplitter
from capypanel.ui.list_workspace.texts import EmptyTexts, ListTexts
from capypanel.ui.main_window.tool import Shell, Tool
from capypanel.ui.main_window.toolbar import ToolBar
from capypanel.ui.menus import StayOpenMenu, popup
from capypanel.ui.new_list import ask_new_list
from capypanel.ui.shortcuts import KeyCommand, portable

log = logging.getLogger(__name__)

HIDDEN_KEY = "details_hidden"


class ListWorkspace(Tool):
    PANES_DEFAULT = (220, 340)
    PANES_MINIMUM = (180, 300, 260)
    LISTS_FROM: ClassVar[str] = ""
    list_changed = Signal()

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
        self._real_doc: OpenList | None = None
        self._shown_for_guide: list[QAction] = []
        self._hold_fill = False
        self._fill_waiting = False
        leader = shell.tool(self.LISTS_FROM) if self.LISTS_FROM else None
        self._leader = leader if isinstance(leader, ListWorkspace) else None
        self._places = shell.paths.lists(self.list_kind())
        self._default_list = self._places.default
        self._personal_list = self._places.personal
        if self._leader is None:
            self._make_lists_folders()
        self.search = SearchBox()
        self.nav = NavigationPane(lambda: self.list_texts().everything, self.ICON)
        self.list_picker = self.nav.add_list_picker(self._fill_list_menu)
        self.table = table
        self.sort_groups_action = QAction(self)
        self.sort_groups_action.setText(_("&Sort groups A–Z"))
        self.sort_menu, self.columns_menu = QMenu(self), StayOpenMenu(self)
        for menu, fill in ((self.sort_menu, table.fill_sort_menu),
                           (self.columns_menu, table.fill_columns_menu)):  # fmt: skip
            menu.aboutToShow.connect(lambda m=menu, f=fill: (m.clear(), f(m)))
        self.sort_menu.setTitle(_("So&rt by"))
        self.columns_menu.setTitle(_("Co&lumns"))
        self.sort_groups_action.triggered.connect(self.sort_groups)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self.details = details
        self.details.copied.connect(self._say_copied)
        self.status_label.clicked.connect(self.copy_list_path)
        self.splitter = PaneSplitter()
        self.tag_strip = TagStrip()
        self.items_pane = QWidget()
        column = QVBoxLayout(self.items_pane)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(self.search)
        column.addWidget(self.tag_strip)
        column.addWidget(self.table)
        self._lay_out()
        # Dragged all the way, a panel would vanish; View hides panels on purpose instead.
        self.splitter.setChildrenCollapsible(False)
        self._size_panes()
        self._default_pane_sizes(1100)
        margins = QVBoxLayout(self)
        margins.setContentsMargins(8, 4, 8, 4)
        margins.addWidget(self.splitter)
        self._connect_list()
        if self._leader is not None:
            self._leader.list_changed.connect(self._follow)

    def _connect_list(self) -> None:
        a = self._list_commands
        a.new_list.triggered.connect(self.new_list)
        a.open_list.triggered.connect(self.open_list_file)
        a.add_group.triggered.connect(self.add_group)
        a.manage_groups.triggered.connect(self.manage_groups)
        a.edit.triggered.connect(self.edit_selected)
        a.remove.triggered.connect(self.remove_selected)
        # Toolbar menus take keys only while open: these shortcuts live here.
        self.addActions([a.edit, a.remove, a.add_group, a.open_list])
        a.show_groups.toggled.connect(self.nav.setVisible)
        a.show_tags.toggled.connect(self.nav.set_tags_visible)
        a.show_details.toggled.connect(self.details.setVisible)
        a.customize_details.triggered.connect(lambda: self.customize_details())
        self.details.customize_requested.connect(lambda: self.customize_details())
        self.details.customizable = bool(self.details_parts())
        for toggled in (a.show_groups.toggled, a.show_details.toggled):
            toggled.connect(self.align_toolbar_later)
        self.splitter.splitterMoved.connect(self.align_toolbar_later)
        self.splitter.edge_double_clicked.connect(self._fit_pane)
        self.nav.add_group_button.clicked.connect(self.add_top_group)
        self.nav.filter_changed.connect(self._filter_picked)
        for tree in (self.nav.everything, self.nav.groups):
            tree.itemClicked.connect(lambda *_a: self.list_to_front())
        self.list_picker.menu().triggered.connect(lambda *_a: self.list_to_front())
        self.tag_strip.clear_clicked.connect(self.nav.clear_tags)
        self.table.clear_tags_button.clicked.connect(self.nav.clear_tags)
        self.search.textChanged.connect(self._search_timer.start)
        self._search_timer.timeout.connect(self._show_items)
        self.search.to_results.connect(self._to_results)
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._end_search)
        self.nav.groups.customContextMenuRequested.connect(self._group_menu)
        self.nav.groups.rearranged.connect(self._groups_dragged)
        self.nav.groups.hosts_dropped.connect(self.move_items)
        self.nav.everything.hosts_dropped.connect(self.move_items)
        self.nav.groups_heading.group_dropped.connect(lambda g: self.move_group(g, None))
        self.nav.groups_heading.customContextMenuRequested.connect(self._heading_menu)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.customContextMenuRequested.connect(self._item_menu)
        self.table.columns_changed.connect(self._save_columns)
        self.table.columns_changed.connect(self._columns_shown)
        self.table.itemDoubleClicked.connect(lambda *_args: self.activate_selected())

    def list_texts(self) -> ListTexts:
        raise NotImplementedError

    def items_text(self, n: int) -> str:
        raise NotImplementedError

    def remove_items_text(self, items: Sequence[Host]) -> tuple[str, str]:
        raise NotImplementedError

    def search_fields(self) -> tuple[list[str], str]:
        raise NotImplementedError

    def selected_text(self, n: int) -> str:
        raise NotImplementedError

    def found_text(self, n: int) -> str:
        raise NotImplementedError

    def counted_text(self, name: str, n: int) -> str:
        raise NotImplementedError

    def selected_source_texts(self) -> tuple[str, str]:
        raise NotImplementedError

    def only_tags_text(self, shown: int, total: int) -> str:
        raise NotImplementedError

    def no_match_text(self) -> str:
        raise NotImplementedError

    def empty_texts(self) -> EmptyTexts:
        return EmptyTexts(
            _("This list is empty.\nAdd an item to start."),
            _("This list is empty."),
            _("This group is empty."),
            _("Nothing is outside a group."),
            _("Nothing matches “{text}”."),
        )

    def import_action(self) -> QAction | None:
        return None

    def typed_offer(self, typed: str, rows: Sequence[Host]) -> list[QAction]:
        return []

    def lists_page(self) -> str:
        raise NotImplementedError

    def add_item(self) -> None:
        raise NotImplementedError

    def add_item_action(self) -> QAction:
        raise NotImplementedError

    def edit_item(self, item: Host) -> None:
        raise NotImplementedError

    def activate_selected(self) -> None:
        pass

    def matches(self, item: Host, needle: str) -> bool:
        return needle in item.name.casefold() or needle in item.notes.casefold()

    def show_details(self, items: Sequence[Host]) -> None:
        pass

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        pass

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        pass

    def copy_action(self, key: str) -> QAction | None:
        return None

    def list_switched(self) -> None:
        pass

    def list_to_front(self) -> None:
        pass

    def update_tool_state(self, writable: bool, selected: int) -> None:
        pass

    def status_extras(self, doc: OpenList) -> list[str]:
        return []

    def _lay_out(self) -> None:
        for pane in (self.nav, self.items_pane, self.details):
            self.splitter.addWidget(pane)
        self.splitter.setStretchFactor(1, 1)

    def _restore_panes(self) -> None:
        splitter = self.prefs.get("main_splitter")
        if isinstance(splitter, str):
            self.splitter.restoreState(QByteArray.fromBase64(splitter.encode()))
            self.splitter.setChildrenCollapsible(False)

    def _save_panes(self) -> None:
        self.prefs["main_splitter"] = self.splitter.saveState().toBase64().toStdString()

    def restore_layout(self) -> None:
        self._restore_panes()
        view = self.prefs.get("view")
        view = view if isinstance(view, dict) else {}
        for key, action in self.view_choices().items():
            action.setChecked(bool(view.get(key, True)))
        a = self._list_commands
        self.nav.set_tags_visible(a.show_tags.isChecked())
        self.nav.restore_split(self.prefs.get("nav_splitter"))
        self.table.set_widths(self.prefs.get("column_widths"))
        self.table.set_hidden_columns(self.prefs.get("hidden_columns"))
        self._columns_shown()
        self.nav.setVisible(a.show_groups.isChecked())
        self.details.setVisible(a.show_details.isChecked())

    def view_choices(self) -> dict[str, QAction]:
        a = self._list_commands
        return {"groups": a.show_groups, "tags": a.show_tags, "details": a.show_details}

    def view_actions(self) -> list[list[QAction]]:
        a = self._list_commands
        panes = [a.show_groups, a.show_tags, a.show_details]
        if self.details_parts():
            panes.append(a.customize_details)
        return [panes, [self.sort_menu.menuAction(), self.columns_menu.menuAction()]]

    def key_commands(self) -> list[KeyCommand]:
        a = self._list_commands
        return [
            KeyCommand(
                f"{self.TOOL_ID}.{f.name}",
                getattr(a, f.name),
                self.TOOL_ID,
                portable(getattr(a, f.name).shortcut()),
            )
            for f in fields(a)
        ]

    def details_parts(self) -> list[Part]:
        return []

    def details_always(self) -> str:
        return ""

    def customize_tabs(self) -> list[tuple[str, QWidget]]:
        return []

    def hidden_parts(self) -> frozenset[str]:
        kept = self.prefs.get(HIDDEN_KEY)
        known = {part.key for part in self.details_parts()}
        if not isinstance(kept, list):
            return frozenset()
        return frozenset(k for k in kept if isinstance(k, str) and k in known)

    def set_hidden_parts(self, hidden: Sequence[str]) -> None:
        self.prefs[HIDDEN_KEY] = sorted(set(hidden))
        self._save_prefs()
        self._selection_changed()

    def customize_details(self, tab: int = 0, parent: QWidget | None = None) -> None:
        parts = PartsTab(self.details_parts(), sorted(self.hidden_parts()), self.details_always())
        parts.changed.connect(self.set_hidden_parts)
        dialog = CustomizeDialog(parent or self, parts, self.customize_tabs())
        dialog.show_tab(tab)
        run_modal(dialog)

    def _scale(self) -> float:
        return max(1.0, self.fontMetrics().height() / 16)

    def _size_panes(self) -> None:
        for pane, width in zip(
            (self.nav, self.items_pane, self.details), self.PANES_MINIMUM, strict=True
        ):
            pane.setMinimumWidth(round(width * self._scale()))
        self.details.setMinimumWidth(max(self.details.minimumWidth(), self.details.minimum_width()))

    def _default_pane_sizes(self, total: int) -> None:
        groups, details = (round(w * self._scale()) for w in self.PANES_DEFAULT)
        details = max(details, self.details.minimum_width())
        self.splitter.setSizes([groups, max(total - groups - details, 1), details])

    def _fit_pane(self, edge: int, splitter: PaneSplitter | None = None) -> None:
        splitter = splitter or self.splitter
        left, right = splitter.widget(edge - 1), splitter.widget(edge)
        if left is None or right is None:
            return
        if left is self.nav:
            natural = self.nav.natural_width()
        elif left is self.items_pane:
            natural = self.table.natural_width()
        else:
            return
        sizes = splitter.sizes()
        total = sizes[edge - 1] + sizes[edge]
        wanted = min(max(natural, left.minimumWidth()), total - right.minimumWidth())
        sizes[edge - 1], sizes[edge] = wanted, total - wanted
        splitter.setSizes(sizes)
        self.align_toolbar_later()

    def restyle(self) -> None:
        self._size_panes()
        super().restyle()

    def toolbar_anchor(self) -> QWidget:
        return self.splitter

    def save_state(self) -> None:
        self.prefs["view"] = {k: a.isChecked() for k, a in self.view_choices().items()}
        self._save_panes()
        self.prefs["nav_splitter"] = self.nav.split_state()
        self.prefs["column_widths"] = self.table.widths()
        self._remember_view()

    def _save_columns(self) -> None:
        self.prefs["hidden_columns"] = self.table.hidden_columns()
        self._save_prefs()

    def _make_lists_folders(self) -> None:
        try:
            shared = self._places.shared_dir
            if not shared.is_dir():
                lists = self._paths.lists_dir
                if not lists.is_dir() and files.can_create_files(lists.parent):
                    files.make_shared_folder(lists)
                if lists.is_dir() and files.can_create_files(lists):
                    files.make_shared_folder(shared)
            self._places.user_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.exception("Couldn't create the lists folders")

    @property
    def places(self) -> settings.ListPlaces:
        return self._places

    @property
    def document(self) -> OpenList | None:
        return self._doc

    @property
    def saved_document(self) -> OpenList | None:
        return self._real_doc if self._real_doc is not None else self._doc

    def list_kind(self) -> str:
        return self.LISTS_FROM or self.TOOL_ID

    def _owner(self) -> "ListWorkspace":
        return self._leader or self

    def _follow(self) -> None:
        doc = self._leader.saved_document if self._leader is not None else None
        if self._real_doc is not None:
            self._real_doc = doc if doc is not None else self._real_doc
            return
        switched = self._swap(doc)
        self.refresh()
        if switched and doc is not None:
            self._show_first(doc)

    @property
    def default_list(self) -> Path:
        return self._default_list

    @property
    def personal_list(self) -> Path:
        return self._personal_list

    def open_first_list(self) -> None:
        if self._leader is not None:
            self._follow()
            return
        self._hold_fill = True
        try:
            self.open_startup_list()
        finally:
            self._hold_fill = False
        self.refresh()

    def open_startup_list(self) -> None:
        prefs = self.prefs
        order = locations.startup_order(
            prefs, default=self._default_list, personal=self._personal_list
        )
        expected = prefs.get(locations.START_KEY, locations.START_LAST) != locations.START_LAST
        expected = expected or bool(locations.recent_lists(prefs))
        for index, path in enumerate(order):
            if not path.exists() and self._kind(path) is ListKind.SHARED:
                continue
            if self.open_list(path, quiet=True):
                if index and expected:
                    note = _("Couldn't open “{wanted}”, so “{opened}” was opened instead.")
                    self._error(note.format(wanted=order[0], opened=path), quiet=True)
                return

    def open_list(self, path: Path, *, quiet: bool = False) -> bool:
        if self._leader is not None:
            return self._leader.open_list(path, quiet=quiet)
        kind = self._kind(path)
        if kind is not ListKind.SHARED and not path.exists():
            return self._create_list(path, replace_existing=False, quiet=quiet)
        if kind is ListKind.DEFAULT and not winsec.made_by_trusted(path):
            note = _(
                "The default list was made by another user, so CapyPanel won't open it. An "
                "administrator can replace or delete “{path}”."
            )
            self._error(note.format(path=path), quiet, place="hosts-default-list-other-user")
            return False
        try:
            doc = OpenList.open(path, kind=self.list_kind())
        except FileNotFoundError:
            locations.forget_list(self.prefs, path)
            gone = _("The list “{path}” doesn't exist anymore, so it's no longer among your lists.")
            self._error(gone.format(path=path), quiet, place="hosts-list-gone")
            return False
        except HostListKindError:
            texts = self.list_texts()
            place = texts.not_this_kind_place
            self._error(texts.not_this_kind.format(path=path), quiet, place=place)
            return False
        except (HostListFileError, OSError) as e:
            failed = _("Couldn't open “{path}”: {error}").format(path=path, error=e)
            self._error(failed, quiet, place="hosts-list-file-error")
            return False
        self._use(doc)
        return True

    def new_list(self) -> None:
        if self._leader is not None:
            self._leader.new_list()
            return
        path = ask_new_list(
            self,
            shared_dir=self._places.shared_dir,
            user_dir=self._places.user_dir,
            texts=self.list_texts(),
        )
        if path is not None:
            self._create_list(path, replace_existing=path.exists())

    def open_list_file(self) -> None:
        if self._leader is not None:
            self._leader.open_list_file()
            return
        shared = self._places.shared_dir
        start = shared if shared.is_dir() else self._personal_list.parent
        name, _filter = QFileDialog.getOpenFileName(
            self, self.list_texts().open, str(start), self.list_texts().file_filter
        )
        if name:
            self.open_list(Path(name))

    def found_lists(self, *, hidden: bool = False) -> list[Path]:
        if self._leader is not None:
            return self._leader.found_lists(hidden=hidden)
        found = locations.found_lists(self._places.shared_dir, self._places.user_dir)
        return found if hidden else locations.without_hidden(self.prefs, found)

    def _available_lists(self) -> list[Path]:
        if self._leader is not None:
            return self._leader._available_lists()
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
        manage = menu.addAction(self.list_texts().manage)
        manage.triggered.connect(lambda: self._shell.open_settings(self._owner().lists_page()))

    def list_choices(self) -> list[tuple[Path, str, bool]]:
        lists = self._available_lists()
        names = locations.list_names(
            lists, default=self._default_list, personal=self._personal_list
        )
        current = self._doc.path if self._doc else None
        return [
            (path, name, current is not None and locations.same_path(path, current))
            for path, name in zip(lists, names, strict=True)
        ]

    def pick_list(self, path: Path) -> None:
        self._pick_list(path)

    def _pick_list(self, path: Path) -> None:
        current = self._doc.path if self._doc else None
        if current is None or not locations.same_path(path, current):
            self.open_list(path)

    def _create_list(self, path: Path, *, replace_existing: bool, quiet: bool = False) -> bool:
        try:
            if self._kind(path) is ListKind.DEFAULT and not path.parent.exists():
                files.make_shared_folder(path.parent)
            doc = OpenList.create(path, replace_existing=replace_existing, kind=self.list_kind())
        except (HostListFileError, OSError) as e:
            failed = _("Couldn't create “{path}”: {error}").format(path=path, error=e)
            self._error(failed, quiet, place="hosts-list-file-error")
            return False
        self._use(doc)
        return True

    def _swap(self, doc: OpenList | None) -> bool:
        old = self._doc
        switched = (old is None) != (doc is None) or (
            old is not None and doc is not None and not locations.same_path(old.path, doc.path)
        )
        if switched:
            self._remember_view()
            self.list_switched()
            self._clear_search()
        self._doc = doc
        return switched

    def _use(self, doc: OpenList) -> None:
        switched = self._swap(doc)
        locations.remember_list(self.prefs, doc.path)
        hidden = locations.hidden_lists(self.prefs)
        if any(locations.same_path(doc.path, p) for p in hidden):
            locations.set_hidden_lists(
                self.prefs, [p for p in hidden if not locations.same_path(doc.path, p)]
            )
        in_folder = any(locations.same_path(doc.path, p) for p in self.found_lists(hidden=True))
        if self._kind(doc.path) is ListKind.SHARED and not in_folder:
            added = [
                p for p in locations.added_lists(self.prefs) if self._kind(p) is ListKind.SHARED
            ]
            locations.set_added_lists(self.prefs, [*added, doc.path])
        self._save_prefs()
        log.info("Opened list %s (read-only=%s)", doc.path, doc.read_only)
        self.refresh()
        if switched:
            self._show_first(doc)

    def _show_first(self, doc: OpenList) -> None:
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
        if self._doc is None:
            return None
        view = locations.list_view(self.prefs, self._doc.path)
        return view.show, view.group

    def set_first_group(self, group_id: str, first: bool) -> None:
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
        self.prefs[locations.START_KEY] = start_list
        if start_view is not None and self._doc is not None:
            show, group = start_view
            view = locations.list_view(self.prefs, self._doc.path)
            locations.set_list_view(
                self.prefs, self._doc.path, replace(view, show=show, group=group)
            )
        locations.set_added_lists(self.prefs, added_lists)
        locations.set_hidden_lists(self.prefs, hidden_lists)

    def add_group(self) -> None:
        self._add_group(self.nav.selected_group_id())

    def add_top_group(self) -> None:
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
            self._error(str(e), place="hosts-list-rule")
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
            self._error(str(e), place="hosts-list-rule")
            return
        self._commit(new)

    def _ask_how_to_remove(
        self, group_id: str, groups: int, items: int
    ) -> tuple[str, str | None] | None:
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
        fill_host_move_menu(
            menu,
            host_list,
            lambda target: chosen.append(("move", target)),
            skip=host_list.subtree(group_id),
        )
        parent = group.parent or NO_GROUP
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
        doc = self._doc
        if doc is None or self._real_doc is not None:
            return False
        try:
            doc.commit(new)
        except HostListChangedError:
            self._resolve_conflict(new)
            return False
        except (HostListFileError, OSError) as e:
            failed = _("Couldn't save the list: {error}").format(error=e)
            self._error(failed, place="hosts-list-file-error")
            return False
        self._owner().refresh()
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
        help_links.add_link(box, "hosts-list-changed")
        run_modal(box)
        if box.clickedButton() is copy:
            name, _filter = QFileDialog.getSaveFileName(
                self,
                _("Save a copy"),
                str(doc.path.with_name(doc.path.stem + " (copy).json")),
                self.list_texts().file_filter,
            )
            if name:
                path = Path(name)
                try:
                    copy = OpenList.save_as(
                        path, mine, replace_existing=path.exists(), kind=self.list_kind()
                    )
                    self._owner()._use(copy)
                    return
                except (HostListFileError, OSError) as e:
                    failed = _("Couldn't save the copy: {error}").format(error=e)
                    self._error(failed, place="hosts-list-file-error")
        try:
            doc.reload()
        except (HostListFileError, OSError) as e:
            failed = _("Couldn't reload the list: {error}").format(error=e)
            self._error(failed, place="hosts-list-file-error")
        self._owner().refresh()

    def manage_groups(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = ManageGroupsDialog(self, doc.hosts)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._arrange(dialog.order())

    def sort_groups(self) -> None:
        doc = self._writable()
        if doc is None or not doc.hosts.groups:
            return
        hosts = doc.hosts
        order: list[tuple[str, str | None]] = []

        def walk(parent: str | None) -> None:
            for group in sorted(hosts.children(parent), key=lambda g: g.name.casefold()):
                order.append((group.id, parent))
                walk(group.id)

        walk(None)
        shown: list[str] = []

        def shown_order(parent: str | None) -> None:
            for group in hosts.children(parent):
                shown.append(group.id)
                shown_order(group.id)

        shown_order(None)
        if shown == [gid for gid, _parent in order]:
            self._shell.show_message(_("The groups are already A–Z."))
            return
        if confirm(
            self,
            _("Sort groups A–Z"),
            _("Sort every group A–Z?"),
            _("Sort A–Z"),
            _("Groups inside other groups are sorted too. The order they're in now isn't kept."),
        ):
            self._arrange(order)

    def _groups_dragged(self) -> None:
        self._arrange(self.nav.groups.order())

    def _arrange(self, order: list[tuple[str, str | None]]) -> None:
        doc = self._writable()
        if doc is None:
            return
        try:
            new = doc.hosts.arrange_groups(order)
        except HostListRuleError as e:
            self._error(str(e), place="hosts-list-rule")
            self.refresh()
            return
        self._commit(new)

    def move_group(self, group_id: str, parent: str | None) -> None:
        doc = self._writable()
        if doc is None:
            return
        try:
            new = doc.hosts.move_group(group_id, parent)
        except HostListRuleError as e:
            self._error(str(e), place="hosts-list-rule")
            return
        if new is not doc.hosts and self._commit(new):
            self.nav.select_group(group_id)
            self._show_items()

    def move_items(self, ids: list[str], group_id: str) -> None:
        doc = self._writable()
        if doc is None or (group_id != NO_GROUP and doc.hosts.group(group_id) is None):
            return
        self._commit(doc.hosts.move_hosts(ids, group_id))

    def retranslate(self) -> None:
        self.sort_groups_action.setText(_("&Sort groups A–Z"))
        self.sort_menu.setTitle(_("So&rt by"))
        self.columns_menu.setTitle(_("Co&lumns"))
        self.nav.retranslate()
        self.table.retranslate()
        self.details.retranslate()
        self._columns_shown()
        self.refresh()

    def refresh(self) -> None:
        self.nav.show_list(self._doc.hosts if self._doc else None)
        editable = self._writable() is not None
        self.nav.groups.set_editable(editable)
        self.table.set_editable(editable)
        self._show_items()
        self.list_changed.emit()

    def came_to_front(self) -> None:
        if self._fill_waiting:
            self._show_items()

    def _show_items(self) -> None:
        if self._hold_fill:
            return
        self._fill_waiting = not self._shell.fills_now(self.TOOL_ID)
        if self._fill_waiting:
            return
        self._search_timer.stop()
        needle = self._needle()
        before_tags = self._place_items()
        tags = self.nav.picked_tags()
        items = self._with_tags(before_tags)
        self.nav.set_searching(bool(needle))
        self.fill_table(items)
        self.table.set_search(needle)
        strip = self.only_tags_text(len(items), len(before_tags)) if tags else ""
        self.tag_strip.show_tags(tags, strip)
        if tags and before_tags and not items:
            self.table.show_no_match(self.no_match_text())
        else:
            self.table.show_note(*self._empty_note(items))
        self.table.show_offer(self.typed_offer(self.search.text().strip(), items) if items else [])

    def _empty_note(self, items: Sequence[Host]) -> tuple[str, list[QAction]]:
        doc, a = self._doc, self._list_commands
        if items:
            return "", []
        if doc is None:
            return self.list_texts().no_list, [a.new_list, a.open_list]
        texts, add = self.empty_texts(), self.add_item_action()
        if typed := self.search.text().strip():
            return texts.search.format(text=typed), self.typed_offer(typed, items)
        if not doc.hosts.hosts:
            if doc.read_only:
                return texts.read_only_list, []
            also = self.import_action()
            return texts.empty_list, [add, *([also] if also is not None else [])]
        if self.nav.current_filter().kind == "nogroup":
            return texts.loose, []
        return texts.group, ([] if doc.read_only else [add])

    def fill_table(self, items: Sequence[Host]) -> None:
        self.table.show_items(items)

    def visible_items(self) -> tuple[Host, ...]:
        return self._with_tags(self._place_items())

    def _place_items(self) -> tuple[Host, ...]:
        if self._doc is None:
            return ()
        hosts, current = self._doc.hosts, self.nav.current_filter()
        if needle := self._needle():
            return tuple(h for h in hosts.hosts if self.matches(h, needle))
        if current.kind == "group" and current.value:
            return hosts.hosts_in(current.value)
        if current.kind == "nogroup":
            return tuple(h for h in hosts.hosts if h.group == NO_GROUP)
        return hosts.hosts

    def _with_tags(self, items: tuple[Host, ...]) -> tuple[Host, ...]:
        tags = self.nav.picked_tags()
        return tuple(h for h in items if all(t in h.tags for t in tags)) if tags else items

    def _needle(self) -> str:
        return self.search.text().strip().casefold()

    def _focus_search(self) -> None:
        self.list_to_front()
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _clear_search(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)

    def _filter_picked(self) -> None:
        self._clear_search()
        self._show_items()
        self.list_to_front()

    def _end_search(self) -> None:
        if self.search.text():
            self._clear_search()
            self._show_items()

    def _columns_shown(self) -> None:
        self.search.set_fields(*self.search_fields())
        if self._needle():
            self._show_items()

    def _to_results(self) -> None:
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
            self.status_label.setText(self.list_texts().no_list)
            self.status_label.setToolTip("")
            self.status_label.unsetCursor()
            self.list_picker.setText(_("No list open"))
            return
        name = self._list_name(doc.path)
        self.title_changed.emit(name)
        self.list_picker.setText(name)
        self.list_picker.setToolTip(str(doc.path))
        kind = self._kind(doc.path)
        parts = [
            self._kind_label(kind),
            *([name] if kind is ListKind.SHARED else []),
            self.items_text(len(doc.hosts.hosts)),
            *self.status_extras(doc),
        ]
        self.status_label.setToolTip("\n".join((str(doc.path), _("Click to copy"))))
        self.status_label.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._needle():
            found = self.table.topLevelItemCount()
            parts.append(self.found_text(found))
        parts.append(self.selected_text(selected))
        if tags := self.nav.picked_tags():
            parts.append(_("Tags: {tags}").format(tags=", ".join(tags)))
        if doc.read_only:
            parts.append(_("read-only"))
        self.status_label.setText(" · ".join(parts))

    def copy_list_path(self) -> None:
        if self._doc is not None:
            QGuiApplication.clipboard().setText(str(self._doc.path))
            self._say_copied(str(self._doc.path))

    def _say_copied(self, text: str) -> None:
        self._shell.show_message(_("Copied: {text}").format(text=text), 5000)

    def title(self) -> str:
        return self._list_name(self._doc.path) if self._doc is not None else ""

    def report_sources(self, host_list: HostList) -> tuple[list[Source], int]:
        counted = self.counted_text
        sources: list[Source] = []
        current = self.nav.current_filter()
        tags = self.nav.picked_tags()
        browsing = not self._needle() and not tags
        start = 0
        if self._needle():
            found = self.visible_items()
            sources.append(Source(counted(_("Search results"), len(found)),
                                  _("the search results"), found))  # fmt: skip
        elif tags:
            shown = self.visible_items()
            label = _("Picked tags: {tags}").format(tags=", ".join(tags))
            sources.append(Source(counted(label, len(shown)), _("the picked tags"), shown))
        selected = self.selected_items()
        if len(selected) > 1:
            label, name = self.selected_source_texts()
            sources.append(Source(counted(label, len(selected)), name, tuple(selected)))
        every = host_list.hosts
        everything = self.list_texts().everything
        sources.append(Source(counted(everything, len(every)), everything, every))
        if browsing and current.kind == "all":
            start = len(sources) - 1
        loose = tuple(h for h in every if h.group == NO_GROUP)
        sources.append(Source(counted(_("No group"), len(loose)), _("No group"), loose))
        if browsing and current.kind == "nogroup":
            start = len(sources) - 1

        def visit(parent: str | None, depth: int) -> None:
            nonlocal start
            for group in host_list.children(parent):
                items = host_list.hosts_in(group.id)
                sources.append(Source(counted(group.name, len(items)), group.name, items, depth))
                if browsing and current.kind == "group" and current.value == group.id:
                    start = len(sources) - 1
                visit(group.id, depth + 1)

        visit(None, 0)
        for tag in sorted(host_list.all_tags(), key=str.casefold):
            items = tuple(h for h in every if tag in h.tags)
            name = _("tag “{tag}”").format(tag=tag)
            sources.append(
                Source(counted(_("Tag: {tag}").format(tag=tag), len(items)), name, items)
            )
        order = self.table.in_shown_order
        return [replace(s, hosts=order(s.hosts)) for s in sources], start

    def _item_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        if self.table.itemAt(position) is None:
            self.table.clearSelection()
            menu.addActions([self.add_item_action(), self._list_commands.add_group])
        else:
            self.fill_item_menu(menu, self.selected_items())
        popup(menu, self.table.viewport().mapToGlobal(position))

    def add_copy_menu(self, menu: QMenu) -> None:
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
        self._add_tags_menu(menu, items)

    def _add_tags_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        assert self._doc is not None
        tags = menu.addMenu(_("&Tags"))
        tags.setEnabled(self._writable() is not None)
        ids = [h.id for h in items]
        for tag in sorted(self._doc.hosts.all_tags(), key=str.casefold):
            having = sum(tag in h.tags for h in items)
            every = having == len(items)
            text = (
                tag
                if every or not having
                else _("{tag} ({n} of {total})").format(tag=tag, n=having, total=len(items))
            )
            item = tags.addAction(text.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(every)
            item.triggered.connect(
                lambda _c=False, t=tag, off=every: self.tag_items(ids, t, on=not off)
            )
        if tags.actions():
            tags.addSeparator()
        new = tags.addAction(_("&New tag…"))
        new.triggered.connect(lambda: self._new_tag(ids))

    def tag_items(self, ids: list[str], tag: str, *, on: bool) -> None:
        doc = self._writable()
        if doc is not None:
            self._commit(doc.hosts.tag_hosts(ids, tag, on))

    def _new_tag(self, ids: list[str]) -> None:
        doc = self._writable()
        if doc is None:
            return
        typed, ok = QInputDialog.getText(self, _("New tag"), _("Tag for the selected items:"))
        tag = typed.strip()[:MAX_TAG]
        if not ok or not tag:
            return
        known = {t.casefold(): t for t in doc.hosts.all_tags()}
        self.tag_items(ids, known.get(tag.casefold(), tag), on=True)

    def _heading_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        self._add_top_group_item(menu)
        menu.addAction(self._list_commands.manage_groups)
        self._add_sort_item(menu)
        popup(menu, self.nav.groups_heading.mapToGlobal(position))

    def _add_top_group_item(self, menu: QMenu) -> None:
        item = menu.addAction(self._list_commands.add_group.text())
        item.setEnabled(self._writable() is not None)
        item.triggered.connect(self.add_top_group)

    def _add_sort_item(self, menu: QMenu) -> None:
        doc = self._doc
        self.sort_groups_action.setEnabled(
            self._writable() is not None and doc is not None and len(doc.hosts.groups) > 1
        )
        menu.addAction(self.sort_groups_action)

    def _group_menu(self, position: QPoint) -> None:
        a = self._list_commands
        menu = QMenu(self)
        group_id = self.nav.group_at(position)
        if group_id is None:
            self._add_top_group_item(menu)
            menu.addAction(a.manage_groups)
            self._add_sort_item(menu)
            popup(menu, self.nav.groups.viewport().mapToGlobal(position))
            return
        self.nav.select_group(group_id)
        self.list_to_front()
        menu.addAction(a.add_group)
        group = self._doc.hosts.group(group_id) if self._doc else None
        if group is not None and self._doc is not None:
            self.fill_group_menu(menu, group)
            menu.addSeparator()
            view = locations.list_view(self.prefs, self._doc.path)
            first = menu.addAction(_("Sho&w this group first"))
            first.setToolTip(_("The list opens on this group"))
            first.setCheckable(True)
            first.setChecked(view.show == locations.SHOW_GROUP and view.group == group.id)
            first.toggled.connect(lambda on: self.set_first_group(group.id, on))
            menu.addSeparator()
            menu.addAction(a.edit)
            move = TreeMenu(_("&Move to"), menu)
            menu.addMenu(move)
            move.setEnabled(self._writable() is not None)
            fill_move_menu(move, self._doc.hosts, group.id, lambda p: self.move_group(group.id, p))
            menu.addAction(a.remove)
        popup(menu, self.nav.groups.viewport().mapToGlobal(position))

    def _writable(self) -> OpenList | None:
        return self._doc if self._doc is not None and not self._doc.read_only else None

    def sample_item(self, group: str) -> Host | None:
        return None

    def sample_items(self, group: str) -> list[Host]:
        item = self.sample_item(group)
        return [item] if item is not None else []

    def sample_shown(self) -> bool:
        return self._real_doc is not None

    def show_sample(self) -> None:
        """In memory only: never saved, and no address of theirs is read (is_sample)."""
        doc = self._doc
        if doc is None or self._real_doc is not None:
            return
        group = self.nav.selected_group_id()
        samples = self.sample_items(group if group and doc.hosts.group(group) else NO_GROUP)
        if not samples:
            return
        a = self._list_commands
        self._shown_for_guide = [p for p in (a.show_groups, a.show_tags, a.show_details)
                                 if not p.isChecked()]  # fmt: skip
        for panel in self._shown_for_guide:
            panel.trigger()
        hosts = replace(doc.hosts, hosts=(*doc.hosts.hosts, *samples))
        self._real_doc = doc
        self._doc = OpenList(doc.path, hosts, doc.stamp, read_only=doc.read_only, kind=doc.kind)
        self.refresh()
        self.table.select_ids([samples[0].id])
        self._selection_changed()

    def hide_sample(self) -> None:
        real, self._real_doc = self._real_doc, None
        if real is None:
            return
        if self._doc is not None and any(is_sample(h.id) for h in self._doc.hosts.hosts):
            self._doc = real
        for panel in self._shown_for_guide:
            if panel.isChecked():
                panel.trigger()
        self._shown_for_guide = []
        self.refresh()
        self._selection_changed()

    def sample_row(self, window: QWidget) -> QRect | None:
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if item is not None and item.data(0, ROLE_ID) == SAMPLE_ID:
                viewport = self.table.viewport()
                row = self.table.visualItemRect(item)
                if not row.isValid() or not viewport.isVisible():
                    return None
                row = QRect(0, row.top(), viewport.width(), row.height())
                return QRect(viewport.mapTo(window, row.topLeft()), row.size())
        return None

    def _kind(self, path: Path) -> ListKind:
        return locations.list_kind(path, default=self._default_list, personal=self._personal_list)

    @staticmethod
    def _kind_label(kind: ListKind) -> str:
        return {
            ListKind.DEFAULT: _("Default"),
            ListKind.PERSONAL: _("Personal"),
            ListKind.SHARED: _("Shared"),
        }[kind]

    def _error(self, message: str, quiet: bool = False, *, place: str = "") -> None:
        log.warning("%s", message)
        if quiet:
            self._shell.show_message(message, 10_000)
        elif place:
            help_links.warning(self, "CapyPanel", message, place=place)
        else:
            QMessageBox.warning(self, "CapyPanel", message)

    def _save_prefs(self) -> None:
        self._shell.save_prefs()
