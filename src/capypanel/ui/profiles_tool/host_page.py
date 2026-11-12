"""One host's tab in the User profiles tool: its box (the name, the filters, the profiles table),
and on the right its card (the profiles ticked, or the delete run) with the Delete button at the
foot. A profile's details open in a window. Each tab keeps its own scan, sizes and delete run, so
several hosts can be read, counted and cleaned at once."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QStackedWidget, QVBoxLayout, QWidget

from capypanel.core.i18n import N_, _, ngettext
from capypanel.core.remote import user_profiles
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.user_profiles import Deleted, Kind, Outcome, Profile, Scan, Why
from capypanel.ui.checks import clock_text
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.command_windows import log_failed
from capypanel.ui.hosts_tool.runner import HostTarget, Job
from capypanel.ui.profiles_tool import rows, work
from capypanel.ui.profiles_tool.panels import (
    DeleteDialog,
    FilterRow,
    HintCard,
    ProfilesTable,
    Shown,
    TabBox,
)
from capypanel.ui.profiles_tool.rows import Result
from capypanel.ui.profiles_tool.side import Entry, Foot, ProfileWindow, RunCard, TickedCard
from capypanel.ui.themes import engine as themes


class Stage(Enum):
    """Where a host's scan is."""

    QUEUED = "queued"  # waiting for a turn among the reads
    SCANNING = "scanning"
    SCANNED = "scanned"
    FAILED = "failed"


@dataclass(frozen=True)
class Mark:
    """How a tab shows where its host is: an icon (none when it's simply scanned), its words
    for the tooltip, and the shorter words the Hosts tab and Andamento use."""

    icon: str
    color: str
    tip: str  # "Deleting the 2nd of 3 profiles…"
    short: str  # "deleting 2 of 3"
    busy: bool  # it's working: Andamento's "In progress"
    bad: bool = False  # it ended badly: red in Andamento


# A run's line on the card: each profile's words on the right, and their colour: one of
# the theme's status colours ("": grey).
_RUN_WORDS = {
    Result.QUEUED: (N_("queued"), ""),
    Result.DELETING: (N_("deleting…"), "working"),
    Result.DELETED: (N_("deleted"), ""),
    Result.SKIPPED: (N_("skipped"), ""),
    Result.FAILED: (N_("failed"), "stopped"),
}


@dataclass
class Context:
    """What a host's tab needs from the tool."""

    pool: work.Pool
    log_file: Callable[[], Path]  # the history's file
    message: Callable[[str], None]  # a note in the status bar
    gap: int  # px between the right panel's cards: the gap between the panels
    another_account: Callable[[HostTarget, BaseException, Callable[[], None]], None] | None


class HostPage(QObject):
    """A host's tab: `box` goes in the middle, `side` on the right under Progress; the tool
    shows both."""

    changed = Signal()  # the mark, the counts or the toolbar may differ now
    status_changed = Signal()  # the status bar's text

    def __init__(self, target: HostTarget, account: Account | None, account_name: str,
                 context: Context) -> None:  # fmt: skip
        super().__init__()
        self.target = target
        self._account = account  # who signs in; None: Windows' own account
        self.account_name = account_name
        self._ctx = context
        self.stage = Stage.QUEUED
        self.scan: Scan | None = None
        self.read_at: datetime | None = None
        self.error: BaseException | None = None
        self._scan_run = 0  # an answer for an older scan is dropped
        self._sizes: dict[str, int | None] = {}  # bytes per row; None while it's counted
        self._counting: object | None = None  # the size count under way: the pool's owner
        self._count_total = 0
        self._count_left = 0  # counts not ended yet
        self._uncounted = 0
        self._so_far: dict[str, int] = {}  # bytes counted up to now, written by the counts
        self._ticker = QTimer(self)  # shows them moving, so a long count isn't taken for stuck
        self._ticker.setInterval(700)
        self._ticker.timeout.connect(self._show_so_far)
        self._results: dict[str, Result] = {}
        self._done: dict[str, Deleted] = {}
        self._queue: list[Profile] = []
        self._run: list[Profile] = []
        self.deleting = False
        self._cancelled = False
        self._began = datetime.now().astimezone()
        self._ended = self._began  # when the last run was over
        self._run_shown = False  # the card shows a delete run, under way or just over
        self._window: ProfileWindow | None = None  # a profile's details, while it's open
        self._window_ident = ""
        self._freed = 0
        self._jobs: set[Job] = set()

        self.filters = FilterRow()
        self.table = ProfilesTable()
        self._card_page = QWidget()
        self._card_box = QVBoxLayout(self._card_page)
        self._card_box.setContentsMargins(0, 0, 0, 0)
        self.card: HintCard | None = None
        self._stack = QStackedWidget()
        self._stack.addWidget(self._card_page)
        self._stack.addWidget(self.table)
        self.box = TabBox(self.filters, self._stack)
        self.ticked_card = TickedCard()
        self.run_card = RunCard()
        self.cards = QStackedWidget()
        self.cards.addWidget(self.ticked_card)
        self.cards.addWidget(self.run_card)
        self.foot = Foot()
        self.side = QWidget()
        column = QVBoxLayout(self.side)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(context.gap)
        column.addWidget(self.cards, 1)
        column.addWidget(self.foot)
        self.filters.changed.connect(self._show_rows)
        self.table.ticked_changed.connect(self._ticks_changed)
        self.table.details_requested.connect(self.show_details)
        self.ticked_card.picked.connect(self.table.select)
        self.run_card.picked.connect(self.table.select)
        self.run_card.log_requested.connect(self.open_log)
        self.run_card.closed.connect(self.close_progress)
        self.foot.delete_button.clicked.connect(lambda: self.delete_ticked(self.side.window()))
        self.foot.cancel_button.clicked.connect(self.cancel_rest)
        self._show_waiting()

    # ---- what the tab and the Hosts tab show ----

    def mark(self) -> Mark:
        """The tab's mark: deleting first, then counting, then the scan's own stage."""
        if self.deleting:
            ended, total = self._run_counts()
            return Mark(
                "trash",
                themes.status_color("attention"),
                _("Deleting profile {n} of {total}. The tab can't close until it ends; use "
                  "Cancel the rest.").format(n=ended + 1, total=total),
                _("deleting {n} of {total}").format(n=ended + 1, total=total),
                busy=True,
            )  # fmt: skip
        if self._counting is not None:
            done = self._count_total - self._count_left
            return Mark(
                "report-analytics",
                themes.status_color("working"),
                _("Calculating sizes: {n} of {total}").format(n=done, total=self._count_total),
                _("calculating sizes"),
                busy=True,
            )
        if self.stage is Stage.QUEUED:
            return Mark("clock", themes.status_color("offline"), _("Waiting to scan"), _("queued"),
                        busy=False)  # fmt: skip
        if self.stage is Stage.SCANNING:
            return Mark(
                "refresh",
                themes.status_color("working"),
                _("Scanning the profiles…"),
                _("scanning…"),
                busy=True,
            )
        if self.stage is Stage.FAILED:
            return Mark("circle-x", themes.status_color("stopped"), self._failure_tip(),
                        self._failure_short(), busy=False, bad=True)  # fmt: skip
        if self._run:
            results = [self._results[p.ident] for p in self._run if p.ident in self._results]
            deleted = results.count(Result.DELETED)
            freed = (
                _("{size} freed").format(size=rows.size_text(self._freed)) if self._freed else ""
            )
            if deleted == len(self._run):
                tip = ngettext("{n} profile deleted", "{n} profiles deleted", deleted).format(
                    n=deleted
                )
                return Mark("circle-check", themes.status_color("online"), tip, freed or tip,
                            busy=False)  # fmt: skip
            counts = rows.counts_text(results) or _("nothing deleted")
            tip = _("{counts}. See the history.").format(counts=counts)
            return Mark("alert-triangle", themes.status_color("attention"), tip, freed or counts,
                        busy=False)  # fmt: skip
        when = clock_text(self.read_at) if self.read_at else ""
        return Mark("", "", _("Scanned at {time}").format(time=when), when, busy=False)

    def progress_words(self) -> str:
        """Its words on Progress's line: where it is, or "scanned at 10:41" once it's read."""
        scanned = self.stage is Stage.SCANNED and not self.deleting and self._counting is None
        if scanned and not self._run and self.read_at is not None:
            return _("scanned at {time}").format(time=clock_text(self.read_at))
        return self.mark().short

    def order(self) -> int:
        """Where Progress lists it: deleting, scanning, counting, waiting, then the ones done,
        the failed ones last."""
        if self.deleting:
            return 0
        if self.stage is Stage.SCANNING:
            return 1
        if self._counting is not None:
            return 2
        if self.stage is Stage.QUEUED:
            return 3
        return 5 if self.stage is Stage.FAILED else 4

    def tab_text(self) -> str:
        """The tab's name: the host's, and "· 2/3" while it deletes."""
        if self.deleting:
            ended, total = self._run_counts()
            return f"{self.target.name} · {ended + 1}/{total}"
        return self.target.name

    def scan_words(self) -> str:
        """The Hosts tab's Scan column: the time, or where the host is."""
        if self.deleting:
            return self.mark().short
        if self.stage is Stage.SCANNED:
            return clock_text(self.read_at) if self.read_at else ""
        if self.stage is Stage.FAILED:
            return self._failure_short()
        return self.mark().short

    def counts(self) -> tuple[int, int] | None:
        """(profiles, how many can be deleted), once scanned."""
        if self.scan is None:
            return None
        return len(self.scan.profiles), sum(p.ready for p in self.scan.profiles)

    def busy(self) -> bool:
        """Reading, counting or deleting: what Close all finished leaves open."""
        return self.mark().busy or self.stage is Stage.QUEUED

    def status_text(self) -> str:
        if self.deleting:
            ended, total = self._run_counts()
            return _("{host} · deleting profile {n} of {total}").format(
                host=self.target.name, n=ended + 1, total=total
            )
        if self.stage is Stage.FAILED and self.error is not None:
            return self._said().status
        if self.scan is None:
            return f"{self.target.name} · {self.mark().short}"
        if self._counting is not None:
            done = self._count_total - self._count_left
            text = _("{host} · calculating sizes: {n} of {total}").format(
                host=self.target.name, n=done, total=self._count_total
            )
            counted = sum(self._counted().values()) + sum(
                size for ident, size in self._so_far.items() if self._sizes.get(ident, 0) is None
            )
            if counted:
                text += " · " + _("{size} so far").format(size=rows.size_text(counted))
            return text
        if self._run:
            results = [self._results[p.ident] for p in self._run if p.ident in self._results]
            parts = [self.target.name, *(rows.counts_text(results) or _("nothing deleted"))
                     .split(", ")]  # fmt: skip
            if self._freed:
                parts.append(_("{size} freed").format(size=rows.size_text(self._freed)))
            return " · ".join(parts)
        return rows.status_text(self.scan, self.target.name, self.table.ticked(), self._counted())

    def about(self) -> str:
        """The box's grey line: "192.0.2.13 · scanned at 10:41 · as EXAMPLE\\support"."""
        parts = []
        if self.target.address != self.target.name:
            parts.append(self.target.address)
        if self.stage is Stage.SCANNED and self.read_at is not None:
            parts.append(_("scanned at {time}").format(time=clock_text(self.read_at)))
        elif self.stage is Stage.FAILED:
            parts.append(_("tried at {time}").format(time=clock_text(self.read_at or self._now())))
        else:
            parts.append(self.mark().short)
        parts.append(_("as {account}").format(account=self.account_name))
        return " · ".join(parts)

    # ---- scanning ----

    def start_scan(self) -> None:
        """Waits for a turn among the reads, then reads the host's profiles. Nothing on the PC
        changes."""
        if self.deleting:
            return
        self.stop_sizes()
        self._results, self._done, self._run = {}, {}, []  # a new scan forgets the last run
        self.close_progress()
        kept = {i: s for i, s in self._sizes.items() if s is not None}
        self.scan, self.error, self.stage = None, None, Stage.QUEUED
        self._scan_run += 1
        run, target, account = self._scan_run, self.target, self._account
        self._ctx.pool.drop(self)  # an older read still waiting
        self._show_waiting()

        def read() -> Scan:
            return user_profiles.scan(target.address, account)

        def began() -> None:
            if run == self._scan_run:
                self.stage = Stage.SCANNING
                self._show_waiting()

        def done(found: Scan) -> None:
            if run != self._scan_run:
                return
            self.stage, self.scan = Stage.SCANNED, found
            idents = {p.ident for p in found.profiles}
            self._sizes = {i: s for i, s in kept.items() if i in idents}
            self.read_at = self._now()
            self._show_scan()

        def failed(error: BaseException) -> None:
            log_failed("User profiles scan", target.name, error)
            if run != self._scan_run:
                return
            self.stage, self.error, self.read_at = Stage.FAILED, error, self._now()
            self._show_failure()

        self._ctx.pool.read(self, read, done, failed, began)

    def show_sample(self, scan: Scan) -> None:
        """A guide's sample tab: a scan made up for it, nothing read from or done on any PC."""
        self.stage, self.scan, self.read_at = Stage.SCANNED, scan, self._now()
        self._show_scan()

    def close(self) -> None:
        """Its tab closes: sizes stop, waiting work never starts, and a read under way is
        ignored when it ends (its widgets are gone by then)."""
        self.stop_sizes()
        self._scan_run += 1
        self._ctx.pool.drop(self)

    def _show_waiting(self) -> None:
        """Queued or reading: a card in the table's place, the filters greyed."""
        reading = self.stage is Stage.SCANNING
        self._show_card(
            HintCard(
                "refresh" if reading else "clock",
                self._muted(),
                (_("Scanning {host}'s profiles…") if reading
                 else _("{host} waits for its turn")).format(host=self.target.name),
                [_("This only reads. Nothing on the host changes.")] if reading
                else [_("A few hosts are read at a time; this one starts when one ends.")],
            )
        )  # fmt: skip
        self._show_side()
        self._changed()

    def _show_scan(self) -> None:
        self.filters.setEnabled(True)
        self._stack.setCurrentWidget(self.table)
        self._show_rows()
        self._changed()

    def _said(self) -> rows.Failure:
        error = self.error or RuntimeError("")
        return rows.failure(error, self.target.name, self.target.address, self.account_name)

    def _failure_short(self) -> str:
        error = self.error
        if isinstance(error, RemoteError) and error.reason is Reason.UNREACHABLE:
            return _("didn't answer")
        if isinstance(error, RemoteError) and error.reason in (Reason.REJECTED, Reason.NOT_ADMIN):
            return _("account refused")
        return _("couldn't be read")

    def _failure_tip(self) -> str:
        error = self.error
        said = self._said()
        if isinstance(error, RemoteError) and error.reason in (Reason.REJECTED, Reason.NOT_ADMIN):
            refused = _("Refused the account {account}").format(account=self.account_name)
            return f"{refused}: {said.lines[0]}"
        return said.title

    def _show_failure(self) -> None:
        said = self._said()
        buttons: list[tuple[str, Callable[[], None]]] = []
        error, again = self.error, self._ctx.another_account
        if said.another_account and again is not None and error is not None:
            buttons.append(
                (_("Try another account…"), lambda: again(self.target, error, self.start_scan))
            )
        buttons.append((_("Try again"), self.start_scan))
        color = QColor(themes.status_color("stopped"))
        self._show_card(HintCard("circle-x", color, said.title, said.lines, buttons))
        self._show_side()
        self._changed()

    def _show_card(self, card: HintCard) -> None:
        old, self.card = self.card, card
        if old is not None:
            self._card_box.removeWidget(old)
            old.deleteLater()
        self._card_box.addWidget(card)
        self._stack.setCurrentWidget(self._card_page)
        self.filters.setEnabled(False)
        self.filters.show_count("")

    def show_again(self) -> None:
        """Everything drawn again: another language, or another theme."""
        self.filters.retranslate()
        self.table.retranslate()
        self._show_side()
        if self.stage is Stage.SCANNED:
            self._show_scan()
        elif self.stage is Stage.FAILED:
            self._show_failure()
        else:
            self._show_waiting()

    # ---- the rows ----

    def _show_rows(self) -> None:
        if self.scan is None:
            return
        shown = rows.visible(self.scan.profiles, self.filters.chosen())
        if self._run:  # a delete run's rows always show, whatever the filters
            seen = {p.ident for p in shown}
            extra = {p.ident for p in self._run} - seen
            shown = [p for p in self.scan.profiles if p.ident in seen or p.ident in extra]
        self.table.show_profiles(shown, self._sizes, self._results, self.scan.root)
        self._show_count()
        self._show_side()
        self.box.show_title(self.title(), self.about())
        self.status_changed.emit()

    def _counted(self) -> dict[str, int]:
        return {i: s for i, s in self._sizes.items() if s is not None}

    def ticked(self) -> list[Profile]:
        return self.table.ticked() if self.scan is not None else []

    def ticked_size(self) -> int:
        return sum(self._counted().get(p.ident, 0) for p in self.ticked())

    def _show_count(self) -> None:
        """Line 2's right end: how many rows show, or, with ticks, how many and their size."""
        if self.scan is None:
            return
        ticked = [] if self.deleting else self.ticked()  # a run under way: the State column
        words = short = ""
        if ticked:
            words = short = ngettext("{n} ticked", "{n} ticked", len(ticked)).format(n=len(ticked))
            if size := self.ticked_size():
                words += " · " + rows.size_text(size)
        showing, total = len(self.table.shown()), len(self.scan.profiles)
        self.filters.show_count(rows.shown_text(showing, total), words, short, str(len(ticked)),
                                rows.shown_short(showing, total))  # fmt: skip

    def title(self) -> str:
        """The box's first line: what this list is, so it's never taken for a list of hosts."""
        return _("User profiles on {host}").format(host=self.target.name)

    def _ticks_changed(self) -> None:
        self._show_count()
        self._show_side()
        self.status_changed.emit()
        self.changed.emit()

    # ---- the right panel ----

    def can_delete(self) -> bool:
        """Scanned, nothing under way, and something ticked."""
        idle = self.stage in (Stage.SCANNED, Stage.FAILED) and not self.deleting
        return self.scan is not None and idle and bool(self.ticked())

    def delete_text(self) -> str:
        """The Delete buttons' words, on the toolbar and at the panel's foot: they count."""
        n = len(self.ticked())
        if not n:
            return _("Delete profiles…")
        return ngettext("Delete {n} profile…", "Delete {n} profiles…", n).format(n=n)

    def delete_tip(self) -> str:
        if not self.ticked():
            return _("Tick profiles in the table to delete")
        return _("Deletes the profiles ticked on {host}, after a question that lists them").format(
            host=self.target.name
        )

    def ticked_words(self) -> str:
        """ "3 profiles · 12.4 GB": what's ticked here, for the Hosts tab's card."""
        n = len(self.ticked())
        words = ngettext("{n} profile", "{n} profiles", n).format(n=n)
        size = self.ticked_size()
        return f"{words} · {rows.size_text(size)}" if size else words

    def _show_side(self) -> None:
        """The card (what's ticked, or the delete run), the button at the foot, and the
        profile's window when it's open."""
        if self._run_shown:
            self._show_run()
            self.cards.setCurrentWidget(self.run_card)
        else:
            self.ticked_card.show_ticked(self.ticked(), self._counted(), self.scan is not None)
            self.cards.setCurrentWidget(self.ticked_card)
        if self.deleting:
            self.foot.show_cancel(not self._cancelled)
        else:
            self.foot.show_delete(self.delete_text(), self.can_delete(), self.delete_tip())
        self._show_window()

    def _show_run(self) -> None:
        ended, total = self._run_counts()
        entries = []
        for profile in self._run:
            result = self._results.get(profile.ident, Result.QUEUED)
            icon, color = rows.result_icon(result)
            size, done = self._sizes.get(profile.ident), self._done.get(profile.ident)
            words, words_color = _RUN_WORDS[result]
            words_color = themes.status_color(words_color) if words_color else ""
            words = _(words)
            if result is Result.DELETED and size:
                words = f"{words} · {rows.size_text(size)}"
            entries.append(
                Entry(
                    profile.ident,
                    rows.user_text(profile),
                    words,
                    icon,
                    color,
                    words_color,
                    tip=rows.ended_text(done, size) if done is not None else "",
                    muted=result is Result.QUEUED,
                )
            )
        if self.deleting:
            title = ngettext(
                "{n} of {total} profile", "{n} of {total} profiles", total
            ).format(n=min(ended + 1, total), total=total)  # fmt: skip
            second = _("since {time}").format(time=clock_text(self._began))
        else:
            results = [self._results[p.ident] for p in self._run if p.ident in self._results]
            title = rows.counts_text(results) or _("nothing deleted")
            second = _("{start} to {end}").format(
                start=clock_text(self._began), end=clock_text(self._ended)
            )
            if self._freed:
                freed = _("{size} freed").format(size=rows.size_text(self._freed))
                second = f"{freed} · {second}"
        self.run_card.show_run(not self.deleting, title, second, ended, total, entries)

    def show_details(self, ident: str = "") -> None:
        """A profile's details in their window: the row asked for, or the one clicked. It
        follows the row while it's open (its size being counted, its tick)."""
        profile = self.table.profile(ident) if ident else self.table.selected()
        if profile is None or self.scan is None:
            return
        window = ProfileWindow(self.side.window(), self.target.name, profile.user)
        window.copied.connect(lambda text: self._ctx.message(_("Copied: {text}").format(text=text)))
        window.tick_toggled.connect(lambda on, i=profile.ident: self.table.tick(i, on))
        self._window, self._window_ident = window, profile.ident
        self._show_window()
        try:
            run_modal(window)
        finally:
            self._window = None

    def _show_window(self) -> None:
        window, ident = self._window, self._window_ident
        profile = self.table.profile(ident) if window is not None else None
        if window is None or profile is None or self.scan is None:
            return
        size = self._sizes.get(ident)
        counting = ident in self._sizes and size is None
        shown = Shown(profile, self.scan.root, size, counting, self._results.get(ident),
                      self._done.get(ident))  # fmt: skip
        window.show_profile(shown, self.table.is_ticked(ident), self.table.can_tick(ident))

    # ---- sizes ----

    def counting(self) -> bool:
        return self._counting is not None

    def toggle_sizes(self) -> None:
        if self.counting():
            self.stop_sizes()
        else:
            self.count_sizes()

    def count_sizes(self) -> None:
        """Counts the folder of every row shown that isn't counted yet, a few at a time across
        every tab."""
        scanned = self.scan
        if scanned is None or self.counting() or self.deleting:
            return
        waiting = [
            p for p in self.table.shown()
            if p.path and p.kind is not Kind.ENTRY and p.ident not in self._sizes
        ]  # fmt: skip
        if not waiting:
            self._ctx.message(_("Every folder shown is already counted."))
            return
        owner = self._counting = object()
        self._count_total = self._count_left = len(waiting)
        self._uncounted = 0
        self._so_far = {}
        self._ticker.start()
        account = self._account
        for profile in waiting:
            self._sizes[profile.ident] = None
            self._show_size(profile)

            def ended(size: int | None, profile: Profile = profile) -> None:
                if self._counting is not owner:
                    return
                self._count_left -= 1
                if size is None:
                    self._sizes.pop(profile.ident, None)
                    self._uncounted += 1
                else:
                    self._sizes[profile.ident] = size
                self._show_size(profile)
                self.status_changed.emit()
                if not self._count_left:
                    self._sizes_counted()
                else:
                    self._changed()

            def so_far(counted: int, ident: str = profile.ident) -> None:
                if self._counting is owner:  # from the count's own thread: just the number
                    self._so_far[ident] = counted

            def count(profile: Profile = profile) -> int | None:
                return user_profiles.profile_size(
                    scanned,
                    profile,
                    account,
                    stop=lambda: self._counting is not owner,
                    progress=so_far,
                )

            def failed(error: BaseException, ended: Callable[[int | None], None] = ended,
                       user: str = profile.user) -> None:  # fmt: skip
                log_failed(f"Size of {user}", self.target.name, error)
                ended(None)

            self._ctx.pool.count(owner, count, ended, failed)
        self._changed()

    def stop_sizes(self) -> None:
        """At once: it only reads, so nothing is left half done. Sizes counted stay."""
        owner = self._counting
        if owner is None:
            return
        self._counting = None  # counts under way stop themselves and are dropped
        self._ticker.stop()
        self._ctx.pool.drop(owner)
        for ident in [i for i, size in self._sizes.items() if size is None]:
            del self._sizes[ident]
            self.table.show_size(ident, self._sizes)
        self._show_side()
        self._changed()

    def _show_size(self, profile: Profile) -> None:
        self.table.show_size(profile.ident, self._sizes)
        self._show_count()
        self._show_side()

    def _show_so_far(self) -> None:
        """Each row being counted, with its bytes up to now; the status bar adds them up."""
        for ident, size in self._sizes.items():
            if size is None and self._so_far.get(ident):
                self.table.show_size(ident, self._sizes, self._so_far[ident])
        self.status_changed.emit()

    def _sizes_counted(self) -> None:
        self._counting = None
        self._ticker.stop()
        self._changed()
        if self._uncounted:
            self._ctx.message(
                _("{host}: sizes counted; {n} couldn't be read.").format(
                    host=self.target.name, n=self._uncounted
                )
            )
        else:
            self._ctx.message(_("{host}: sizes counted.").format(host=self.target.name))

    # ---- deleting ----

    def delete_ticked(self, parent: QWidget) -> None:
        """Asks, listing the ticked rows, then deletes them one at a time."""
        ticked = self.ticked()
        if self.scan is None or not ticked or self.deleting:
            return
        self.stop_sizes()
        dialog = DeleteDialog(parent, self.target.name, ticked, self._counted())
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self.delete(ticked)

    def delete(self, profiles: list[Profile]) -> None:
        """No question: the Delete window asked already."""
        self.deleting, self._cancelled = True, False
        self._run, self._queue = list(profiles), list(profiles)
        self._results, self._done, self._freed = {}, {}, 0
        self._began = self._now()
        self._run_shown = True
        self.table.lock(True)
        for profile in profiles:
            self._set_result(profile, Result.QUEUED)
        self._show_rows()  # the run's rows show whatever the filters
        self._delete_next()

    def cancel_rest(self) -> None:
        """The profile being deleted finishes; the ones still queued don't start."""
        if not self.deleting or self._cancelled:
            return
        self._cancelled = True
        left, self._queue = self._queue, []
        for profile in left:
            self._set_result(profile, None)
        self._run = [p for p in self._run if p not in left]
        self._show_side()
        self._changed()

    def _run_counts(self) -> tuple[int, int]:
        """(ended, total) of the run under way."""
        ended = sum(result in rows.ENDED for result in self._results.values())
        return ended, len(self._run)

    def _delete_next(self) -> None:
        scanned = self.scan
        if not self._queue or scanned is None:
            self._delete_over()
            return
        profile, account = self._queue.pop(0), self._account
        self._set_result(profile, Result.DELETING)
        log_file = self._ctx.log_file()
        self._changed()

        def done(ended: Deleted) -> None:
            size = self._sizes.get(profile.ident)
            self._done[profile.ident] = ended
            if ended.outcome is Outcome.DELETED and size:
                self._freed += size
            self._set_result(profile, rows.result_of(ended))
            self._delete_next()

        work.start(
            lambda: user_profiles.delete(scanned, profile, account, log_file=log_file),
            done,
            lambda error: done(Deleted(profile, Outcome.FAILED, Why.ERROR, str(error))),
            self._jobs,
        )

    def _delete_over(self) -> None:
        self.deleting = False
        self._ended = self._now()
        self.table.lock(False)
        self._show_side()
        self._changed()

    def _set_result(self, profile: Profile, result: Result | None) -> None:
        if result is None:
            self._results.pop(profile.ident, None)
        else:
            self._results[profile.ident] = result
        self.table.show_result(profile.ident, result)
        self._show_count()  # a row that ended lost its tick
        self._show_side()

    def open_log(self) -> None:
        """The file every delete is written to, in whatever opens text files."""
        log_file = self._ctx.log_file()
        if log_file.exists():
            os.startfile(log_file)  # noqa: S606 (Windows' own "open", as a double-click)
        else:
            self._ctx.message(_("The history has nothing yet."))

    def close_progress(self) -> None:
        """A run that's over leaves the card: what's ticked shows again."""
        if self.deleting or not self._run_shown:
            return
        self._run_shown = False
        self._show_side()

    # ---- helpers ----

    def _changed(self) -> None:
        self.box.show_title(self.title(), self.about())
        self.changed.emit()
        self.status_changed.emit()

    def _muted(self) -> QColor:
        return self.box.palette().color(QPalette.ColorRole.PlaceholderText)

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone()
