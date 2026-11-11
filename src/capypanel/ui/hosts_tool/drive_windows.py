"""Mapped drives, a Users command: the drives saved for each person signed in. The Commands
window shows them on its right side with the same rows (drive_rows)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTreeWidgetItem, QVBoxLayout, QWidget

from capypanel.core.hosts.bulk import write_csv
from capypanel.core.i18n import N_, _, ngettext
from capypanel.core.remote import drives
from capypanel.core.remote.drives import Person
from capypanel.ui import checks as check_texts
from capypanel.ui.hosts_tool.command_windows import ReadList
from capypanel.ui.notes import hint

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.runner import HostTarget, Runner


@dataclass(frozen=True)
class DriveRow:
    person: str
    letter: str
    path: str


def drive_header() -> list[str]:
    return [_("Person"), _("Drive"), _("Path")]


def drive_rows(people: Sequence[Person]) -> list[DriveRow]:
    """Each person's saved drives by letter; a person with none gets one line saying so."""
    rows: list[DriveRow] = []
    for person in people:
        if not person.drives:
            rows.append(DriveRow(person.user, "", _("No saved drives")))
        for drive in person.drives:
            rows.append(DriveRow(person.user, drive.letter, drive.path))
    return rows


SAVED_NOTE = N_("These are the drives that come back at every sign-in.")


def row_text(row: DriveRow) -> list[str]:
    return [row.person, row.letter, row.path]


class DrivesDialog(ReadList):
    """Mapped drives: the drives saved for each person signed in, and Copy list."""

    READ = "Mapped drives"

    def __init__(self, parent: QWidget | None, runner: "Runner", target: "HostTarget") -> None:
        super().__init__(parent, runner, target)
        self._people: list[Person] = []
        self.setWindowTitle(_("Mapped drives on {host}").format(host=target.name))
        self.table.setHeaderLabels(drive_header())
        self.note = hint(_(SAVED_NOTE))
        self.copy_button = QPushButton(_("&Copy list"))
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self._copy)
        actions = QHBoxLayout()
        for button in (self.copy_button, self.read_button):
            actions.addWidget(button)
        actions.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.note)
        layout.addLayout(actions)
        layout.addLayout(bottom)
        self.resize(760, 420)
        self._update()
        self.read()

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
        for row in drive_rows(self._people):
            self.table.addTopLevelItem(QTreeWidgetItem(row_text(row)))
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)

    def _update(self) -> None:
        self.copy_button.setEnabled(bool(self._people))

    def _copy(self) -> None:
        rows = [row_text(r) for r in drive_rows(self._people)]
        QGuiApplication.clipboard().setText(write_csv(drive_header(), rows, "\t"))
