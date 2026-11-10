"""The User profiles tool: the Windows profiles on one PC, which of them can be deleted, and how
big they are. Three panels, as Hosts: the open host list's PCs, the profiles, one profile's
details. It keeps no list of its own: the PCs are Hosts' open list, and the account that signs
in to a PC is the one Hosts' Accounts give it. Scanning and counting sizes only read."""

import os
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QStackedWidget, QVBoxLayout, QWidget

from capypanel.core.i18n import _
from capypanel.core.remote import user_profiles
from capypanel.core.remote.access import Account
from capypanel.core.remote.user_profiles import Deleted, Kind, Outcome, Profile, Scan, Why
from capypanel.ui.checks import clock_text
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.accounts import windows_account
from capypanel.ui.hosts_tool.runner import HostTarget, Job
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.icons import STATUS_COLORS, tabler_icon
from capypanel.ui.list_workspace.splitter import PaneSplitter
from capypanel.ui.main_window.tool import Shell, Tool
from capypanel.ui.main_window.toolbar import ToolBar, tool_button
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.panels import (
    ALL_GROUPS,
    LEFT,
    RIGHT,
    DeleteDialog,
    HeaderCard,
    HintCard,
    PcPane,
    ProfileDetails,
    ProfilesTable,
    ProgressPanel,
    Shown,
)
from capypanel.ui.profiles_tool.rows import Result

SIZES_AT_ONCE = 4  # folders counted at the same time: walking a tree is mostly waiting
PANES_KEY = "panes"  # the side panels' widths, in the tool's settings
GROUPS_KEY = "groups"  # the group each host list was left on, by the list's file
PROGRESS_WIDTH = 320  # px: the progress panel is at least this wide, for its queue's columns


class ProfilesToolBar(ToolBar):
    def __init__(self) -> None:
        super().__init__()
        self.rescan_button = tool_button()
        self.sizes_button = tool_button()
        self.delete_button = tool_button()
        self.delete_button.setProperty("risky", True)  # amber, as every action that destroys
        self._counting = False
        self.add_group([self.rescan_button, self.sizes_button])
        self.add_group([self.delete_button])
        self.retranslate()

    def show_counting(self, counting: bool) -> None:
        """While sizes are counted, the button stops the count."""
        self._counting = counting
        self.restyle()

    def retranslate(self) -> None:
        gap = " "  # the stylesheet drops the gap between icon and text
        self.rescan_button.setText(gap + _("Scan again"))
        self.rescan_button.setToolTip(_("Read this PC's profiles again"))
        if self._counting:
            self.sizes_button.setText(gap + _("Stop counting"))
            self.sizes_button.setToolTip(_("Stop at once; sizes already counted stay"))
        else:
            self.sizes_button.setText(gap + _("Calculate sizes"))
            self.sizes_button.setToolTip(
                _("Count the size of each profile shown; it only reads, and can take minutes")
            )
        self.delete_button.setText(gap + _("Delete ticked…"))
        self.delete_button.setToolTip(
            _("Delete the profiles ticked, after a question that lists them")
        )

    def restyle(self) -> None:
        """Icons in the theme's text colour."""
        color = self.rescan_button.palette().color(QPalette.ColorRole.ButtonText)
        self.rescan_button.setIcon(tabler_icon("refresh", color))
        self.sizes_button.setIcon(tabler_icon("x" if self._counting else "report-analytics", color))
        self.show_delete(self.delete_button.isEnabled())
        self.retranslate()

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
        self._target: HostTarget | None = None  # the PC on show: scanned, or tried
        self._scan: Scan | None = None
        self._account: Account | None = None  # who signed in for the scan; None: Windows'
        self._account_name = ""
        self._scanning = False
        self._read_at = datetime.now().astimezone()  # when the scan on show was read
        self._scan_run = 0  # an answer for an older scan is dropped
        self._sizes: dict[str, int | None] = {}  # bytes per row; None while it's counted
        self._waiting: list[Profile] = []  # rows still to count
        self._count_run = 0  # counts of a stopped run are dropped, and stop themselves
        self._active = 0  # counts running now
        self._uncounted = 0  # folders the last run couldn't read
        self._results: dict[str, Result] = {}  # where each row of a delete run stands
        self._done: dict[str, Deleted] = {}  # how each delete ended
        self._queue: list[Profile] = []  # ticked rows still to delete
        self._run: list[Profile] = []  # every row of the delete run, in its order
        self._deleting = False
        self._cancelled = False
        self._began = datetime.now().astimezone()  # when the delete run started
        self._freed = 0  # bytes of the deleted rows that had been counted
        self._side_width = 0  # Details' width before the progress panel widened it
        self._jobs: set[Job] = set()

        self.pcs = PcPane(self._list_choices)
        self.header = HeaderCard()
        self.table = ProfilesTable()
        self.details = ProfileDetails()
        self.progress = ProgressPanel()
        self._side = QStackedWidget()  # Details, or the progress of a delete run
        self._side.addWidget(self.details)
        self._side.addWidget(self.progress)
        self._card_page = QWidget()
        self._card_box = QVBoxLayout(self._card_page)
        self._card_box.setContentsMargins(0, 0, 0, 0)
        self.card: HintCard | None = None
        self._stack = QStackedWidget()
        self._stack.addWidget(self._card_page)
        self._stack.addWidget(self.table)
        middle = QWidget()
        column = QVBoxLayout(middle)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(self.header)
        column.addWidget(self._stack, 1)
        self.splitter = PaneSplitter()
        for pane in (self.pcs, middle, self._side):
            self.splitter.addWidget(pane)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)  # dragged all the way, a panel would vanish
        left, right = _two_widths(self.prefs.get(PANES_KEY)) or (LEFT, RIGHT)
        self.splitter.setSizes([left, max(400, 1100 - left - right), right])
        self.splitter.splitterMoved.connect(self.align_toolbar_later)
        margins = QVBoxLayout(self)
        margins.setContentsMargins(8, 4, 8, 4)  # as the Hosts page
        margins.addWidget(self.splitter)

        bar = self.bar
        bar.rescan_button.clicked.connect(self.scan_again)
        bar.sizes_button.clicked.connect(self.toggle_sizes)
        bar.delete_button.clicked.connect(self.delete_ticked)
        self.table.ticked_changed.connect(self._ticks_changed)
        self.progress.cancel_requested.connect(self.cancel_rest)
        self.progress.log_requested.connect(self.open_log)
        self.progress.closed.connect(self._close_progress)
        self.pcs.scan_requested.connect(self.scan)
        self.pcs.list_picked.connect(self._pick_list)
        self.pcs.group_picked.connect(self._keep_group)
        self.header.filters_changed.connect(self._show_rows)
        self.table.picked.connect(self._show_details)
        self.details.copied.connect(
            lambda text: shell.show_message(_("Copied: {text}").format(text=text), 5000)
        )
        if self._hosts is not None:
            self._hosts.list_changed.connect(self._show_list)
        self._show_list()
        self._show_start()

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
        return self.pcs

    def save_state(self) -> None:
        sizes = self.splitter.sizes()
        if len(sizes) == 3 and all(sizes):
            self.prefs[PANES_KEY] = [sizes[0], sizes[2]]

    def retranslate(self) -> None:
        self.toolbar.retranslate()
        self.pcs.retranslate()
        self.header.retranslate()
        self.table.retranslate()
        self.progress.retranslate()
        self._show_list()
        self._show_again()

    def restyle(self) -> None:
        super().restyle()
        self._show_again()  # greyed rows and icons take the new theme's colours

    # ---- the PCs ----

    def _list_choices(self) -> list[tuple[Any, str, bool]]:
        return self._hosts.list_choices() if self._hosts is not None else []

    def _pick_list(self, path: Any) -> None:
        if self._hosts is not None:
            self._hosts.pick_list(path)

    def _show_list(self) -> None:
        """Hosts opened another list, or the open one changed."""
        doc = self._hosts.document if self._hosts is not None else None
        if doc is None:
            self.pcs.show_list(_("No list open"), "", None)
            return
        name = next((n for _p, n, current in self._list_choices() if current), doc.path.stem)
        self.pcs.show_list(name, str(doc.path), doc.hosts, self._group_of(str(doc.path)))

    def _group_of(self, list_path: str) -> str:
        """The group this list was left on, here."""
        kept = self.prefs.get(GROUPS_KEY)
        group = kept.get(list_path) if isinstance(kept, dict) else None
        return group if isinstance(group, str) else ALL_GROUPS

    def _keep_group(self, group: str) -> None:
        doc = self._hosts.document if self._hosts is not None else None
        if doc is None:
            return
        kept = self.prefs.get(GROUPS_KEY)
        kept = dict(kept) if isinstance(kept, dict) else {}
        if group == ALL_GROUPS:
            kept.pop(str(doc.path), None)
        else:
            kept[str(doc.path)] = group
        self.prefs[GROUPS_KEY] = kept
        self._shell.save_prefs()

    # ---- scanning ----

    def scan(self, target: HostTarget) -> None:
        """Reads `target`'s profiles. Nothing on the PC changes."""
        if self._scanning or self._deleting or self._hosts is None:
            return
        go, account = self._hosts.accounts.account_for(target, self.window())
        if not go:
            return  # its password wasn't typed
        self.stop_sizes()
        self._results, self._done, self._run = {}, {}, []  # a new scan forgets the last run
        self._close_progress()
        same = self._target is not None and self._target.key == target.key
        kept = dict(self._sizes) if same else {}  # sizes counted before, for rows still there
        self._target, self._scan, self._sizes = target, None, {}
        self._account = account
        self._account_name = account.user if account is not None else windows_account()
        self._scanning = True
        self._scan_run += 1
        run = self._scan_run
        self.header.show_pc(target.name, self._about(_("reading…")))
        self._show_card(
            HintCard(
                "refresh",
                self._muted(),
                _("Reading {host}'s profiles…").format(host=target.name),
                [_("This only reads. Nothing on the PC changes.")],
            )
        )
        self.details.show_hint(_("Scan a PC to see its profiles."))
        self.status_label.setText(_("{host} · reading…").format(host=target.name))
        self._update_bar()

        def done(found: Scan) -> None:
            if run != self._scan_run:
                return
            self._scanning = False
            self._scan = found
            idents = {p.ident for p in found.profiles}
            self._sizes = {i: s for i, s in kept.items() if i in idents and s is not None}
            self._read_at = datetime.now().astimezone()
            self._show_scan()

        def failed(error: BaseException) -> None:
            if run != self._scan_run:
                return
            self._scanning = False
            self._show_failure(target, error)

        self._start(lambda: user_profiles.scan(target.address, account), done, failed)

    def scan_again(self) -> None:
        if self._target is not None:
            self.scan(self._target)

    def _about(self, what: str) -> str:
        """The header's line: "192.0.2.13 · read at 10:41 · as EXAMPLE\\support"."""
        target = self._target
        assert target is not None
        parts = [what, _("as {account}").format(account=self._account_name)]
        if target.address != target.name:
            parts.insert(0, target.address)
        return " · ".join(parts)

    def _show_start(self) -> None:
        """Before any scan: what to do."""
        self.header.hide()
        self._show_card(
            HintCard(
                self.ICON,
                self._muted(),
                _("Choose a PC"),
                [
                    _("Pick a PC in the list and click Scan, or double-click it."),
                    _("For a PC that isn't in the list, type its name or address in "
                      "\"Another PC\"."),
                    "",
                    _("Scanning only reads. Nothing is deleted before you tick it, ask for it "
                      "and confirm."),
                ],
            )
        )  # fmt: skip
        self.details.show_hint(_("Scan a PC to see its profiles."))
        self.status_label.setText(_("No PC scanned"))
        self._update_bar()

    def _show_scan(self) -> None:
        target = self._target
        assert target is not None
        when = clock_text(self._read_at)
        self.header.show_pc(target.name, self._about(_("read at {time}").format(time=when)))
        self.header.filters.show()
        self.header.show()
        self._stack.setCurrentWidget(self.table)
        if target.key and not target.key.startswith("@"):
            self.pcs.pick(target.key)
        self._show_rows()
        self._update_bar()

    def _show_failure(self, target: HostTarget, error: BaseException) -> None:
        said = rows.failure(error, target.name, target.address, self._account_name)
        when = clock_text(datetime.now().astimezone())
        self.header.show_pc(target.name, self._about(_("tried at {time}").format(time=when)))
        buttons: list[tuple[str, Callable[[], None]]] = []
        hosts = self._hosts
        if said.another_account and hosts is not None:
            buttons.append(
                (
                    _("Try another account…"),
                    lambda: hosts.runner.another_account(target, error, lambda: self.scan(target)),
                )
            )
        buttons.append((_("Try again"), lambda: self.scan(target)))
        color = QColor(STATUS_COLORS["stopped"])
        self._show_card(HintCard("circle-x", color, said.title, said.lines, buttons))
        self.details.show_hint(_("Scan a PC to see its profiles."))
        self.status_label.setText(said.status)
        self._update_bar()

    def _show_card(self, card: HintCard) -> None:
        """A card in the middle instead of the table; the header keeps only the PC's name."""
        old, self.card = self.card, card
        if old is not None:
            self._card_box.removeWidget(old)
            old.deleteLater()
        self._card_box.addWidget(card)
        self._stack.setCurrentWidget(self._card_page)
        self.header.filters.hide()
        self.header.setVisible(self._target is not None)

    def _show_again(self) -> None:
        """Everything on show drawn again: another language, or another theme."""
        if self._scanning:
            return
        if self._scan is not None:
            self._show_scan()
        elif self._target is None:
            self._show_start()

    # ---- the rows ----

    def _show_rows(self) -> None:
        if self._scan is None or self._target is None:
            return
        shown = rows.visible(self._scan.profiles, self.header.chosen())
        self.table.show_profiles(shown, self._sizes, self._results)
        self.header.shown.setText(rows.shown_text(len(shown), len(self._scan.profiles)))
        self._show_status()

    def _counted(self) -> dict[str, int]:
        return {i: s for i, s in self._sizes.items() if s is not None}

    def _show_status(self) -> None:
        if self._scan is None or self._target is None or self._deleting:
            return
        if self._run:  # a delete run ended: what it did stays until the next scan
            return
        self.status_label.setText(
            rows.status_text(self._scan, self._target.name, self.table.ticked(), self._counted())
        )

    def _ticks_changed(self) -> None:
        self._show_status()
        self._update_bar()

    def _show_details(self) -> None:
        profile = self.table.selected() if self._scan is not None else None
        if profile is None or self._scan is None:
            self.details.show_hint(
                "" if self._scan is not None else _("Scan a PC to see its profiles.")
            )
            return
        size = self._sizes.get(profile.ident)
        counting = profile.ident in self._sizes and size is None
        result, done = self._results.get(profile.ident), self._done.get(profile.ident)
        self.details.show_item(Shown(profile, self._scan.root, size, counting, result, done), 1)

    # ---- sizes ----

    def counting(self) -> bool:
        return bool(self._active or self._waiting)

    def toggle_sizes(self) -> None:
        if self.counting():
            self.stop_sizes()
        else:
            self.count_sizes()

    def count_sizes(self) -> None:
        """Counts the folder of every row shown that isn't counted yet, a few at a time."""
        if self._scan is None or self.counting():
            return
        self._waiting = [
            p for p in self.table.shown()
            if p.path and p.kind is not Kind.ENTRY and p.ident not in self._sizes
        ]  # fmt: skip
        if not self._waiting:
            self._shell.show_message(_("Every folder shown is already counted."))
            return
        self._uncounted = 0
        self._count_run += 1
        for _slot in range(SIZES_AT_ONCE):
            self._count_next()
        self._update_bar()

    def stop_sizes(self) -> None:
        """At once: it only reads, so nothing is left half done. Sizes counted stay."""
        if not self.counting():
            return
        self._count_run += 1  # the counts under way stop themselves and are dropped
        self._waiting, self._active = [], 0
        for ident in [i for i, size in self._sizes.items() if size is None]:
            del self._sizes[ident]
            self.table.show_size(ident, self._sizes)
        self._show_details()
        self._update_bar()

    def _count_next(self) -> None:
        scanned = self._scan
        if not self._waiting or scanned is None:
            if not self._active:
                self._sizes_counted()
            return
        profile, run, account = self._waiting.pop(0), self._count_run, self._account
        self._active += 1
        self._sizes[profile.ident] = None
        self._show_size(profile)

        def ended(size: int | None) -> None:
            if run != self._count_run:
                return
            self._active -= 1
            if size is None:
                del self._sizes[profile.ident]
                self._uncounted += 1
            else:
                self._sizes[profile.ident] = size
            self._show_size(profile)
            self._show_status()
            self._count_next()

        self._start(
            lambda: user_profiles.profile_size(
                scanned, profile, account, stop=lambda: run != self._count_run
            ),
            ended,
            lambda _error: ended(None),
        )

    def _show_size(self, profile: Profile) -> None:
        self.table.show_size(profile.ident, self._sizes)
        picked = self.table.selected()
        if picked is not None and picked.ident == profile.ident:
            self._show_details()

    def _sizes_counted(self) -> None:
        """The last count of a run ended."""
        self._update_bar()
        if self._uncounted:
            self._shell.show_message(
                _("Sizes counted; {n} couldn't be read.").format(n=self._uncounted)
            )
        else:
            self._shell.show_message(_("Sizes counted."))

    # ---- deleting ----

    def delete_ticked(self) -> None:
        """Asks, listing the ticked rows, then deletes them one at a time."""
        target, scanned = self._target, self._scan
        ticked = self.table.ticked()
        if target is None or scanned is None or not ticked or self._deleting:
            return
        self.stop_sizes()
        dialog = DeleteDialog(self.window(), target.name, ticked, self._counted())
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._delete(ticked)

    def _delete(self, profiles: list[Profile]) -> None:
        self._deleting, self._cancelled = True, False
        self._run, self._queue = list(profiles), list(profiles)
        self._results, self._done, self._freed = {}, {}, 0
        self._began = datetime.now().astimezone()
        self.table.lock(True)
        self.progress.start(profiles)
        for profile in profiles:
            self._set_result(profile, Result.QUEUED)
        self._open_progress()
        self._update_bar()
        self._delete_next()

    def cancel_rest(self) -> None:
        """The profile being deleted finishes; the ones still queued don't start."""
        if not self._deleting or self._cancelled:
            return
        self._cancelled = True
        left, self._queue = self._queue, []
        for profile in left:
            self._set_result(profile, None)
        if left:
            self._log(_("cancelled: {n} not started").format(n=len(left)))

    def _delete_next(self) -> None:
        target, scanned = self._target, self._scan
        if not self._queue or target is None or scanned is None:
            self._delete_over()
            return
        profile, account = self._queue.pop(0), self._account
        self._set_result(profile, Result.DELETING)
        ended = sum(result in rows.ENDED for result in self._results.values())
        total = ended + 1 + len(self._queue)
        since = clock_text(self._began)
        self.progress.show_progress(
            _("{host} · {n} of {total} · since {time}").format(
                host=target.name, n=ended + 1, total=total, time=since
            ),
            ended,
        )
        status = _("{host} · deleting {n} of {total}").format(
            host=target.name, n=ended + 1, total=total
        )
        counts = rows.counts_text(self._results.values())
        self.status_label.setText(f"{status} · {counts}" if counts else status)
        self._log(f"{profile.user}: " + _("checking and deleting…"))
        log_file = self._shell.paths.user_profiles_log_file

        def done(ended: Deleted) -> None:
            size = self._sizes.get(profile.ident)
            self._done[profile.ident] = ended
            if ended.outcome is Outcome.DELETED and size:
                self._freed += size
            self._log(f"{profile.user}: " + rows.ended_text(ended, size))
            self._set_result(profile, rows.result_of(ended))
            self._delete_next()

        self._start(
            lambda: user_profiles.delete(scanned, profile, account, log_file=log_file),
            done,
            lambda error: done(Deleted(profile, Outcome.FAILED, Why.ERROR, str(error))),
        )

    def _delete_over(self) -> None:
        target = self._target
        assert target is not None
        self._deleting = False
        self.table.lock(False)
        results = [self._results[p.ident] for p in self._run if p.ident in self._results]
        counts = rows.counts_text(results) or _("nothing deleted")
        times = _("{start} to {end}").format(
            start=clock_text(self._began), end=clock_text(datetime.now().astimezone())
        )
        freed = _("{size} freed").format(size=rows.size_text(self._freed)) if self._freed else ""
        self.progress.finish(f"{target.name} · {counts}", f"{freed} · {times}" if freed else times)
        parts = [target.name, *counts.split(", ")]
        if freed:
            parts.append(freed)
        self.status_label.setText(" · ".join(parts))
        self._show_details()
        self._update_bar()

    def _set_result(self, profile: Profile, result: Result | None) -> None:
        if result is None:
            self._results.pop(profile.ident, None)
        else:
            self._results[profile.ident] = result
        self.table.show_result(profile.ident, result)
        self.progress.show_result(profile.ident, result)
        picked = self.table.selected()
        if picked is not None and picked.ident == profile.ident:
            self._show_details()

    def _log(self, text: str) -> None:
        """A line in the progress panel's log: the time, then what happened."""
        self.progress.add_line(f"{datetime.now().astimezone():%H:%M}  {text}")

    def open_log(self) -> None:
        """The file every delete is written to, in whatever opens text files."""
        log_file = self._shell.paths.user_profiles_log_file
        if log_file.exists():
            os.startfile(log_file)  # noqa: S606 (Windows' own "open", as a double-click)
        else:
            self._shell.show_message(_("The log has nothing yet."))

    def _open_progress(self) -> None:
        """The progress panel takes Details' place, a little wider when Details was narrow."""
        self._side.setCurrentWidget(self.progress)
        sizes = self.splitter.sizes()
        if len(sizes) == 3 and 0 < sizes[2] < PROGRESS_WIDTH:
            self._side_width = sizes[2]
            wider = PROGRESS_WIDTH - sizes[2]
            self.splitter.setSizes([sizes[0], max(200, sizes[1] - wider), PROGRESS_WIDTH])

    def _close_progress(self) -> None:
        """Details again, at the width it had."""
        if self._deleting or self._side.currentWidget() is self.details:
            return
        self._side.setCurrentWidget(self.details)
        sizes = self.splitter.sizes()
        if self._side_width and len(sizes) == 3:
            back = sizes[2] - self._side_width
            self.splitter.setSizes([sizes[0], sizes[1] + back, self._side_width])
        self._side_width = 0
        self._show_details()

    # ---- the toolbar, and work off the main thread ----

    def _update_bar(self) -> None:
        bar = self.bar
        busy = self._scanning or self._deleting
        bar.rescan_button.setEnabled(self._target is not None and not busy)
        bar.sizes_button.setEnabled(self._scan is not None and not busy)
        bar.show_counting(self.counting())
        bar.show_delete(self._scan is not None and not busy and bool(self.table.ticked()))
        self.pcs.setEnabled(not busy)

    def _muted(self) -> QColor:
        return self.palette().color(QPalette.ColorRole.PlaceholderText)

    def _start(
        self,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        """`work` on a background thread; its value or its error comes back on this one."""
        job = Job(work)
        self._jobs.add(job)

        def finish(value: object, error: object) -> None:
            self._jobs.discard(job)
            if isinstance(error, BaseException):
                failed(error)
            else:
                done(value)

        job.done.connect(finish)
        job.start()


def _two_widths(saved: object) -> tuple[int, int] | None:
    """The side panels' saved widths, when the settings hold two real ones."""
    if isinstance(saved, list) and len(saved) == 2:
        left, right = saved
        if isinstance(left, int) and isinstance(right, int) and left > 0 and right > 0:
            return left, right
    return None
