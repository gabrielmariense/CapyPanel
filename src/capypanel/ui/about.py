"""Help > About CapyPanel, the third-party licenses, and the Help menu's links: the website and
reporting a problem."""

import platform
import sys
from pathlib import Path
from urllib.parse import quote

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QCursor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from capypanel import _COMMIT, BUILD, __version__
from capypanel.core import i18n
from capypanel.core.i18n import _
from capypanel.ui import branding
from capypanel.ui.main_window.details import CopyValue
from capypanel.ui.notes import hint
from capypanel.ui.themes import engine as themes

CREATOR = 'Gabriel "GMErebos" Mariense'
YEAR = 2026
MASCOT_BY = ""  # the mascot's artist, once credited here: the row shows only then
REPO_URL = "https://github.com/gabrielmariense/CapyPanel"
DOCS_URL = "https://gabrielmariense.github.io/CapyPanel/"
LICENSES_DIR = Path(__file__).resolve().parent.parent / "licenses"


def docs_url() -> str:
    """The website, in Portuguese when the app is."""
    return DOCS_URL + ("pt-BR/" if i18n.language() == "pt_BR" else "")


def source_url() -> str:
    """The repository; in Portuguese, its Portuguese README (GitHub always shows the English)."""
    return f"{REPO_URL}/blob/main/README.pt-BR.md" if i18n.language() == "pt_BR" else REPO_URL


def install_kind(portable: bool) -> str:
    """How this copy runs: "installed", "portable" or "source" (a checkout, run with uv)."""
    if portable:
        return "portable"
    return "installed" if getattr(sys, "frozen", False) else "source"


def report_url(portable: bool) -> str:
    """A new GitHub issue that starts with what helps to reproduce a problem: versions, theme,
    language and how the app runs. Never a user, domain, computer name or path."""
    body = (
        f"CapyPanel {BUILD} · {install_kind(portable)}\n"
        f"Windows {platform.version()}\n"
        f"Theme: {themes.current().id} · Language: {i18n.language()}\n"
        f"Qt {qVersion()} · Python {platform.python_version()}\n"
        "\n---\n\n"
    )
    return f"{REPO_URL}/issues/new?body={quote(body)}"


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None, log_dir: Path, *, portable: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("About CapyPanel"))
        picture = QLabel()
        picture.setPixmap(branding.mascot(112, self.devicePixelRatioF()))
        name = QLabel("CapyPanel")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.8)
        font.setBold(True)
        name.setFont(font)
        # The version beside the name, quiet; a click copies it with its commit, for a report.
        self.version = CopyValue(BUILD, __version__)
        self.version.setObjectName("hint")
        self.version.setWordWrap(False)
        self.version.copied.connect(lambda _text: QToolTip.showText(QCursor.pos(), _("Copied")))
        self.version.setContentsMargins(0, 0, 0, 3)  # on the name's baseline, not below it
        title = QHBoxLayout()
        title.setSpacing(10)
        title.addWidget(name)
        title.addWidget(self.version, 0, Qt.AlignmentFlag.AlignBottom)
        title.addStretch(1)
        about = QLabel(_("Every computer you look after, in one window."))
        about.setWordWrap(True)
        heading = QVBoxLayout()
        heading.addStretch(1)
        heading.addLayout(title)
        heading.addSpacing(4)
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
        grid.setVerticalSpacing(9)
        rows = [
            (_("Created by"), f"{CREATOR} · © {YEAR}"),
            (_("Documentation"), _link(docs_url(), DOCS_URL.removeprefix("https://").rstrip("/"))),
            (_("Source code"), _link(source_url(), REPO_URL.removeprefix("https://"))),
            # The GPL's "appropriate legal notices": the © above, no warranty, and every
            # license one click away (CapyPanel's first, then what it's built with).
            (
                _("License"),
                _link("licenses", "GPL-3.0")
                + " — "
                + _("free to use, change and share, with no warranty"),
            ),
        ]
        if MASCOT_BY:
            rows.insert(1, (_("Mascot"), MASCOT_BY))
        for row, (label, value) in enumerate(rows):
            title_label = hint(label)
            title_label.setWordWrap(False)
            text = QLabel(value)
            text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            text.linkActivated.connect(self._open_link)
            grid.addWidget(title_label, row, 0)
            grid.addWidget(text, row, 1)
        grid.setColumnStretch(1, 1)

        # Tools on the left, Close on its own at the right; no blue button: nothing to confirm.
        self.report_button = QPushButton(_("&Report a problem"))
        self.logs_button = QPushButton(_("Open &log folder"))
        self.logs_button.setToolTip(_("The app's logs, to attach to a problem report"))
        close = QPushButton(_("Close"))
        self.report_button.clicked.connect(lambda: open_url(report_url(portable)))
        self.logs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        )
        close.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.logs_button)
        buttons.addStretch(1)
        buttons.addWidget(close)

        build = [f"commit {_COMMIT}"] if _COMMIT else []  # only what applies
        if portable:
            build.append(_("portable mode"))
        built = hint(" · ".join(build))
        built.setWordWrap(False)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(built)
        rule = QFrame()  # the thin line that divides the panes
        rule.setObjectName("divider")
        rule.setFixedHeight(1)
        for part in (rule, built):
            part.setVisible(bool(build))  # an installed copy has nothing to add down here

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addWidget(card)
        layout.addLayout(buttons)
        layout.addWidget(rule)
        layout.addLayout(foot)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.setFixedWidth(560)

    def _open_link(self, url: str) -> None:
        if url == "licenses":
            LicensesDialog(self).exec()
        else:
            open_url(url)


# ---- Licenses ----

# CapyPanel, then what ships inside it, each with its copyright and the license text it comes with.
COMPONENTS = (
    (
        f"CapyPanel {__version__}",
        f"Copyright (C) {YEAR} Gabriel Tobias Mariense (GMErebos).\n"
        "CapyPanel is free software: you can share and change it under the GNU General Public "
        "License, version 3. It comes with NO WARRANTY, to the extent permitted by law.",
        ("gpl-3.0.txt",),
    ),
    (
        f"Qt {qVersion()} · Qt for Python {pyside_version}",
        "Copyright (C) The Qt Company Ltd. and other contributors.\n"
        "Used under the GNU Lesser General Public License, version 3, which builds on the GNU "
        "General Public License, version 3 (its text is under CapyPanel). You can replace these "
        "libraries with your own build of the same version.",
        ("lgpl-3.0.txt",),
    ),
    (
        f"Python {platform.python_version()}",
        "Copyright (c) 2001-2024 Python Software Foundation; All Rights Reserved.",
        ("python.txt",),
    ),
    ("Tabler Icons", "Copyright (c) 2020-2026 Paweł Kuna. MIT License.", ("tabler-icons.txt",)),
)


class LicensesDialog(QDialog):
    """CapyPanel's license, then every part it ships, each with its copyright and full text."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Licenses"))
        self.parts = QListWidget()
        for name, _notice, _files in COMPONENTS:
            self.parts.addItem(name)
        self.parts.setFixedWidth(240)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas"))
        self.parts.currentRowChanged.connect(self._show)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        for button in box.findChildren(QPushButton):
            button.setAutoDefault(False)  # no blue button, as in About
        columns = QHBoxLayout()
        columns.addWidget(self.parts)
        columns.addWidget(self.text, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(columns, 1)
        layout.addWidget(box)
        self.parts.setCurrentRow(0)
        self.resize(820, 560)

    def _show(self, row: int) -> None:
        if not 0 <= row < len(COMPONENTS):
            return
        name, notice, files = COMPONENTS[row]
        parts = [name, notice]
        for file in files:
            path = LICENSES_DIR / file
            try:
                parts.append(path.read_text(encoding="utf-8"))
            except OSError:
                missing = _("The license text is missing from this copy: {file}")
                parts.append(missing.format(file=file))
        self.text.setPlainText("\n\n".join(parts))


def _link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'
