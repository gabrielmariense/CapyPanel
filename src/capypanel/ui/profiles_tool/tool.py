"""The User profiles tool: the Windows profiles on the hosts of Hosts' open list, which can be
deleted, how big they are. Hosts' Groups panel on the left (read only); in the middle and on the
right, tabs: the pinned Hosts tab lists the group's hosts, and each host opened gets its own tab,
so several hosts are read, counted and cleaned at once. It keeps no list of its own, and the
account that signs in to a host is the one Hosts' Accounts give it. Scanning only reads."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import NO_GROUP, Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts import group_path
from capypanel.ui.hosts_tool.accounts import windows_account
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.hosts_tool.runner import HostTarget
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.icons import STATUS_COLORS, tabler_icon
from capypanel.ui.list_workspace.panels import NavigationPane, natural_key
from capypanel.ui.list_workspace.splitter import PaneSplitter
from capypanel.ui.main_window.tool import Shell, Tool
from capypanel.ui.main_window.toolbar import ToolBar, tool_button
from capypanel.ui.menus import MenuCombo, popup
from capypanel.ui.profiles_tool import work
from capypanel.ui.profiles_tool.host_page import Context, HostPage, Stage
from capypanel.ui.profiles_tool.hosts_page import HostFacts, HostsPage, RowFacts
from capypanel.ui.profiles_tool.panels import LEFT, RIGHT
from capypanel.ui.profiles_tool.tabs import HOSTS, TabStrip, mark_icon

PANES_KEY = "panes"  # the side panels' widths, in the tool's settings
VIEWS_KEY = "views"  # the group each host list was left on, by the list's file
SHOWN_KEY = "shown"  # View's Groups panel and Details panel ticks


class ProfilesToolBar(ToolBar):
    """One set of buttons on every tab, greyed where it doesn't apply; the tooltips name the
    host."""

    def __init__(self) -> None:
        super().__init__()
        self.scan_button = tool_button()
        self.sizes_button = tool_button()
        self.delete_button = tool_button()
        self.delete_button.setProperty("risky", True)  # amber, as every action that destroys
        self._counting = False
        self._scan_text = ""
        self._delete_text = ""
        self.add_group([self.scan_button, self.sizes_button])
        self.add_group([self.delete_button])
        self.retranslate()

    def show_texts(self, scan: str, scan_tip: str, delete: str, delete_tip: str,
                   sizes_tip: str, counting: bool) -> None:  # fmt: skip
        gap = " "  # the stylesheet drops the gap between icon and text
        self._scan_text, self._delete_text, self._counting = scan, delete, counting
        self.scan_button.setText(gap + scan)
        self.scan_button.setToolTip(scan_tip)
        self.delete_button.setText(gap + delete)
        self.delete_button.setToolTip(delete_tip)
        self.sizes_button.setText(gap + (_("Stop the count") if counting else _("Calculate sizes")))
        self.sizes_button.setToolTip(sizes_tip)
        self._icons()

    def retranslate(self) -> None:
        self.show_texts(_("Scan"), "", _("Delete profiles…"), "", "", self._counting)

    def restyle(self) -> None:
        self._icons()

    def _icons(self) -> None:
        color = self.scan_button.palette().color(QPalette.ColorRole.ButtonText)
        self.scan_button.setIcon(tabler_icon("refresh", color))
        self.sizes_button.setIcon(tabler_icon("x" if self._counting else "report-analytics", color))
        self.show_delete(self.delete_button.isEnabled())

    def show_delete(self, enabled: bool) -> None:
        """Amber while it can be pressed, greyed with its icon while it can't."""
        self.delete_button.setEnabled(enabled)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        color = QColor(STATUS_COLORS["attention"]) if enabled else muted
        self.delete_button.setIcon(tabler_icon("trash", color))


class ProfilesTool(Tool):
    TOOL_ID = "profiles"
    ICON = "profile-card"

    def __init__(self, shell: Shell) -> None:
        super().__init__(shell, ProfilesToolBar())
        hosts = shell.tool(HostsTool.TOOL_ID)
        self._hosts = hosts if isinstance(hosts, HostsTool) else None
        self.pool = work.Pool()
        self._pages: dict[str, HostPage] = {}  # by host key, as the tabs are
        self._kept: dict[str, tuple[int, int, datetime]] = {}  # closed tabs' counts and time
        self._quitting = False  # quit asked while a host deletes: quit once they're done

        self.nav = NavigationPane(lambda: _("All hosts"))
        self.nav.add_group_button.hide()  # read only: groups are made in Hosts
        self.nav.groups.set_editable(False)
        self.nav.everything.setAcceptDrops(False)
        self.nav.groups_heading.setAcceptDrops(False)
        self.list_picker = MenuCombo()
        self.list_picker.setObjectName("listPicker")
        self.list_picker.menu().setToolTipsVisible(True)  # each list's path
        self.list_picker.menu().aboutToShow.connect(self._fill_list_menu)
        nav_layout = self.nav.layout()
        assert isinstance(nav_layout, QVBoxLayout)
        nav_layout.insertWidget(0, self.list_picker)

        self.hosts_page = HostsPage()
        self.tabs = TabStrip()
        self.middle = QStackedWidget()
        self.side = QStackedWidget()
        self.middle.addWidget(self.hosts_page.box)
        self.side.addWidget(self.hosts_page.side)
        self.inner = PaneSplitter()
        self.inner.addWidget(self.middle)
        self.inner.addWidget(self.side)
        self.inner.setStretchFactor(0, 1)
        self.inner.setChildrenCollapsible(False)
        area = QWidget()
        column = QVBoxLayout(area)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.tabs)
        column.addWidget(self.inner, 1)
        self.splitter = PaneSplitter()
        self.splitter.addWidget(self.nav)
        self.splitter.addWidget(area)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        left, right = _two_widths(self.prefs.get(PANES_KEY)) or (LEFT, RIGHT)
        self.splitter.setSizes([left, 1100 - left])
        self.inner.setSizes([max(400, 1100 - left - right), right])
        margins = QVBoxLayout(self)
        margins.setContentsMargins(8, 4, 8, 4)  # as the Hosts page
        margins.addWidget(self.splitter)

        self.show_groups = QAction(self)
        self.show_details = QAction(self)
        shown = self.prefs.get(SHOWN_KEY)
        shown = shown if isinstance(shown, dict) else {}
        for action, key, pane in (
            (self.show_groups, "groups", self.nav),
            (self.show_details, "details", self.side),
        ):
            action.setCheckable(True)
            action.setChecked(bool(shown.get(key, True)))
            pane.setVisible(action.isChecked())
            action.toggled.connect(pane.setVisible)
            action.toggled.connect(self._save_shown)
            action.toggled.connect(self.align_toolbar_later)

        self._connect()
        self.retranslate()
        self._show_list()

    def _connect(self) -> None:
        bar = self.bar
        bar.scan_button.clicked.connect(self.scan_clicked)
        bar.sizes_button.clicked.connect(self._toggle_sizes)
        bar.delete_button.clicked.connect(self.delete_ticked)
        self.splitter.splitterMoved.connect(self.align_toolbar_later)
        self.nav.filter_changed.connect(self._group_picked)
        self.hosts_page.search.textChanged.connect(self._fill_hosts)
        table = self.hosts_page.table
        table.open_requested.connect(self.open_hosts)
        table.picked.connect(self._hosts_picked)
        table.scan_typed.connect(self.open_typed)
        self.hosts_page.progress.go_to.connect(self.switch)
        self.tabs.picked.connect(self.switch)
        self.tabs.close_requested.connect(self.close_tab)
        self.tabs.menu_requested.connect(self._tab_menu)
        for keys, run in (
            ("Ctrl+Tab", lambda: self._step(1)),
            ("Ctrl+Shift+Tab", lambda: self._step(-1)),
            ("Ctrl+W", lambda: self.close_tab(self.tabs.current())),
        ):
            shortcut = QShortcut(QKeySequence(keys), self, run)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        if self._hosts is not None:
            self._hosts.list_changed.connect(self._show_list)
            self._hosts.host_changed.connect(self._host_checked)
            self._hosts.checks_changed.connect(self._fill_hosts)

    @property
    def bar(self) -> ProfilesToolBar:
        assert isinstance(self.toolbar, ProfilesToolBar)
        return self.toolbar

    # ---- what the shell asks ----

    def tool_name(self) -> str:
        return _("User profiles")

    def menu_name(self) -> str:
        return _("&User profiles")

    def toolbar_anchor(self) -> QWidget:
        return self.nav if self.nav.isVisible() else self.middle

    def view_actions(self) -> list[list[QAction]]:
        return [[self.show_groups, self.show_details]]

    def save_state(self) -> None:
        outer, inner = self.splitter.sizes(), self.inner.sizes()
        if len(outer) == 2 and len(inner) == 2 and outer[0] and inner[1]:
            self.prefs[PANES_KEY] = [outer[0], inner[1]]

    def quit_question(self, parent: QWidget) -> bool:
        """Before CapyPanel quits: while a host deletes, ask. Cancel the rest and quit lets the
        profile under way finish, then quits."""
        deleting = [p for p in self._pages.values() if p.deleting]
        if self._quitting or not deleting:
            return True
        n = len(deleting)
        question = Question(
            parent,
            _("Quit CapyPanel"),
            ngettext(
                "{n} host is still deleting profiles", "{n} hosts are still deleting profiles", n
            ).format(n=n),  # fmt: skip
            _(
                "Quitting now cancels the profiles still queued. The profile being deleted on "
                "each host finishes first; CapyPanel quits after that."
            ),  # fmt: skip
            _("Cancel the rest and quit"),
        )
        question.cancel.setText(_("Continue"))
        if run_modal(question) != QDialog.DialogCode.Accepted:
            return False
        self._quitting = True
        for page in deleting:
            page.cancel_rest()
        return False  # the window closes once the last profile under way ends

    def retranslate(self) -> None:
        self.nav.retranslate()
        self.show_groups.setText(_("&Groups pane"))
        self.show_details.setText(_("&Details pane"))
        self.hosts_page.retranslate()
        for page in self._pages.values():
            page.show_again()
        self._show_list()
        self._update()

    def restyle(self) -> None:
        super().restyle()
        self.tabs.restyle()
        for page in self._pages.values():
            page.show_again()
        self._fill_hosts()
        self._update()

    # ---- the list and its groups ----

    def _fill_list_menu(self) -> None:
        menu = self.list_picker.menu()
        menu.clear()
        choices = self._hosts.list_choices() if self._hosts is not None else []
        for path, name, current in choices:
            item = menu.addAction(name.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current)
            item.setToolTip(str(path))
            item.triggered.connect(lambda _c=False, p=path: self._pick_list(p))

    def _pick_list(self, path: Any) -> None:
        if self._hosts is not None:
            self._hosts.pick_list(path)

    def _show_list(self) -> None:
        """Hosts opened another list, or the open one changed."""
        doc = self._hosts.document if self._hosts is not None else None
        if doc is None:
            self.list_picker.setText(_("No list open"))
            self.list_picker.setToolTip("")
            self.nav.show_list(None)
            self._fill_hosts()
            self._overview()
            return
        choices = self._hosts.list_choices() if self._hosts is not None else []
        name = next((n for _p, n, current in choices if current), doc.path.stem)
        self.list_picker.setText(name)
        self.list_picker.setToolTip(str(doc.path))
        self.nav.show_list(doc.hosts)
        kind, value = self._view_of(str(doc.path))
        self.nav.blockSignals(True)
        self.nav.show_view(kind, value)
        self.nav.blockSignals(False)
        self._fill_hosts()
        self._overview()

    def _view_of(self, list_path: str) -> tuple[str, str]:
        kept = self.prefs.get(VIEWS_KEY)
        view = kept.get(list_path) if isinstance(kept, dict) else None
        if isinstance(view, list) and len(view) == 2 and all(isinstance(v, str) for v in view):
            return view[0], view[1]
        return "all", ""

    def _group_picked(self) -> None:
        """A group on the left: the Hosts tab comes forward on it, and a search ends."""
        doc = self._hosts.document if self._hosts is not None else None
        if doc is not None:
            current = self.nav.current_filter()
            kept = self.prefs.get(VIEWS_KEY)
            kept = dict(kept) if isinstance(kept, dict) else {}
            kept[str(doc.path)] = [current.kind, current.value or ""]
            self.prefs[VIEWS_KEY] = kept
            self._shell.save_prefs()
        search = self.hosts_page.search
        search.blockSignals(True)
        search.clear()
        search.blockSignals(False)
        self.switch(HOSTS)
        self._fill_hosts()

    def _all_hosts(self) -> tuple[Host, ...]:
        doc = self._hosts.document if self._hosts is not None else None
        return tuple(h for h in doc.hosts.hosts if h.connect_address) if doc is not None else ()

    def visible_hosts(self) -> list[Host]:
        """The Hosts tab's rows: a search looks through the whole list; otherwise the group
        picked, narrowed to the picked tags."""
        doc = self._hosts.document if self._hosts is not None else None
        if doc is None:
            return []
        reachable = self._all_hosts()
        needle = self.hosts_page.search.text().strip().casefold()
        if needle:
            found = [h for h in reachable
                     if needle in h.name.casefold() or needle in h.address.casefold()]  # fmt: skip
        else:
            current = self.nav.current_filter()
            if current.kind == "group" and current.value:
                inside = {h.id for h in doc.hosts.hosts_in(current.value)}
                found = [h for h in reachable if h.id in inside]
            elif current.kind == "nogroup":
                found = [h for h in reachable if h.group == NO_GROUP]
            else:
                found = list(reachable)
        tags = self.nav.picked_tags()
        if tags:
            found = [h for h in found if all(t in h.tags for t in tags)]
        return sorted(found, key=lambda h: natural_key(h.name))

    def _place_name(self) -> str:
        """The Hosts tab's first line: the group's name, or All hosts."""
        doc = self._hosts.document if self._hosts is not None else None
        current = self.nav.current_filter()
        if self.hosts_page.search.text().strip():
            return _("All hosts")
        if doc is not None and current.kind == "group" and current.value:
            group = doc.hosts.group(current.value)
            if group is not None:
                return group.name
        if current.kind == "nogroup":
            return _("No group")
        return _("All hosts")

    def _fill_hosts(self) -> None:
        hosts = self.visible_hosts()
        typed = self.hosts_page.search.text().strip()
        self.hosts_page.table.show_hosts(hosts, self._row_facts)
        self.hosts_page.table.show_typed(typed if typed and not hosts else "")
        if typed:
            about = _("{shown} of {total} shown").format(
                shown=len(hosts), total=len(self._all_hosts())
            )
        else:
            about = ngettext("{n} host", "{n} hosts", len(hosts)).format(n=len(hosts))
        self.hosts_page.show_title(self._place_name(), about)
        self._hosts_picked()

    def _host_checked(self, key: str) -> None:
        host = self._host(key)
        if host is not None:
            self.hosts_page.table.show_facts(key, self._row_facts(host))
            self._hosts_picked()

    def _host(self, key: str) -> Host | None:
        doc = self._hosts.document if self._hosts is not None else None
        return doc.hosts.host(key) if doc is not None else None

    def _checked(self, key: str) -> tuple[Status, datetime] | None:
        return self._hosts.status_found(key) if self._hosts is not None else None

    def _row_facts(self, host: Host) -> RowFacts:
        checked = self._checked(host.id)
        if checked is None:
            status, color, tip = _("Not checked"), "", _("Hosts hasn't checked it yet.")
        else:
            state, when = checked
            status, color = check_texts.status_text(state), STATUS_COLORS[state]
            tip = _("Hosts' last check: {when}").format(when=check_texts.when_text(when))
        page = self._pages.get(host.id)
        profiles = deletable = None
        words, time, scan_color = "", None, ""
        if page is not None:
            counts = page.counts()
            if counts is not None:
                profiles, deletable = counts
            words = page.scan_words()
            if page.read_at is not None and page.stage is Stage.SCANNED:
                time = page.read_at.timestamp()
            mark = page.mark()
            scan_color = mark.color if mark.bad else ("#3b82f6" if mark.busy else "")
        elif host.id in self._kept:
            profiles, deletable, when = self._kept[host.id]
            words, time = check_texts.clock_text(when), when.timestamp()
        return RowFacts(status, color, tip, profiles, deletable, words, time, scan_color)

    def _hosts_picked(self) -> None:
        ids = self.hosts_page.table.selected_ids()
        host = self._host(ids[0]) if len(ids) == 1 else None
        self.hosts_page.show_host(self._host_facts(host) if host is not None else None)
        if self.tabs.current() == HOSTS:
            self._update()

    def _host_facts(self, host: Host) -> HostFacts:
        doc = self._hosts.document if self._hosts is not None else None
        checked = self._checked(host.id)
        if checked is None:
            dot, status = "", _("Not checked by Hosts")
        else:
            state, when = checked
            dot = STATUS_COLORS[state]
            status = _("{status} · checked by Hosts at {time}").format(
                status=check_texts.status_text(state), time=check_texts.clock_text(when)
            )
        page = self._pages.get(host.id)
        scanned, account = "—", "—"
        if page is not None and page.read_at is not None and page.stage is Stage.SCANNED:
            scanned, account = check_texts.clock_text(page.read_at), page.account_name
        elif host.id in self._kept:
            scanned = check_texts.clock_text(self._kept[host.id][2])
        group = group_path(doc.hosts, host.group) if doc is not None else ""
        return HostFacts(host.name, dot, status, host.address, group, scanned, account)

    # ---- opening hosts ----

    def scan_clicked(self) -> None:
        """Scan on the Hosts tab opens the hosts picked; on a host's tab, Scan again."""
        page = self._pages.get(self.tabs.current())
        if page is not None:
            page.start_scan()
            return
        ids = self.hosts_page.table.selected_ids()
        self.open_hosts(ids, len(ids) == 1)  # several open behind, as middle-clicks

    def open_hosts(self, ids: Sequence[str], focus: bool) -> None:
        """Each host in its own tab; a host that has one already isn't read again. `focus`:
        go to the (first) host's tab."""
        targets = [_target(h) for key in ids if (h := self._host(key)) is not None]
        for index, target in enumerate(targets):
            self.open_target(target, focus and index == 0)

    def open_typed(self, typed: str) -> None:
        """A host that isn't in the list, typed in the search box."""
        typed = typed.strip()
        if typed:
            self.open_target(HostTarget(f"@{typed}", typed, typed), True)

    def open_target(self, target: HostTarget, focus: bool) -> None:
        if target.key in self._pages:
            if focus:
                self.switch(target.key)
            return
        if self._hosts is None:
            return
        go, account = self._hosts.accounts.account_for(target, self.window())
        if not go:
            return  # its password wasn't typed
        context = self._context(self._hosts)
        name = account.user if account is not None else windows_account()
        page = HostPage(target, account, name, context)
        self._pages[target.key] = page
        self.middle.addWidget(page.box)
        self.side.addWidget(page.side)
        self.tabs.add(target.key, target.name)
        page.changed.connect(lambda p=page: self._page_changed(p))
        page.status_changed.connect(lambda p=page: self._page_status(p))
        page.start_scan()
        if focus:
            self.switch(target.key)
        self._page_changed(page)

    # ---- the tabs ----

    def switch(self, key: str) -> None:
        """The tab in front: HOSTS, or a host's key."""
        page = self._pages.get(key)
        self.tabs.set_current(key if page is not None else HOSTS)
        if page is not None:
            self.middle.setCurrentWidget(page.box)
            self.side.setCurrentWidget(page.side)
        else:
            self.middle.setCurrentWidget(self.hosts_page.box)
            self.side.setCurrentWidget(self.hosts_page.side)
        self._update()

    def _step(self, by: int) -> None:
        """Ctrl+Tab: the next tab, the Hosts tab included, round and round."""
        keys = [HOSTS, *self.tabs.host_keys()]
        index = keys.index(self.tabs.current()) if self.tabs.current() in keys else 0
        self.switch(keys[(index + by) % len(keys)])

    def close_tab(self, key: str) -> bool:
        """Never the Hosts tab, nor a host that's deleting (the status bar says why)."""
        page = self._pages.get(key)
        if page is None:
            return False
        if page.deleting:
            self._shell.show_message(
                _(
                    "{host} is deleting profiles: its tab closes once it ends. Use Cancel the "
                    "rest to stop it sooner."
                ).format(host=page.target.name)  # fmt: skip
            )
            return False
        page.stop_sizes()
        self.pool.drop(page)
        if page.scan is not None and page.read_at is not None:
            total, deletable = page.counts() or (0, 0)
            self._kept[key] = (total, deletable, page.read_at)
        keys = self.tabs.host_keys()
        index = keys.index(key)
        was_current = self.tabs.current() == key
        self.tabs.remove(key)
        del self._pages[key]
        self.middle.removeWidget(page.box)
        self.side.removeWidget(page.side)
        page.box.deleteLater()
        page.side.deleteLater()
        page.deleteLater()
        if was_current:  # the tab on its left, or the Hosts tab
            left = self.tabs.host_keys()
            self.switch(left[index - 1] if index > 0 and left else HOSTS)
        self._overview()
        return True

    def close_others(self, key: str) -> None:
        for other in [k for k in self.tabs.host_keys() if k != key]:
            self.close_tab(other)

    def close_finished(self) -> None:
        """Every tab whose host is done: scanned, failed or through its delete run."""
        for key in [k for k, p in self._pages.items() if not p.busy()]:
            self.close_tab(key)

    def _tab_menu(self, key: str, where: QPoint) -> None:
        menu = QMenu(self)
        page = self._pages.get(key)
        close = menu.addAction(_("Close"), lambda: self.close_tab(key))
        close.setEnabled(page is not None and not page.deleting)
        menu.addAction(_("Close the others"), lambda: self.close_others(key))
        menu.addAction(_("Close the finished ones"), self.close_finished)
        popup(menu, where)

    def _page_changed(self, page: HostPage) -> None:
        mark = page.mark()
        self.tabs.show_tab(
            page.target.key,
            page.tab_text(),
            mark_icon(mark.icon, mark.color),
            mark.tip,
            closable=not page.deleting,
        )
        host = self._host(page.target.key)
        if host is not None:
            self.hosts_page.table.show_facts(host.id, self._row_facts(host))
        self._overview()
        if self.tabs.current() == page.target.key:
            self._update()
        if self._quitting and not any(p.deleting for p in self._pages.values()):
            self._shell.quit_app()  # the quit asked while hosts were deleting

    def _page_status(self, page: HostPage) -> None:
        if self.tabs.current() == page.target.key:
            self.status_label.setText(page.status_text())

    def _overview(self) -> None:
        """Andamento, the Hosts tab's name and ▾'s list."""
        pages = [self._pages[k] for k in self.tabs.host_keys() if k in self._pages]
        self.hosts_page.progress.show_pages(pages)
        total = len(self._all_hosts())
        self.tabs.set_hosts_text(_("Hosts ({n})").format(n=total))
        items = [(HOSTS, _("Hosts ({n})").format(n=total), mark_icon("device-desktop", ""))]
        for page in pages:
            mark = page.mark()
            text = f"{page.target.name} · {mark.short}" if mark.short else page.target.name
            items.append((page.target.key, text, mark_icon(mark.icon, mark.color)))
        self.tabs.set_more(items)
        if self.tabs.current() == HOSTS:
            self.status_label.setText(self._hosts_status())

    def _hosts_status(self) -> str:
        """ "8 hosts · 4 in tabs · 1 deleting profiles · 2 scanning"."""
        total = len(self._all_hosts())
        parts = [ngettext("{n} host", "{n} hosts", total).format(n=total)]
        pages = list(self._pages.values())
        if pages:
            parts.append(_("{n} in tabs").format(n=len(pages)))
        deleting = sum(p.deleting for p in pages)
        if deleting:
            parts.append(_("{n} deleting profiles").format(n=deleting))
        scanning = sum(p.stage is Stage.SCANNING for p in pages)
        if scanning:
            parts.append(_("{n} scanning").format(n=scanning))
        return " · ".join(parts)

    # ---- the toolbar ----

    def _update(self) -> None:
        bar = self.bar
        page = self._pages.get(self.tabs.current())
        if page is None:
            ids = self.hosts_page.table.selected_ids()
            names = [h.name for k in ids if (h := self._host(k)) is not None]
            if len(names) == 1:
                scan = _("Scan {host}").format(host=names[0])
                tip = _("Opens {host} in a tab and reads its profiles").format(host=names[0])
            elif names:
                scan = ngettext("Scan {n} host", "Scan {n} hosts", len(names)).format(n=len(names))
                tip = _("Opens each in a tab of its own and reads their profiles")
            else:
                scan, tip = _("Scan"), _("Pick hosts in the list first")
            bar.show_texts(scan, tip, _("Delete profiles…"), "", "", counting=False)
            bar.scan_button.setEnabled(bool(names))
            bar.sizes_button.setEnabled(False)
            bar.show_delete(False)
            self.status_label.setText(self._hosts_status())
            self.align_toolbar_later()
            return
        name = page.target.name
        ticked = page.ticked()
        delete = (
            ngettext("Delete {n} profile…", "Delete {n} profiles…", len(ticked)).format(
                n=len(ticked)
            )
            if ticked
            else _("Delete profiles…")
        )
        counting = page.counting()
        bar.show_texts(
            _("Scan again"),
            _("Scans {host}'s profiles again").format(host=name),
            delete,
            _("Deletes the profiles ticked on {host}, after a question that lists them").format(
                host=name
            ),
            _("Stops at once; sizes already counted stay")
            if counting
            else _("Counts the size of each profile shown on {host}; it only reads").format(
                host=name
            ),
            counting,
        )
        idle = page.stage in (Stage.SCANNED, Stage.FAILED) and not page.deleting
        bar.scan_button.setEnabled(idle)
        bar.sizes_button.setEnabled(page.scan is not None and not page.deleting)
        bar.show_delete(page.scan is not None and idle and bool(ticked))
        self.status_label.setText(page.status_text())
        self.align_toolbar_later()

    def _toggle_sizes(self) -> None:
        page = self._pages.get(self.tabs.current())
        if page is not None:
            page.toggle_sizes()

    def delete_ticked(self) -> None:
        page = self._pages.get(self.tabs.current())
        if page is not None:
            page.delete_ticked(self.window())

    def page(self, key: str) -> HostPage | None:
        """A host's tab (for tests)."""
        return self._pages.get(key)

    def _context(self, hosts: HostsTool) -> Context:
        """What a host's tab needs from the tool and from Hosts."""
        return Context(
            pool=self.pool,
            log_file=lambda: self._shell.paths.user_profiles_log_file,
            message=self._shell.show_message,
            another_account=hosts.runner.another_account,
        )

    def _save_shown(self) -> None:
        self.prefs[SHOWN_KEY] = {
            "groups": self.show_groups.isChecked(),
            "details": self.show_details.isChecked(),
        }
        self._shell.save_prefs()


def _target(host: Host) -> HostTarget:
    return HostTarget(host.id, host.name, host.connect_address)


def _two_widths(saved: object) -> tuple[int, int] | None:
    """The side panels' saved widths, when the settings hold two real ones."""
    if isinstance(saved, list) and len(saved) == 2:
        left, right = saved
        if isinstance(left, int) and isinstance(right, int) and left > 0 and right > 0:
            return left, right
    return None
