"""One host's tab in the User profiles tool: its box (the name, the filters, the profiles table),
and on the right a profile's details, or the progress while it deletes. Each tab keeps its own
scan, sizes and delete run, so several hosts can be read, counted and cleaned at once."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialog, QStackedWidget, QVBoxLayout, QWidget

from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import user_profiles
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.user_profiles import Deleted, Kind, Outcome, Profile, Scan, Why
from capypanel.ui.checks import clock_text
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.runner import HostTarget, Job
from capypanel.ui.icons import STATUS_COLORS
from capypanel.ui.profiles_tool import rows, work
from capypanel.ui.profiles_tool.panels import (
    DeleteDialog,
    FilterRow,
    HintCard,
    ProfileDetails,
    ProfilesTable,
    ProgressPanel,
    Shown,
    TabBox,
)
from capypanel.ui.profiles_tool.rows import Result


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


BLUE = rows.IN_USE_BLUE


@dataclass
class Context:
    """What a host's tab needs from the tool."""

    pool: work.Pool
    log_file: Callable[[], Path]  # the history's file
    message: Callable[[str], None]  # a note in the status bar
    another_account: Callable[[HostTarget, BaseException, Callable[[], None]], None] | None


class HostPage(QObject):
    """A host's tab: `box` goes in the middle, `side` on the right; the tool shows both."""

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
        self.details = ProfileDetails()
        self.progress = ProgressPanel()
        self.side = QStackedWidget()
        self.side.addWidget(self.details)
        self.side.addWidget(self.progress)
        self.filters.changed.connect(self._show_rows)
        self.table.picked.connect(self._show_details)
        self.table.ticked_changed.connect(self._ticks_changed)
        self.progress.cancel_requested.connect(self.cancel_rest)
        self.progress.log_requested.connect(self.open_log)
        self.progress.closed.connect(self.close_progress)
        self._show_waiting()

    # ---- what the tab and the Hosts tab show ----

    def mark(self) -> Mark:
        """The tab's mark: deleting first, then counting, then the scan's own stage."""
        if self.deleting:
            ended, total = self._run_counts()
            return Mark(
                "trash",
                STATUS_COLORS["attention"],
                _("Deleting profile {n} of {total}. The tab can't close until it ends; use "
                  "Cancel the rest.").format(n=ended + 1, total=total),
                _("deleting {n} of {total}").format(n=ended + 1, total=total),
                busy=True,
            )  # fmt: skip
        if self._counting is not None:
            done = self._count_total - self._count_left
            return Mark(
                "report-analytics",
                BLUE,
                _("Calculating sizes: {n} of {total}").format(n=done, total=self._count_total),
                _("calculating sizes"),
                busy=True,
            )
        if self.stage is Stage.QUEUED:
            return Mark("clock", STATUS_COLORS["offline"], _("Waiting to scan"), _("queued"),
                        busy=False)  # fmt: skip
        if self.stage is Stage.SCANNING:
            return Mark("refresh", BLUE, _("Scanning the profiles…"), _("scanning…"), busy=True)
        if self.stage is Stage.FAILED:
            return Mark("circle-x", STATUS_COLORS["stopped"], self._failure_tip(),
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
                return Mark("circle-check", STATUS_COLORS["online"], tip, freed or tip,
                            busy=False)  # fmt: skip
            counts = rows.counts_text(results) or _("nothing deleted")
            tip = _("{counts}. See the history.").format(counts=counts)
            return Mark("alert-triangle", STATUS_COLORS["attention"], tip, freed or counts,
                        busy=False)  # fmt: skip
        when = clock_text(self.read_at) if self.read_at else ""
        return Mark("", "", _("Scanned at {time}").format(time=when), when, busy=False)

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
            if run != self._scan_run:
                return
            self.stage, self.error, self.read_at = Stage.FAILED, error, self._now()
            self._show_failure()

        self._ctx.pool.read(self, read, done, failed, began)

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
        self.details.show_hint(_("The profiles show once the host is scanned."))
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
        color = QColor(STATUS_COLORS["stopped"])
        self._show_card(HintCard("circle-x", color, said.title, said.lines, buttons))
        self.details.show_hint(_("The profiles show once the host is scanned."))
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
        self.progress.retranslate()
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
        ticked = self.ticked()
        words = short = ""
        if ticked:
            words = short = ngettext("{n} ticked", "{n} ticked", len(ticked)).format(n=len(ticked))
            if size := self.ticked_size():
                words += " · " + rows.size_text(size)
        shown = rows.shown_text(len(self.table.shown()), len(self.scan.profiles))
        self.filters.show_count(shown, words, short, str(len(ticked)))

    def title(self) -> str:
        """The box's first line: what this list is, so it's never taken for a list of hosts."""
        return _("User profiles on {host}").format(host=self.target.name)

    def _ticks_changed(self) -> None:
        self._show_count()
        self.status_changed.emit()
        self.changed.emit()

    def _show_details(self) -> None:
        profile = self.table.selected() if self.scan is not None else None
        if profile is None or self.scan is None:
            self.details.show_hint(
                "" if self.scan is not None else _("The profiles show once the host is scanned.")
            )
            return
        size = self._sizes.get(profile.ident)
        counting = profile.ident in self._sizes and size is None
        result, done = self._results.get(profile.ident), self._done.get(profile.ident)
        self.details.show_item(Shown(profile, self.scan.root, size, counting, result, done), 1)

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

            self._ctx.pool.count(owner, count, ended, lambda _error, e=ended: e(None))
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
        self._show_details()
        self._changed()

    def _show_size(self, profile: Profile) -> None:
        self.table.show_size(profile.ident, self._sizes)
        self._show_count()
        picked = self.table.selected()
        if picked is not None and picked.ident == profile.ident:
            self._show_details()

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
        self.table.lock(True)
        self.progress.start(len(profiles))
        for profile in profiles:
            self._set_result(profile, Result.QUEUED)
        self._show_rows()  # the run's rows show whatever the filters
        self.side.setCurrentWidget(self.progress)
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
        if left:
            self._log(_("cancelled: {n} not started").format(n=len(left)))
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
        ended, total = self._run_counts()
        self.progress.show_progress(
            _("{host} · profile {n} of {total} · since {time}").format(
                host=self.target.name, n=ended + 1, total=total, time=clock_text(self._began)
            ),
            ended,
        )
        self._log(f"{profile.user}: " + _("deleting…"))
        log_file = self._ctx.log_file()
        self._changed()

        def done(ended: Deleted) -> None:
            size = self._sizes.get(profile.ident)
            self._done[profile.ident] = ended
            if ended.outcome is Outcome.DELETED and size:
                self._freed += size
            self._log(f"{profile.user}: " + rows.ended_text(ended, size))
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
        self.table.lock(False)
        results = [self._results[p.ident] for p in self._run if p.ident in self._results]
        counts = rows.counts_text(results) or _("nothing deleted")
        times = _("{start} to {end}").format(
            start=clock_text(self._began), end=clock_text(self._now())
        )
        freed = _("{size} freed").format(size=rows.size_text(self._freed)) if self._freed else ""
        self.progress.finish(
            f"{self.target.name} · {counts}", f"{freed} · {times}" if freed else times
        )
        self._show_details()
        self._changed()

    def _set_result(self, profile: Profile, result: Result | None) -> None:
        if result is None:
            self._results.pop(profile.ident, None)
        else:
            self._results[profile.ident] = result
        self.table.show_result(profile.ident, result)
        picked = self.table.selected()
        if picked is not None and picked.ident == profile.ident:
            self._show_details()

    def _log(self, text: str) -> None:
        """A line in the progress panel's history: the time, then what happened."""
        self.progress.add_line(f"{self._now():%H:%M}  {text}")

    def open_log(self) -> None:
        """The file every delete is written to, in whatever opens text files."""
        log_file = self._ctx.log_file()
        if log_file.exists():
            os.startfile(log_file)  # noqa: S606 (Windows' own "open", as a double-click)
        else:
            self._ctx.message(_("The history has nothing yet."))

    def close_progress(self) -> None:
        """Details again."""
        if self.deleting or self.side.currentWidget() is self.details:
            return
        self.side.setCurrentWidget(self.details)
        self._show_details()

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
