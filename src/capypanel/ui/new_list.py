"""New host list: its name, and who it's for. Shared lists go in the shared lists folder, for
everyone on this PC; personal ones in the user's own; "somewhere else" asks for the file."""

import re
from pathlib import Path

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.files import can_create_files
from capypanel.core.i18n import _
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts import confirm, list_file_filter
from capypanel.ui.notes import notes

SHARED, PERSONAL, ELSEWHERE = "shared", "personal", "elsewhere"
_NOT_IN_A_NAME = re.compile(r'[\\/:*?"<>|]')  # Windows won't take these in a file name


class NewListDialog(QDialog):
    def __init__(self, parent: QWidget | None, *, shared_dir: Path, user_dir: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("New host list"))
        self.shared_dir, self.user_dir = shared_dir, user_dir
        self.name = QLineEdit()
        self.name.setPlaceholderText(_("e.g. Branch offices"))
        self.shared = QRadioButton(_("Everyone on this PC (shared)"))
        self.personal = QRadioButton(_("Only me (personal)"))
        self.elsewhere = QRadioButton(_("Somewhere else, e.g. a network share…"))
        self._kinds = QButtonGroup(self)
        for button in (self.shared, self.personal, self.elsewhere):
            self._kinds.addButton(button)
        # Only people Windows lets write the shared folder can add a shared list.
        self.can_share = can_create_files(shared_dir)
        self.shared.setEnabled(self.can_share)
        (self.shared if self.can_share else self.personal).setChecked(True)
        why = notes(
            _("Shared lists are in the shared lists folder and show up for everyone; only "
              "people Windows lets write that folder can add one.")
            if not self.can_share
            else _("Shared and personal lists show up in the list dropdown by themselves.")
        )  # fmt: skip
        kinds = QVBoxLayout()
        kinds.setSpacing(4)
        for widget in (self.shared, self.personal, self.elsewhere, why):
            kinds.addWidget(widget)
        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("For:"), kinds)
        self.buttons = QDialogButtonBox()
        self.create_button = self.buttons.addButton(
            _("&Create"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._create)
        self.chosen: Path | None = None
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self._update)
        self.elsewhere.toggled.connect(self._update)
        self._update()
        self.resize(460, self.sizeHint().height())

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # The button box makes Create the default as it shows: Enter never creates by surprise.
        for button in self.buttons.buttons():
            if isinstance(button, QPushButton):
                button.setAutoDefault(False)
                button.setDefault(False)

    def kind(self) -> str:
        if self.shared.isChecked():
            return SHARED
        return PERSONAL if self.personal.isChecked() else ELSEWHERE

    def _update(self) -> None:
        """Somewhere else needs no name here: the file dialog asks for it."""
        named = bool(self.name.text().strip()) and not _NOT_IN_A_NAME.search(self.name.text())
        self.name.setEnabled(not self.elsewhere.isChecked())
        self.create_button.setEnabled(named or self.elsewhere.isChecked())

    def _create(self) -> None:
        """Create: the window closes once there's a file to make; a cancelled question keeps it
        open."""
        self.chosen = self.path()
        if self.chosen is not None:
            self.accept()

    def path(self) -> Path | None:
        """Where the new list goes; None when a question was cancelled."""
        if self.kind() == ELSEWHERE:
            name, _filter = QFileDialog.getSaveFileName(
                self, _("New host list"), str(self.user_dir), list_file_filter()
            )
            return Path(name) if name else None  # the file dialog asked before replacing
        folder = self.shared_dir if self.kind() == SHARED else self.user_dir
        path = folder / f"{self.name.text().strip()}.json"
        if path.exists() and not confirm(
            self,
            _("New host list"),
            _("A list named “{name}” is already there. Replace it with an empty one?").format(
                name=path.stem
            ),
            _("Replace"),
        ):
            return None
        return path


def ask_new_list(parent: QWidget | None, *, shared_dir: Path, user_dir: Path) -> Path | None:
    """The new list's file, or None when cancelled."""
    dialog = NewListDialog(parent, shared_dir=shared_dir, user_dir=user_dir)
    accepted = run_modal(dialog) == QDialog.DialogCode.Accepted
    return dialog.chosen if accepted else None
