"""Updates in the app: a look at GitHub at every start by default (Settings › CapyPanel ›
General › Updates: at every start, once a day, once a week or off, one choice for the whole
PC) and from Help › Check for updates; an "Update 0.26.1" button at the right of the menu bar
when there's one; and one window with the notes, Install and restart, Later and Skip this
version, where the download's progress shows too. The download and the swap are
core/updates.py's."""

import logging
import shutil
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QLocale, QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from capypanel import __version__
from capypanel.core import files, updates
from capypanel.core.i18n import _
from capypanel.core.updates import Release, UpdateError
from capypanel.ui import spacing

log = logging.getLogger(__name__)

PREFS_KEY = "updates"  # this person's: {"last": ISO time, "skip": "0.26.1"}
FIRST_LOOK = 15_000  # ms after the start: the window is drawn and lists are open first
TICK = 3_600_000  # ms between looks at whether it's time again


def packaged() -> bool:
    """Run as CapyPanel.exe: only that copy updates itself; a source checkout uses git."""
    return bool(getattr(sys, "frozen", False))


class Updater(QObject):
    """Whether there's a newer release, kept as `offer`. Looks on its own only in the exe, as
    often as this PC's choice says (`folder` holds it): by default soon after every start, then
    once a day while CapyPanel stays open."""

    changed = Signal()  # `offer` changed: the menu bar's button follows
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
        except (UpdateError, OSError) as e:
            shutil.rmtree(place.staging, ignore_errors=True)
            self.ended.emit("", _("Cancelled.") if self.cancel.is_set() else str(e))
            return
        self.ended.emit(str(new_app), "")


NOTES_HEIGHT = 480  # the window's height with release notes to read


class UpdateWindow(QDialog):
    """One window for an update: what's new, then the download's progress in the same place."""

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
        self.setWindowTitle(_("Update CapyPanel"))
        self._updater, self._app_dir = updater, app_dir
        self._working, self._quit_for_update = working, quit_for_update
        self._release: Release | None = None
        self._job: _Job | None = None
        self.heading = QLabel()
        self.heading.setObjectName("sectionTitle")
        self.heading.setWordWrap(True)
        self.line = QLabel()
        self.line.setWordWrap(True)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(160)
        self.page = QLabel()
        self.page.setOpenExternalLinks(True)
        self.progress = QProgressBar()
        self.progress.setObjectName("thin")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.install = QPushButton(_("&Install and restart"))
        self.later = QPushButton(_("&Later"))
        self.skip = QPushButton(_("&Skip this version"))
        self.install.setDefault(True)
        self.install.clicked.connect(self._install)
        self.later.clicked.connect(self._later)
        self.skip.clicked.connect(self._skip)
        buttons = QHBoxLayout()
        buttons.addWidget(self.skip)
        buttons.addStretch(1)
        buttons.addWidget(self.later)
        buttons.addWidget(self.install)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(spacing.WINDOW,) * 4)
        layout.setSpacing(spacing.CONTROLS)
        layout.addWidget(self.heading)
        layout.addWidget(self.line)
        layout.addWidget(self.notes, 1)
        layout.addWidget(self.page)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addStretch(0)  # the slack, when there are no notes to take it
        layout.addLayout(buttons)
        self._waiting = QTimer(self)
        self._waiting.setInterval(1000)
        self._waiting.timeout.connect(self._try_restart)
        updater.looked.connect(self._looked)
        self.resize(620, NOTES_HEIGHT)
        if updater.offer is not None:
            self._show(updater.offer)
        else:
            self._checking()

    # ---- what it shows ----

    def _checking(self) -> None:
        self.heading.setText(_("Checking for updates…"))
        self.line.setText(_("CapyPanel {version} asks GitHub for its newest release.").format(
            version=__version__))  # fmt: skip
        self._show_parts(notes=False, progress=True, install=False, skip=False)
        self.progress.setRange(0, 0)  # busy
        self.later.setText(_("Close"))
        self._updater.look(asked=True)

    def _looked(self, release: Release | None, error: str) -> None:
        if self._release is not None:
            return  # already showing one
        if release is not None:
            self._show(release)
        elif error:
            self._failed(_("Couldn't check for updates."), error)
        else:
            self.heading.setText(_("CapyPanel is up to date"))
            self.line.setText(_("{version} is the newest release.").format(version=__version__))
            self._show_parts(notes=False, progress=False, install=False, skip=False)
            self.later.setText(_("Close"))

    def _show(self, release: Release) -> None:
        self._release = release
        self.heading.setText(_("CapyPanel {new} is out").format(new=release.version))
        self.line.setText(_("You have {current}. Your settings, lists and saved logins stay as "
                            "they are.").format(current=__version__))  # fmt: skip
        self.notes.setMarkdown(release.notes or _("No notes for this release."))
        self.page.setText(
            f'<a href="{escape(release.page_url)}">{escape(_("The release on GitHub"))}</a>'
        )
        self.later.setText(_("&Later"))
        why = self._cannot_install()
        self._show_parts(notes=True, progress=False, install=not why, skip=True)
        self.status.setText(why)
        self.status.setVisible(bool(why))

    def _cannot_install(self) -> str:
        if not packaged():
            return _("This copy runs from source: update it with git, or download the zip from "
                     "the release page.")  # fmt: skip
        reason = updates.cannot_install(self._app_dir)
        if reason:
            text = _("CapyPanel can't install it from here ({reason}). Download the zip from "
                     "the release page and unpack it in place of this one.")  # fmt: skip
            return text.format(reason=reason)
        return ""

    def _show_parts(self, *, notes: bool, progress: bool, install: bool, skip: bool) -> None:
        self.notes.setVisible(notes)
        self.page.setVisible(notes)
        self.progress.setVisible(progress)
        self.status.setVisible(progress)
        self.install.setVisible(install)
        self.skip.setVisible(skip)
        QTimer.singleShot(0, self, lambda: self._fit(notes))

    def _fit(self, notes: bool) -> None:
        """Tall enough for the release notes; without them, just its few lines."""
        layout = self.layout()
        if notes:
            height = max(self.height(), NOTES_HEIGHT)
        else:
            height = layout.heightForWidth(self.width()) if layout is not None else -1
            height = max(height, self.minimumSizeHint().height())
        self.resize(self.width(), height)

    def _failed(self, heading: str, why: str) -> None:
        self.heading.setText(heading)
        self.line.setText(why)
        self._show_parts(notes=False, progress=False, install=False, skip=False)
        self.page.setText(f'<a href="{updates.RELEASES_URL}">{escape(_("Releases on GitHub"))}</a>')
        self.page.setVisible(True)
        self.later.setText(_("Close"))

    # ---- buttons ----

    def _install(self) -> None:
        release = self._release
        if release is None:
            return
        self.install.setEnabled(False)
        self.skip.setEnabled(False)
        self.later.setText(_("Cancel"))
        self._show_parts(notes=True, progress=True, install=True, skip=True)
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
            self.install.setEnabled(True)
            self.skip.setEnabled(True)
            self.later.setText(_("&Later"))
            self.progress.setVisible(False)
            self.status.setText(error)
            self.status.setVisible(True)
            log.info("Update: %s", error)
            return
        self._try_restart()

    def _try_restart(self) -> None:
        """Once nothing is at work (a Refresh), CapyPanel closes and the new version's own exe
        swaps the folders and starts it."""
        release = self._release
        if release is None:
            return
        if self._working():
            self.status.setText(_("Waiting for CapyPanel to finish what it's doing…"))
            self._waiting.start()
            return
        self._waiting.stop()
        self.status.setText(_("Restarting CapyPanel…"))

        def start_helper() -> None:
            args = updates.helper_args(self._app_dir, updates.own_pid(), __version__,
                                       release.version)  # fmt: skip
            log.info("Update: handing over to %s", args[0])
            updates.start(Path(args[0]), *args[1:], splash=False)

        if not self._quit_for_update(start_helper):
            self.status.setText(_("Not installed: CapyPanel stays open. Install again when "
                                  "you're ready."))  # fmt: skip
            self.install.setEnabled(True)
            self.skip.setEnabled(True)
            self.later.setText(_("&Later"))

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


# ---- after a restart ----


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
    return _("The update to {new} didn't go in, so this is still {current}: {why}").format(
        new=version, current=__version__, why=why
    )


def button_text(release: Release) -> str:
    return _("Update {version}").format(version=release.version)
