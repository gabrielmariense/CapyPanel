"""Help > About CapyPanel, the third-party licenses, and the Help menu's links: the website and
reporting a problem."""

import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, QUrl, qVersion
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
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
    """The mascot, name and version on top; About, Credits and Licenses as tabs below."""

    def __init__(self, parent: QWidget | None, log_dir: Path, *, portable: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("About CapyPanel"))
        picture = QLabel()
        picture.setPixmap(branding.mascot(104, self.devicePixelRatioF()))
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self._about_tab(), _("About"))
        self.tabs.addTab(self._credits_tab(), _("Credits"))
        self.tabs.addTab(self._licenses_tab(), _("Licenses"))

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
        built.setVisible(bool(build))  # an installed copy has nothing to add down here
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(built)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 12)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)
        layout.addLayout(foot)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.setFixedWidth(600)

    def _about_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(
            _card(
                [
                    (_("Created by"), f"{CREATOR} · © {YEAR}"),
                    (
                        _("Documentation"),
                        _link(docs_url(), DOCS_URL.removeprefix("https://").rstrip("/")),
                    ),
                    (_("Source code"), _link(source_url(), REPO_URL.removeprefix("https://"))),
                ],
                self._open_link,
            )
        )
        # The GPL's "appropriate legal notices": the © above, no warranty, and the license a
        # click away.
        notice = QLabel(
            _("Free software under the GPL-3.0, with no warranty: see {licenses}.").format(
                licenses=_link("#licenses", _("Licenses"))
            )
        )
        notice.setWordWrap(True)
        notice.linkActivated.connect(self._open_link)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page

    def _credits_tab(self) -> QWidget:
        rows = [(_("Created by"), CREATOR)]
        if MASCOT_BY:
            rows.append((_("Mascot"), MASCOT_BY))
        rows.append((_("Built with"), "Python · Qt for Python · Tabler Icons"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_card(rows, self._open_link))
        layout.addStretch(1)
        return page

    def _licenses_tab(self) -> QWidget:
        """Like qBittorrent's "Software used": each part, its version and a link to its license.
        The links open the texts that ship with CapyPanel, so they work offline."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(_("CapyPanel and what it's built with:")))
        rows = []
        for part in COMPONENTS:
            name = f"{part.name}<br><small>{part.notice}</small>"
            license_link = _link(QUrl.fromLocalFile(str(LICENSES_DIR / part.file)).toString(),
                                 part.license)  # fmt: skip
            rows.append((name, f"{part.version} · {license_link}"))
        self.licenses = _card(rows, self._open_link, rich_titles=True)
        layout.addWidget(self.licenses)
        folder = QLabel(
            _link(QUrl.fromLocalFile(str(LICENSES_DIR)).toString(), _("Open the licenses folder"))
        )
        folder.linkActivated.connect(self._open_link)
        layout.addWidget(folder)
        layout.addStretch(1)
        return page

    def _open_link(self, url: str) -> None:
        if url == "#licenses":
            self.tabs.setCurrentIndex(2)
        elif url.startswith("file:"):
            QDesktopServices.openUrl(QUrl(url))  # the copy shipped with the app
        else:
            open_url(url)


# ---- Licenses ----


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    notice: str  # its copyright line
    license: str
    file: str  # the license text, shipped in capypanel/licenses


# CapyPanel, then what ships inside it. LGPL-3.0 builds on the GPL-3.0: both texts ship.
COMPONENTS = (
    Component(
        "CapyPanel",
        __version__,
        f"© {YEAR} Gabriel Tobias Mariense",
        "GPL-3.0",
        "gpl-3.0.txt",
    ),
    Component(
        "Qt · Qt for Python",
        f"{qVersion()} · {pyside_version}",
        "© The Qt Company Ltd. and other contributors",
        "LGPL-3.0",
        "lgpl-3.0.txt",
    ),
    Component(
        "Python",
        platform.python_version(),
        "© 2001-2024 Python Software Foundation",
        "PSF License",
        "python.txt",
    ),
    Component("Tabler Icons", "", "© 2020-2026 Paweł Kuna", "MIT", "tabler-icons.txt"),
)


def _card(
    rows: list[tuple[str, str]], on_link: Callable[[str], None], *, rich_titles: bool = False
) -> QFrame:
    """Label and value rows in a card, links in the values."""
    card = QFrame()
    card.setObjectName("card")
    grid = QGridLayout(card)
    grid.setContentsMargins(14, 12, 14, 12)
    grid.setHorizontalSpacing(18)
    grid.setVerticalSpacing(9)
    for row, (label, value) in enumerate(rows):
        title = QLabel(label) if rich_titles else hint(label)
        title.setWordWrap(False)
        text = QLabel(value.removeprefix(" · "))
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        text.linkActivated.connect(on_link)
        grid.addWidget(title, row, 0)
        grid.addWidget(text, row, 1)
    grid.setColumnStretch(1, 1)
    return card


def _link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'
