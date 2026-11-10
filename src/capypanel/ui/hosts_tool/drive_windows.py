"""The windows of the Users commands for drives and caches: Mapped drives (the drives saved for
each person signed in, and their session's live state after Check their session), Map a drive…
and Clear caches…. The Commands window shows Mapped drives on its right side with the same rows
(drive_rows)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.bulk import write_csv
from capypanel.core.i18n import N_, _, ngettext
from capypanel.core.remote import drives
from capypanel.core.remote.drives import App, Checked, Drive, Person
from capypanel.ui import checks as check_texts
from capypanel.ui.hosts_tool.command_windows import WIDE, Question, ReadList, escape
from capypanel.ui.icons import STATUS_COLORS
from capypanel.ui.notes import hint

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.runner import HostTarget, Runner


@dataclass(frozen=True)
class DriveRow:
    person: str
    letter: str
    path: str
    state: str = ""  # after Check their session
    problem: bool = False  # not connected, or the check failed


def drive_header() -> list[str]:
    return [_("Person"), _("Drive"), _("Path"), _("State")]


def drive_rows(people: Sequence[Person], checked: Checked | None) -> list[DriveRow]:
    """Each person's saved drives by letter, then, once their session was checked, the drives
    mapped only for this session; with a check, every row says whether it's connected."""
    rows: list[DriveRow] = []
    for person in people:
        key = person.account.casefold()
        asked = checked is not None and key in checked.live
        live = {d.letter: d for d in checked.live[key]} if asked and checked else None
        failed = checked is not None and key in checked.failed
        if not person.drives and not live:
            nothing = _("No drives") if live is not None else _("No saved drives")
            state = (_("Couldn't check"), True) if failed else ("", False)
            rows.append(DriveRow(person.user, "", nothing, *state))
        for drive in person.drives:
            now = live.get(drive.letter) if live is not None else None
            rows.append(DriveRow(person.user, drive.letter, drive.path,
                                 *_state(now, live, failed)))  # fmt: skip
        for drive in (live or {}).values():
            if drive.letter not in {d.letter for d in person.drives}:
                text = (_("Connected, this session only") if drives.connected(drive)
                        else _("Not connected, this session only"))  # fmt: skip
                rows.append(DriveRow(person.user, drive.letter, drive.path, text,
                                     not drives.connected(drive)))  # fmt: skip
    return rows


def _state(now: Drive | None, live: dict[str, Drive] | None, failed: bool) -> tuple[str, bool]:
    if failed:
        return _("Couldn't check"), True
    if live is None:
        return "", False
    if now is None:
        return _("Not mapped now"), True
    return (_("Connected"), False) if drives.connected(now) else (_("Not connected"), True)


def checked_text(people: Sequence[Person], checked: Checked) -> str:
    """Under the table after a check: why a person's session couldn't be asked."""
    from capypanel.ui.hosts_tool.runner import reason_text

    lines = []
    for person in people:
        error = checked.failed.get(person.account.casefold())
        if error is not None:
            lines.append(_("Couldn't check {user}'s session: {reason}").format(
                user=person.user, reason=reason_text(error)))  # fmt: skip
    return "\n".join(lines)


SAVED_NOTE = N_(
    "These are the drives that come back at every sign-in. Check their session shows a drive "
    "mapped only for now, and whether each one is connected; it runs a short hidden task as "
    "each person."
)


def check_link(checking: bool) -> str:
    if checking:
        return escape(_("Checking their session…"))
    return f'<a href="check">{escape(_("Check their session"))}</a>'


def row_text(row: DriveRow) -> list[str]:
    return [row.person, row.letter, row.path, row.state]


class DrivesDialog(ReadList):
    """Mapped drives: the drives saved for each person signed in, Check their session for the
    live state, Map a drive…, Copy list."""

    READ = "Mapped drives"

    def __init__(self, parent: QWidget | None, runner: "Runner", target: "HostTarget",
                 map_drive: Callable[[Callable[[], None]], None]) -> None:  # fmt: skip
        """`map_drive(then)`: Map a drive…, calling `then` once it's mapped."""
        super().__init__(parent, runner, target)
        self._map_drive = map_drive
        self._people: list[Person] = []
        self._checked: Checked | None = None
        self.setWindowTitle(_("Mapped drives on {host}").format(host=target.name))
        self.table.setHeaderLabels(drive_header())
        self.note = hint(_(SAVED_NOTE))
        self.check = QLabel(check_link(False))
        self.check.setTextFormat(Qt.TextFormat.RichText)
        self.check.linkActivated.connect(lambda _href: self.check_sessions())
        self.failures = hint("")
        self.map_button = QPushButton(_("&Map a drive…"))
        self.copy_button = QPushButton(_("&Copy list"))
        for button in (self.map_button, self.copy_button):
            button.setAutoDefault(False)
        self.map_button.clicked.connect(lambda: self._map_drive(self.read))
        self.copy_button.clicked.connect(self._copy)
        actions = QHBoxLayout()
        for button in (self.map_button, self.copy_button, self.read_button):
            actions.addWidget(button)
        actions.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.note)
        layout.addWidget(self.check)
        layout.addWidget(self.failures)
        layout.addLayout(actions)
        layout.addLayout(bottom)
        self.resize(760, 420)
        self._update()
        self.read()

    def read(self) -> None:
        self._checked = None
        super().read()

    def work(self, account: Any) -> list[Person]:
        return drives.saved_drives(self.target.address, account)

    def show_rows(self, found: list[Person]) -> None:
        self._people = list(found)
        self._fill()
        assert self.read_at is not None
        when = check_texts.clock_text(self.read_at)
        if not found:
            self.summary.setText(_("No one is signed in to {host} (read at {when}).").format(
                host=self.target.name, when=when))  # fmt: skip
        else:
            self.summary.setText(ngettext(
                "Drives saved for the person signed in to {host}, read at {when}.",
                "Drives saved for the {n} people signed in to {host}, read at {when}.",
                len(found)).format(n=len(found), host=self.target.name, when=when))  # fmt: skip
        self._update()

    def _fill(self) -> None:
        self.table.clear()
        for row in drive_rows(self._people, self._checked):
            item = QTreeWidgetItem(row_text(row))
            if row.problem:
                item.setForeground(3, QColor(STATUS_COLORS["attention"]))
            self.table.addTopLevelItem(item)
        self.table.setColumnHidden(3, self._checked is None)  # State: only after a check
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)

    def check_sessions(self) -> None:
        if not self._people:
            return
        self.check.setText(check_link(True))
        people = list(self._people)

        def work(account: Any) -> Checked:
            return drives.check_sessions(self.runner.scripts, self.target.address, people, account)

        def done(checked: Checked) -> None:
            if not self._alive():
                return
            self._checked = checked
            self.check.setText(check_link(False))
            self.failures.setText(checked_text(self._people, checked))
            self._fill()

        def failed(error: BaseException) -> None:
            from capypanel.ui.hosts_tool.runner import reason_text

            if not self._alive():
                return
            self.check.setText(check_link(False))
            self.failures.setText(_("Couldn't check their session: {reason}").format(
                reason=reason_text(error)))  # fmt: skip

        self.runner.call(work, done, failed, self.target)

    def _update(self) -> None:
        self.copy_button.setEnabled(bool(self._people))
        self.check.setVisible(bool(self._people))

    def _copy(self) -> None:
        rows = [row_text(r) for r in drive_rows(self._people, self._checked)]
        QGuiApplication.clipboard().setText(write_csv(drive_header(), rows, "\t"))


class MapDriveDialog(QDialog):
    """A letter and a \\\\server\\share for the person signed in."""

    def __init__(self, parent: QWidget | None, host: str, user: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Map a drive"))
        intro = QLabel(_("Maps a network drive for {user} on {host}. It shows in their File "
                         "Explorer at once and comes back at every sign-in.").format(
            user=user, host=host))  # fmt: skip
        intro.setWordWrap(True)
        self.letter = QComboBox()
        self.letter.addItems(list(drives.LETTERS))
        self.letter.setCurrentText("S:")
        self.letter.setMaximumWidth(90)  # two characters; full width looked like a path field
        self.path = QLineEdit()
        self.path.setPlaceholderText("\\\\FS01\\Shared")
        self.path.setMinimumWidth(300)
        form = QFormLayout()
        form.addRow(_("&Letter:"), self.letter)
        form.addRow(_("&Folder:"), self.path)
        note = hint(
            _(
                "A shared folder as \\\\server\\share. It runs as {user}, so the drive "
                "is theirs; if the letter is taken, Windows says so."
            ).format(user=user)
        )
        self.map_button = QPushButton(_("&Map"))
        self.map_button.setDefault(True)
        cancel = QPushButton(_("Cancel"))
        self.map_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.map_button)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.path.textChanged.connect(self._update)
        self._update()
        self.resize(WIDE + 40, self.sizeHint().height())
        self.path.setFocus()

    def picked(self) -> tuple[str, str]:
        return self.letter.currentText(), self.path.text().strip().rstrip("\\")

    def _update(self) -> None:
        self.map_button.setEnabled(drives.valid_share(self.path.text()))


class ClearCachesDialog(Question):
    """The question before Clear caches…, with a tick per app."""

    def __init__(self, parent: QWidget | None, host: str, user: str) -> None:
        text = _(
            "Only cache folders go: passwords, cookies, history and bookmarks stay. An app "
            "that's open for {user} is left alone. Teams' whole cache goes, as Microsoft's "
            "own steps clear it, so Teams may ask them to sign in again."
        ).format(user=user)
        super().__init__(parent, _("Clear caches"),
                         _("Clear caches for {user} on {host}?").format(user=user, host=host),
                         escape(text), _("&Clear caches"))  # fmt: skip
        self.ticks: dict[App, QCheckBox] = {}
        for app in App:
            tick = QCheckBox(drives.APP_NAMES[app])
            tick.setChecked(True)
            tick.toggled.connect(self._update)
            self.ticks[app] = tick
            self.body.addWidget(tick)

    def apps(self) -> tuple[App, ...]:
        return tuple(app for app, tick in self.ticks.items() if tick.isChecked())

    def _update(self) -> None:
        self.action.setEnabled(bool(self.apps()))


def cleared_text(user: str, host: str, found: Sequence[drives.Cleared]) -> str:
    """What Clear caches did, as rich text."""
    from capypanel.ui.hosts_tool.runner import bold, size_text

    done = [c for c in found if c.state is drives.CacheState.CLEARED]
    open_ = [drives.APP_NAMES[c.app] for c in found if c.state is drives.CacheState.OPEN]
    who, where = bold(user), escape(host)
    if done:
        names = ", ".join(drives.APP_NAMES[c.app] for c in done)
        text = _("Cleared {size} of caches for {user} on {host}: {apps}.").format(
            size=size_text(sum(c.freed for c in done)), user=who, host=where, apps=names
        )
        left = sum(c.left for c in done)
        if left:
            text += " " + ngettext("{n} file in use stayed.", "{n} files in use stayed.",
                                   left).format(n=left)  # fmt: skip
    elif not open_:
        text = _("Nothing to clear for {user} on {host}: those apps keep no cache there.").format(
            user=who, host=where)  # fmt: skip
    else:
        text = _("Nothing cleared for {user} on {host}.").format(user=who, host=where)
    if open_:
        text += " " + ngettext("{apps} was open, so its cache stayed.",
                               "{apps} were open, so their caches stayed.",
                               len(open_)).format(apps=", ".join(open_))  # fmt: skip
    return text
