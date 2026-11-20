"""Profile cleanup's first opening: a real warning naming what it deletes, Continue greyed until
"I understand…" is ticked (a tick is read, a countdown waited out), Cancel the default."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui import help_links, spacing
from capypanel.ui.dialogs import run_modal
from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes import engine as themes

UNDERSTOOD_KEY = "warning_understood"  # in the tool's settings, once ticked and continued


class FirstUseWarning(QDialog):
    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Profile cleanup"))
        sign = QLabel()
        amber = themes.status_color("attention")
        sign.setPixmap(tabler_icon("alert-triangle", QColor(amber), 36).pixmap(36, 36))
        heading = QLabel(_("This tool deletes user profiles"))
        font = heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        heading.setFont(font)  # a warning, not a section: the sign beside it is the colour
        words = QLabel(
            _(
                "On the PCs you pick, it deletes Windows user profiles: each person's folder "
                "under C:\\Users, with every file in it, and the profile's entry in the "
                "registry. A deleted profile can't be brought back."
            )
        )
        words.setWordWrap(True)
        self.understood = QCheckBox(_("I understand it deletes user profiles on the PCs I pick"))
        self.go_on = QPushButton(_("&Continue"))
        self.go_on.setObjectName("risky")
        self.go_on.setEnabled(False)
        self.cancel = QPushButton(_("Cancel"))
        self.cancel.setDefault(True)
        self.understood.toggled.connect(self.go_on.setEnabled)
        self.go_on.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        top = QHBoxLayout()
        top.setSpacing(spacing.WINDOW)
        top.addWidget(sign, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(spacing.CONTROLS)
        text.addWidget(heading)
        text.addWidget(words)
        text.addSpacing(spacing.CONTROLS)
        text.addWidget(self.understood)
        top.addLayout(text, 1)
        self.help_button = help_links.HelpButton("profiles/user-profiles/")
        buttons = QHBoxLayout()
        buttons.addWidget(self.help_button)
        buttons.addStretch(1)
        buttons.addWidget(self.go_on)
        buttons.addWidget(self.cancel)
        column = QVBoxLayout(self)
        column.setContentsMargins(*(spacing.WINDOW,) * 4)
        column.setSpacing(spacing.WINDOW)
        column.addLayout(top)
        column.addLayout(buttons)
        self.resize(520, self.sizeHint().height())


def ask(parent: QWidget | None) -> bool:
    """The warning; True once its tick is ticked and Continue pressed."""
    return run_modal(FirstUseWarning(parent)) == QDialog.DialogCode.Accepted
