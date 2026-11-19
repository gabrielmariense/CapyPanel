"""Updates in the app: a look at GitHub at every start by default (Settings › CapyPanel ›
General › Updates: at every start, once a day, once a week or off, one choice for the whole
PC) and from Help › Check for updates; one window with the notes (in the app's language),
Install and restart, Later and Skip this version, where the download's progress shows too,
opened on its own when a look finds a newer release, and an "Update 0.26.1" button at the
right of the menu bar for later; after the restart, a window saying it's installed or why
not. The download and the swap are core/updates.py's."""

import logging
import re
import shutil
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLocale, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from capypanel import __version__
from capypanel.core import files, i18n, updates
from capypanel.core.i18n import _, ngettext
from capypanel.core.ssh import launch as ssh_launch
from capypanel.core.updates import Release, UpdateError
from capypanel.ui import branding
from capypanel.ui.dialogs import run_modal

log = logging.getLogger(__name__)

PREFS_KEY = "updates"  # this person's: {"last": ISO time, "skip": "0.26.1", "installed": …}
FIRST_LOOK = 1_000  # ms after the start: the window is drawn first; GitHub answers in a thread
TICK = 3_600_000  # ms between looks at whether it's time again


def packaged() -> bool:
    """Run as CapyPanel.exe: only that copy updates itself; a source checkout uses git."""
    return bool(getattr(sys, "frozen", False))


class Updater(QObject):
    """Whether there's a newer release, kept as `offer`. Looks on its own only in the exe, as
    often as this PC's choice says (`folder` holds it): by default soon after every start, then
    once a day while CapyPanel stays open."""

    changed = Signal()  # `offer` changed: the menu bar's button follows
    found = Signal()  # a look of its own found a newer release: the window opens for it
    looked = Signal(object, str)  # after a look: the release or None, and why it failed or ""
    _answer = Signal(object, str)  # from the thread that asked GitHub

    def __init__(
        self, prefs: dict[str, Any], save: Callable[[], None], folder: Path, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._prefs, self._save, self._folder = prefs, save, folder
        self.offer: Release | None = None
        self.looking = False
        self._answer.connect(self._answered)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK)
        self._timer.timeout.connect(lambda: self._maybe_look(started=False))
        if packaged():
            self._timer.start()
            QTimer.singleShot(FIRST_LOOK, self, lambda: self._maybe_look(started=True))

    def _own(self) -> dict[str, Any]:
        kept = self._prefs.get(PREFS_KEY)
        if not isinstance(kept, dict):
            kept = self._prefs[PREFS_KEY] = {}
        return kept

    def how_often(self) -> str:
        """updates.AT_START, DAILY, WEEKLY or OFF, as chosen for this PC."""
        return updates.check_of(self._folder)

    def set_how_often(self, how: str) -> None:
        """For everyone on this PC. Raises OSError where this person can't write it."""
        updates.set_check(self._folder, how)
        log.info("Update checks for this PC: %s", how)

    def can_set(self) -> bool:
        """Whether Windows lets this person change the choice for everyone on this PC."""
        return files.can_create_files(self._folder)

    def skipped(self) -> str:
        skip = self._own().get("skip")
        return skip if isinstance(skip, str) else ""

    def skip(self, version: str) -> None:
        """Skip this version: no button for it, until a newer one or a look from Help."""
        self._own()["skip"] = version
        self._save()
        self.offer = None
        self.changed.emit()

    def remember_install(self, release: Release) -> None:
        """Kept through the restart, so the new version can say what it brought."""
        self._own()["installed"] = {"version": release.version, "notes": release.notes,
                                    "page": release.page_url}  # fmt: skip
        self._save()

    def take_installed(self) -> dict[str, str]:
        """What remember_install kept, once: {} when nothing was."""
        kept = self._own().pop("installed", None)
        if kept is not None:
            self._save()
        if not isinstance(kept, dict):
            return {}
        return {k: v for k, v in kept.items() if isinstance(k, str) and isinstance(v, str)}

    def _due(self, wait: timedelta) -> bool:
        last = self._own().get("last")
        try:
            when = datetime.fromisoformat(last) if isinstance(last, str) else None
        except ValueError:
            when = None
        return when is None or datetime.now(UTC) - when >= wait

    def _maybe_look(self, *, started: bool) -> None:
        how = self.how_often()
        if how == updates.OFF:
            return
        if (started and how == updates.AT_START) or self._due(updates.WAIT[how]):
            self.look(asked=False)

    def look(self, *, asked: bool) -> None:
        """Ask GitHub, on a thread of its own; `looked` brings the answer. `asked`: from Help or
        About, so a skipped version is offered again."""
        if self.looking:
            return
        self.looking = True
        self._asked = asked

        def ask() -> None:
            try:
                self._answer.emit(updates.latest(), "")
            except UpdateError as e:
                self._answer.emit(None, str(e))

        threading.Thread(target=ask, name="update-check", daemon=True).start()

    def _answered(self, release: Release | None, error: str) -> None:
        self.looking = False
        if error:
            log.info("Update check: %s", error)
        else:
            self._own()["last"] = datetime.now(UTC).isoformat(timespec="seconds")
            self._save()
        newer = release is not None and updates.is_newer(release, __version__)
        offered = newer and (self._asked or release.version != self.skipped())  # type: ignore[union-attr]
        before = self.offer
        self.offer = release if offered else None
        if newer:
            log.info("Update check: %s is out", release.version)  # type: ignore[union-attr]
        if self.offer != before:
            self.changed.emit()
        self.looked.emit(release if newer else None, error)
        if self.offer is not None and not self._asked:
            self.found.emit()


class _Job(QObject):
    """Download, check and unpack, on a thread of its own; `step` brings each step's words
    and the bytes so far, `ended` the unpacked folder or why it failed."""

    step = Signal(str, int, int)
    ended = Signal(str, str)  # the new version's folder, or ""; why it failed, or ""

    def __init__(self, release: Release, app_dir: Path) -> None:
        super().__init__()
        self._release, self._place = release, updates.places(app_dir)
        self.cancel = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="update-download", daemon=True).start()

    def _run(self) -> None:
        release, place = self._release, self._place
        try:
            shutil.rmtree(place.staging, ignore_errors=True)
            place.staging.mkdir(parents=True)
            archive = place.staging / release.zip_name
            digest_file = place.staging / f"{release.zip_name}.sha256"
            self.step.emit(_("Downloading…"), 0, release.zip_size)
            updates.download(release.sha_url, digest_file, cancelled=self.cancel.is_set)
            updates.download(
                release.zip_url,
                archive,
                progress=lambda done, total: self.step.emit(_("Downloading…"), done, total),
                cancelled=self.cancel.is_set,
            )
            self.step.emit(_("Checking the file…"), 0, 0)
            wanted = updates.expected_sha256(digest_file.read_text(encoding="utf-8"),
                                             release.zip_name)  # fmt: skip
            if updates.sha256_of(archive) != wanted:
                raise UpdateError(_("The download doesn't match its SHA-256: it was changed or "
                                    "cut short."))  # fmt: skip
            self.step.emit(_("Unpacking…"), 0, 0)
            new_app = updates.unpack(archive, place.staging)
            archive.unlink(missing_ok=True)
            # Its self-test now, while CapyPanel is still open: after the restart only the
            # files' swap is left, a fraction of a second.
            self.step.emit(_("Checking the new version…"), 0, 0)
            if not updates.self_test(new_app / updates.EXE):
                raise UpdateError(_("The new version didn't pass its self-test"))
            updates.mark_tested(place, release.version)
        except (UpdateError, OSError) as e:
            shutil.rmtree(place.staging, ignore_errors=True)
            self.ended.emit("", _("Cancelled.") if self.cancel.is_set() else str(e))
            return
        self.ended.emit(str(new_app), "")


NOTES_HEIGHT = 480  # the most a window grows to show release notes; longer ones scroll
WIDE, NARROW = 620, 480  # with a list of changes; just a message (nothing new, checking, failed)
BUSY_WIDTH = 256  # the bar under "Checking for updates…"
ZERO_WIDTH_SPACE = "​"  # a place a line may break, drawn as nothing
REASON_MARK = "\x00"  # where a translation puts the reason, so it can start a line
BODY = (24, 22, 24, 18)  # the body's margins: left, top, right, bottom
SHORT_BODY = (24, 36, 24, 32)  # just a message: more room above and below, so it sits centred
GAPS = {"links": 16, "busy": 16}  # above the links, above the busy bar
SHORT_GAPS = {"links": 10, "busy": 6}  # closer under a centred message (the bar: with no line)

_LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")


def changes_and_links(notes: str) -> tuple[list[str], list[tuple[str, str]]]:
    """A release's notes as the window shows them: one change per bullet (or paragraph), and
    apart, every line that is only a link (the code-signing policy), as (words, address)."""
    changes: list[str] = []
    links: list[tuple[str, str]] = []
    open_item = False  # the last line belongs to a change that may go on
    for raw in notes.splitlines():
        line = raw.strip()
        only_link = _LINK.fullmatch(line)
        if not line or line.startswith("#"):
            open_item = False
        elif only_link:
            links.append((only_link[1], only_link[2]))
            open_item = False
        elif line[:2] in ("- ", "* ", "+ "):
            changes.append(line[2:].strip())
            open_item = True
        elif open_item:
            changes[-1] += " " + line
        else:
            changes.append(line)
            open_item = True
    return changes, links


def _inline(text: str) -> str:
    """A change's words as rich text: escaped, with the notes' links, **bold** and `code`."""
    out, at = [], 0
    for found in _LINK.finditer(text):
        out.append(_marks(text[at : found.start()]))
        out.append(f'<a href="{escape(found[2])}">{_marks(found[1])}</a>')
        at = found.end()
    out.append(_marks(text[at:]))
    return "".join(out)


def _marks(text: str) -> str:
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def _link(words: str, url: str) -> str:
    return f'<a href="{escape(url)}" style="text-decoration: none">{escape(words)} ↗</a>'


class _Changes(QScrollArea):
    """The list of changes: as tall as its rows want, so the window grows to show them all,
    and willing to shrink (and scroll) once the window is at its tallest."""

    def __init__(self) -> None:
        super().__init__()
        self.width_for_rows = WIDE - 48

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        rows = self.widget()
        layout = rows.layout() if rows is not None else None
        height = layout.heightForWidth(self.width_for_rows) if layout is not None else 0
        return QSize(self.width_for_rows, max(height, 0) + 2 * self.frameWidth())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return QSize(0, 60)


class _Frame(QDialog):
    """The update windows' shared look, Windows 11's dialogs: a soft body (the app icon, a
    title, a version chip, a grey line, the changes with a ✓ each, links) over a footer band
    with the buttons. A window with only a message (nothing new, checking, couldn't check)
    has no icon or chip: the message bigger, in the middle, and a narrower window."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("CapyPanel")  # the app's name, in every language
        self._shown: list[str] = []
        body = QWidget()
        body.setObjectName("updateBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.icon = QLabel()
        self.icon.setPixmap(branding.app_icon().pixmap(32, 32))
        self.heading = QLabel()
        self.heading.setObjectName("updateTitle")
        self.heading.setWordWrap(True)
        self.chip = QLabel()
        self.chip.setObjectName("updateChip")
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(self.icon)
        head.addWidget(self.heading, 1)
        head.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.line = QLabel()
        self.line.setObjectName("updateLine")
        self.line.setWordWrap(True)
        self.line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.busy = QProgressBar()
        self.busy.setObjectName("thin")
        self.busy.setTextVisible(False)
        self.busy.setFixedSize(BUSY_WIDTH, 6)
        self.busy.setRange(0, 0)
        self._rows = QWidget()
        self._rows.setObjectName("updateRows")
        rows = self._row_list = QVBoxLayout(self._rows)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(14)
        self.changes = _Changes()
        self.changes.setObjectName("updateChanges")
        self.changes.setFrameShape(QFrame.Shape.NoFrame)
        self.changes.setWidgetResizable(True)
        self.changes.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.changes.setWidget(self._rows)
        self.links = QLabel()
        self.links.setObjectName("updateLink")
        self.links.setOpenExternalLinks(True)
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(*BODY)
        self._body.setSpacing(0)
        self._body.addLayout(head)
        self._body.addSpacing(10)
        self._body.addWidget(self.line)
        self._gap_changes = self._spacer(18)
        self._body.addWidget(self.changes, 1)
        self._gap_links = self._spacer(GAPS["links"])
        self._body.addWidget(self.links)
        self._gap_busy = self._spacer(GAPS["busy"])
        self._body.addWidget(self.busy, 0, Qt.AlignmentFlag.AlignHCenter)
        self._body.addStretch(0)  # the slack, when there are no changes to take it
        footer = QWidget()
        footer.setObjectName("updateFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.buttons = QHBoxLayout(footer)
        self.buttons.setContentsMargins(24, 16, 24, 16)
        self.buttons.setSpacing(8)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(body, 1)
        layout.addWidget(footer)

    def _spacer(self, height: int) -> QWidget:
        gap = QWidget()
        gap.setFixedHeight(height)
        self._body.addWidget(gap)
        return gap

    # ---- what it shows ----

    def full(self, heading: str, chip: str, line: str, notes: str, page: str) -> None:
        """The window with its icon, chip, the notes' changes and links: `page` is the release
        on GitHub, "" when there's none to link."""
        changes, links = changes_and_links(notes)
        if page.startswith("https://"):
            links.insert(0, (_("Notes on GitHub"), page))
        self._set_rows(changes)
        self._shape(full=True, heading=heading, line=line, links=links)
        self.chip.setText(chip)
        self.chip.setVisible(bool(chip))
        self._gap_changes.setVisible(bool(changes))
        self.changes.setVisible(bool(changes))

    def short(self, message: str, line: str = "", link: tuple[str, str] | None = None,
              *, busy: bool = False) -> None:  # fmt: skip
        """Just a message, bigger and in the middle, with a grey line, a link or a busy bar
        under it."""
        self._set_rows([])
        self._shape(full=False, heading=message, line=line, links=[link] if link else [])
        self.chip.setVisible(False)
        self._gap_changes.setVisible(False)
        self.changes.setVisible(False)
        self._gap_busy.setFixedHeight(SHORT_GAPS["busy"] if not line else GAPS["busy"])
        self._gap_busy.setVisible(busy)
        self.busy.setVisible(busy)

    def _shape(self, *, full: bool, heading: str, line: str, links: list[tuple[str, str]]) -> None:
        self.icon.setVisible(full)
        self._body.setContentsMargins(*(BODY if full else SHORT_BODY))
        self._gap_links.setFixedHeight((GAPS if full else SHORT_GAPS)["links"])
        self.changes.width_for_rows = (WIDE if full else NARROW) - 48  # less the body's margins
        centre = Qt.AlignmentFlag.AlignHCenter if not full else Qt.AlignmentFlag.AlignLeft
        for label in (self.heading, self.line, self.links):
            label.setAlignment(centre | Qt.AlignmentFlag.AlignVCenter)
        self.heading.setText(heading)
        self.line.setText(line)
        self.line.setVisible(bool(line))
        self.links.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join(_link(w, u) for w, u in links))
        self.links.setVisible(bool(links))
        self._gap_links.setVisible(bool(links))
        self._gap_busy.setVisible(False)
        self.busy.setVisible(False)
        self.resize(WIDE if full else NARROW, self.height())
        QTimer.singleShot(0, self, self._fit)

    def _set_rows(self, changes: list[str]) -> None:
        self._shown = list(changes)
        rows = self._row_list
        while rows.count():
            item = rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for change in changes:
            row = QWidget()
            mark = QLabel("✓")
            mark.setObjectName("updateMark")
            mark.setFixedWidth(14)
            mark.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            words = QLabel(f'<p style="line-height: 145%; margin: 0">{_inline(change)}</p>')
            words.setObjectName("updateChange")
            words.setWordWrap(True)
            words.setOpenExternalLinks(True)
            words.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            line.addWidget(mark)
            line.addWidget(words, 1)
            rows.addWidget(row)
        rows.addStretch(1)

    def changes_text(self) -> list[str]:
        """The changes shown, as the notes word them."""
        return list(self._shown)

    def _fit(self) -> None:
        """Tall enough for the changes it shows, up to NOTES_HEIGHT, past which they scroll;
        without changes, just its few lines."""
        layout = self.layout()
        if layout is None:
            return
        layout.invalidate()
        height = layout.heightForWidth(self.width()) if layout.hasHeightForWidth() else -1
        height = max(height, self.minimumSizeHint().height())
        self.resize(self.width(), min(height, NOTES_HEIGHT))


class UpdateWindow(_Frame):
    """One window for an update: what's new, then the download's progress in its footer."""

    def __init__(
        self,
        parent: QWidget,
        updater: Updater,
        *,
        app_dir: Path,
        working: Callable[[], bool],
        quit_for_update: Callable[[Callable[[], None]], bool],
    ) -> None:
        super().__init__(parent)
        self._updater, self._app_dir = updater, app_dir
        self._working, self._quit_for_update = working, quit_for_update
        self._release: Release | None = None
        self._job: _Job | None = None
        self.reason = QLabel()  # why this copy can't install it: under the links, in grey
        self.reason.setObjectName("updateLine")
        self.reason.setWordWrap(True)
        self.reason.setContentsMargins(0, 12, 0, 0)
        self._body.insertWidget(self._body.indexOf(self._gap_busy), self.reason)
        self.progress = QProgressBar()
        self.progress.setObjectName("thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.status = QLabel()
        self.status.setObjectName("updateStatus")
        self.status.setWordWrap(True)
        self.install = QPushButton(_("&Install and restart"))
        self.later = QPushButton(_("&Later"))
        self.skip = QPushButton(_("&Skip this version"))
        self.install.clicked.connect(self._install)
        self.later.clicked.connect(self._later)
        self.skip.clicked.connect(self._skip)
        self._going = QWidget()  # the download's words over its bar, in Skip's place
        going = QVBoxLayout(self._going)
        going.setContentsMargins(0, 0, 0, 0)
        going.setSpacing(6)
        going.addWidget(self.status)
        going.addWidget(self.progress)
        self.buttons.addWidget(self.skip)
        self.buttons.addWidget(self._going, 1)
        self.buttons.addStretch(0)
        self.buttons.addWidget(self.later)
        self.buttons.addWidget(self.install)
        self._waiting = QTimer(self)
        self._waiting.setInterval(1000)
        self._waiting.timeout.connect(self._try_restart)
        updater.looked.connect(self._looked)
        self.resize(WIDE, NOTES_HEIGHT)
        if updater.offer is not None:
            self._show(updater.offer)
        else:
            self._checking()

    # ---- what it shows ----

    def _closing_only(self) -> None:
        """Nothing new, checking, couldn't check: Close at the right, nothing else."""
        self.reason.setVisible(False)
        self.skip.setVisible(False)
        self._going.setVisible(False)
        self.install.setVisible(False)
        self.later.setText(_("Close"))
        self._default(self.later)

    def _default(self, button: QPushButton) -> None:
        for each in (self.install, self.later):
            each.setDefault(each is button)
            each.setAutoDefault(each is button)
        self.skip.setAutoDefault(False)

    def _checking(self) -> None:
        self.short(_("Checking for updates…"), busy=True)
        self._closing_only()
        self._updater.look(asked=True)

    def _looked(self, release: Release | None, error: str) -> None:
        if self._release is not None:
            return  # already showing one
        if release is not None:
            self._show(release)
        elif error:
            self.short(_("Couldn't check for updates."), error,
                       (_("Releases on GitHub"), updates.RELEASES_URL))  # fmt: skip
            self._closing_only()
        else:
            self.short(_("You already have the newest version."),
                       _("CapyPanel {version}").format(version=__version__))  # fmt: skip
            self._closing_only()

    def _show(self, release: Release) -> None:
        self._release = release
        self.full(_("Update available"), f"{__version__} → {release.version}",
                  _("Your settings, lists and saved logins stay as they are."),
                  notes_here(release.notes), release.page_url)  # fmt: skip
        why = self._cannot_install()
        self.reason.setText(breakable(why))  # a long folder wraps instead of widening it
        self.reason.setVisible(bool(why))
        self.skip.setVisible(True)
        self.skip.setEnabled(True)
        self._going.setVisible(False)
        self.install.setVisible(not why)
        self.install.setEnabled(True)
        self.later.setText(_("&Later"))
        self._default(self.later if why else self.install)

    def _cannot_install(self) -> str:
        if not packaged():
            return _("This copy runs from source: update it with git, or download the zip from "
                     "the release page.")  # fmt: skip
        reason = updates.cannot_install(self._app_dir)
        if reason:
            text = _("{reason}, so the update can't be installed from here. Open Notes on "
                     "GitHub, download the zip and unpack it in place of this copy.")  # fmt: skip
            return text.format(reason=reason)
        return ""

    def _footer_says(self, words: str, *, bar: bool) -> None:
        """The download's words (and its bar) in the footer's left, where Skip was."""
        self.skip.setVisible(False)
        self._going.setVisible(True)
        self.progress.setVisible(bar)
        self.status.setText(words)

    # ---- buttons ----

    def _install(self) -> None:
        release = self._release
        if release is None:
            return
        if open_ssh := self._ssh_windows_open():
            self._say(open_ssh)
            return
        self.install.setEnabled(False)
        self.later.setText(_("Cancel"))
        self._default(self.later)
        self._footer_says(_("Downloading…"), bar=True)
        self.progress.setRange(0, 0)
        job = self._job = _Job(release, self._app_dir)
        job.step.connect(self._step)
        job.ended.connect(self._unpacked)
        log.info("Update: downloading %s", release.version)
        job.start()

    def _step(self, words: str, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            locale = QLocale()
            megabytes = _("{done} of {total} MB").format(
                done=locale.toString(done / 1e6, "f", 1), total=locale.toString(total / 1e6, "f", 1)
            )
            self.status.setText(f"{words} {megabytes}")
        else:
            self.progress.setRange(0, 0)
            self.status.setText(words)

    def _unpacked(self, new_app: str, error: str) -> None:
        self._job = None
        if error:
            self._stays_open(error)
            log.info("Update: %s", error)
            return
        self._try_restart()

    def _stays_open(self, why: str) -> None:
        """It didn't go ahead: why, in the footer, and Install again."""
        self.install.setEnabled(True)
        self.later.setText(_("&Later"))
        self._default(self.install)
        self._footer_says(why, bar=False)

    def _try_restart(self) -> None:
        """Once nothing is at work (a Refresh), CapyPanel closes and the new version's own exe
        swaps the folders and starts it."""
        release = self._release
        if release is None:
            return
        if open_ssh := self._ssh_windows_open():  # one opened while it downloaded
            self._waiting.stop()
            self._say(open_ssh)
            self._stays_open(open_ssh)
            return
        if self._working():
            self._footer_says(_("Waiting for CapyPanel to finish what it's doing…"), bar=False)
            self._waiting.start()
            return
        self._waiting.stop()
        self._footer_says(_("CapyPanel closes now and opens again by itself in a few "
                            "seconds."), bar=False)  # fmt: skip

        def start_helper() -> None:
            args = updates.helper_args(self._app_dir, updates.own_pid(), __version__,
                                       release.version)  # fmt: skip
            log.info("Update: handing over to %s", args[0])
            updates.start(Path(args[0]), *args[1:])  # its splash: "Updating to …"

        self._updater.remember_install(release)
        if not self._quit_for_update(start_helper):
            self._updater.take_installed()
            self._stays_open(_("Not installed: CapyPanel stays open. Install again when "
                               "you're ready."))  # fmt: skip

    def _ssh_windows_open(self) -> str:
        """Separate SSH windows run from CapyPanel's folder and keep its files in use, so the
        swap couldn't replace them: how many are open, in words; "" when none is."""
        n = ssh_launch.open_windows()
        if not n:
            return ""
        return ngettext(
            "{n} SSH connection is still open in a separate window. Close it, then install the "
            "update.",
            "{n} SSH connections are still open in separate windows. Close them, then install "
            "the update.",
            n,
        ).format(n=n)

    def _say(self, text: str) -> None:
        """OK is its only button: installing anyway isn't a choice, the swap would roll back."""
        box = QMessageBox(
            QMessageBox.Icon.Information, "CapyPanel", text, QMessageBox.StandardButton.Ok, self
        )
        run_modal(box)

    def _later(self) -> None:
        if self._job is not None:
            self._job.cancel.set()
            return
        self._waiting.stop()
        self.reject()

    def _skip(self) -> None:
        if self._release is not None:
            self._updater.skip(self._release.version)
        self.reject()

    def done(self, result: int) -> None:
        if self._job is not None:
            self._job.cancel.set()
        self._waiting.stop()
        super().done(result)


def notes_here(notes: str) -> str:
    """A release's notes in the language CapyPanel is shown in, when they have that part."""
    return updates.notes_in(notes, i18n.LANGUAGES.get(i18n.language(), ""))


# ---- after a restart ----


class RestartWindow(_Frame):
    """After the helper started CapyPanel again: the new version is in, with its changes, or
    why it didn't go in."""

    def __init__(
        self, parent: QWidget, kind: str, version: str, why: str, installed: dict[str, str]
    ) -> None:
        super().__init__(parent)
        close = self.close_button = QPushButton(_("Close"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        self.buttons.addStretch(1)
        self.buttons.addWidget(close)
        self.resize(WIDE, NOTES_HEIGHT)
        if kind == "updated":
            kept = installed.get("version") == __version__
            self.full(_("Update installed"), f"{version} → {__version__}",
                      _("Your settings, lists and saved logins are as they were."),
                      notes_here(installed.get("notes", "")) if kept else "",
                      installed.get("page", "") if kept else "")  # fmt: skip
        else:
            # The reason starts its own line: two short sentences, never one word left alone.
            line = _("You still have CapyPanel {current}. {why}.").format(
                current=__version__, why=REASON_MARK
            )
            before, _mark, after = line.partition(REASON_MARK)
            line = f"{before.rstrip()}\n{sentence(why)}{after}" if _mark else line
            self.short(_("The update to {new} wasn't installed.").format(new=version), line,
                       (_("Releases on GitHub"), updates.RELEASES_URL))  # fmt: skip


def after_restart(argv: list[str]) -> tuple[str, str, str] | None:
    """What the helper said when it started CapyPanel again: ("updated", old version, ""),
    ("failed", new version, why), or None for a plain start."""
    if len(argv) >= 3 and argv[1] == updates.UPDATED_FLAG:
        return "updated", argv[2], ""
    if len(argv) >= 4 and argv[1] == updates.FAILED_FLAG:
        return "failed", argv[2], argv[3]
    return None


def restart_text(kind: str, version: str, why: str) -> str:
    if kind == "updated":
        return _("Updated from {old} to {new}.").format(old=version, new=__version__)
    return _("The update to {new} wasn't installed. You still have CapyPanel {current}. "
             "{why}.").format(new=version, current=__version__, why=sentence(why))  # fmt: skip


def breakable(text: str) -> str:
    """`text` with a place to break the line after each backslash of a folder: a label wraps
    only at spaces, so a long path would otherwise widen the window or run past its edge."""
    return text.replace("\\", "\\" + ZERO_WIDTH_SPACE)


def sentence(why: str) -> str:
    """Why an update failed, as a sentence of its own: a capital first, and no closing period,
    which the text around it adds (a Windows error can bring its own)."""
    why = why.strip().rstrip(".")
    return why[:1].upper() + why[1:]


def button_text(release: Release) -> str:
    return _("Update {version}").format(version=release.version)
