"""Help > About CapyPanel, and the Help menu's links: the website and reporting a problem."""

import platform
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capypanel import BUILD
from capypanel.core import i18n
from capypanel.core.i18n import _
from capypanel.ui import branding
from capypanel.ui.notes import hint

CREATOR = "Gabriel Tobias Mariense (GMErebos)"
REPO_URL = "https://github.com/gabrielmariense/CapyPanel"
DOCS_URL = "https://gabrielmariense.github.io/CapyPanel/"
LICENSE_URL = f"{REPO_URL}/blob/main/LICENSE"


def docs_url() -> str:
    """The website, in Portuguese when the app is."""
    return DOCS_URL + ("pt-BR/" if i18n.language() == "pt_BR" else "")


def report_url() -> str:
    """A new GitHub issue with the versions already filled in, under the space for the report."""
    body = (
        "\n\n---\n"
        f"CapyPanel {BUILD}\n"
        f"Windows {platform.version()}\n"
        f"Qt {qVersion()}, Python {platform.python_version()}\n"
    )
    return f"{REPO_URL}/issues/new?body={quote(body)}"


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None, log_dir: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("About CapyPanel"))
        picture = QLabel()
        picture.setPixmap(branding.mascot(120, self.devicePixelRatioF()))
        name = QLabel("CapyPanel")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.8)
        font.setBold(True)
        name.setFont(font)
        version = QLabel(_("Version {version}").format(version=BUILD))
        version.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        about = QLabel(_("Manage the computers on your network from one window."))
        about.setWordWrap(True)
        heading = QVBoxLayout()
        heading.addStretch(1)
        heading.addWidget(name)
        heading.addWidget(version)
        heading.addSpacing(8)
        heading.addWidget(about)
        heading.addStretch(1)
        top = QHBoxLayout()
        top.setSpacing(16)
        top.addWidget(picture)
        top.addLayout(heading, 1)

        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        rows = (
            (_("Created by"), CREATOR),
            (_("Website"), _link(docs_url(), DOCS_URL.removeprefix("https://").rstrip("/"))),
            (_("Source code"), _link(REPO_URL, REPO_URL.removeprefix("https://"))),
            (_("License"), _link(LICENSE_URL, _("GNU General Public License, version 3"))),
        )
        for row, (label, value) in enumerate(rows):
            title = hint(label)
            title.setWordWrap(False)
            text = QLabel(value)
            text.setOpenExternalLinks(True)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            grid.addWidget(title, row, 0)
            grid.addWidget(text, row, 1)
        grid.setColumnStretch(1, 1)
        credits = hint(
            _("Built with Python and Qt for Python (LGPL-3.0). Icons: Tabler Icons (MIT).")
        )

        buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.report_button = buttons.addButton(_("&Report a problem"), role.ActionRole)
        self.logs_button = buttons.addButton(_("Open &log folder"), role.ActionRole)
        self.logs_button.setToolTip(_("The app's logs, to attach to a problem report"))
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self.report_button.clicked.connect(lambda: open_url(report_url()))
        self.logs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        )
        copyright_line = hint("© 2026 Gabriel Tobias Mariense")
        copyright_line.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 14)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addWidget(card)
        layout.addWidget(credits)
        layout.addWidget(buttons)
        layout.addWidget(copyright_line)
        for button in self.findChildren(QPushButton):  # no blue button: nothing to confirm
            button.setAutoDefault(False)
            button.setDefault(False)
        self.setFixedWidth(560)


def _link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'
