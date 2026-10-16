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
from PySide6.QtGui import QCursor, QDesktopServices, QFontDatabase, QShowEvent, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
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
    """The icon, name and version on top; About, Credits and Licenses as tabs below. Plain text
    in the tabs, in one font and colour, as in most apps' About windows."""

    def __init__(self, parent: QWidget | None, log_dir: Path, *, portable: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("About CapyPanel"))
        self._portable = portable
        icon = QLabel()
        icon.setPixmap(branding.app_icon().pixmap(40, 40))
        name = QLabel("CapyPanel")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        name.setFont(font)
        # The version beside the name, in its font; a click copies it with its commit.
        self.version = CopyValue(BUILD, __version__)
        self.version.setFont(font)
        self.version.setWordWrap(False)
        self.version.copied.connect(lambda _text: QToolTip.showText(QCursor.pos(), _("Copied")))
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(icon)
        top.addWidget(name)
        top.addSpacing(-8)  # the version's hover padding is gap enough
        top.addWidget(self.version)
        top.addStretch(1)

        self.reader = LicenseReader(self)  # one, reused: windows here are never deleted
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(buttons)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.setFixedWidth(660)

    def _about_tab(self) -> QWidget:
        """The mascot on the left; what CapyPanel is, its notices and links on the right."""
        picture = QLabel()
        picture.setPixmap(branding.mascot(112, self.devicePixelRatioF()))
        picture.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(12)
        text.addWidget(_text(_("Every computer you look after, in one window.")))
        # The GPL's "appropriate legal notices": the ©, no warranty, and the license a click away.
        text.addWidget(_text(f"© {YEAR} {CREATOR}"))
        text.addWidget(
            _text(
                _("Free software under the GPL-3.0, with no warranty: see {licenses}.").format(
                    licenses=_link("#licenses", _("Licenses"))
                ),
                self._open_link,
            )
        )
        rows = [
            (_("Documentation:"), _link(docs_url(), DOCS_URL.removeprefix("https://").rstrip("/"))),
            (_("Source code:"), _link(source_url(), REPO_URL.removeprefix("https://"))),
        ]
        build = [f"commit {_COMMIT}"] if _COMMIT else []  # only what applies
        if self._portable:
            build.append(_("portable mode"))
        if build:
            rows.append((_("Build:"), " · ".join(build)))
        text.addLayout(_rows(rows, self._open_link))
        text.addStretch(1)
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)
        layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text, 1)
        return page

    def _credits_tab(self) -> QWidget:
        rows = [(_("Created by:"), CREATOR)]
        if MASCOT_BY:
            rows.append((_("Mascot:"), MASCOT_BY))
        rows.append((_("Icons:"), f"{_link(TABLER_URL, 'Tabler Icons')} · © Paweł Kuna"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(_rows(rows, self._open_link))
        layout.addStretch(1)
        return page

    def _licenses_tab(self) -> QWidget:
        """Like qBittorrent's "Software used": each part on one line, its license a link that
        opens the copy shipped with CapyPanel in a window here, so it reads offline."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(_text(_("CapyPanel is built with the following software:")))
        layout.addWidget(_divider())
        self.licenses = QWidget()
        grid = QGridLayout(self.licenses)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(8)
        for row, part in enumerate(COMPONENTS):
            cells = (part.name, part.version, _link(f"license:{part.file}", part.license),
                     part.notice)  # fmt: skip
            for column, cell in enumerate(cells):
                grid.addWidget(_text(cell, self._open_link, wrap=False), row, column)
        grid.setColumnStretch(3, 1)
        layout.addWidget(self.licenses)
        layout.addWidget(_divider())
        layout.addWidget(
            _text(
                _("Click a license to read it. They all ship with CapyPanel, in its {folder}.")
                .format(folder=_link(QUrl.fromLocalFile(str(LICENSES_DIR)).toString(),
                                     _("licenses folder"))),
                self._open_link,
            )
        )  # fmt: skip
        layout.addStretch(1)
        return page

    def _open_link(self, url: str) -> None:
        if url == "#licenses":
            self.tabs.setCurrentIndex(2)
        elif url.startswith("license:"):
            part = next(c for c in COMPONENTS if c.file == url.removeprefix("license:"))
            self.reader.show_license(part)
        elif url.startswith("file:"):
            QDesktopServices.openUrl(QUrl(url))  # the licenses folder
        else:
            open_url(url)


# ---- Licenses ----


class LicenseReader(QDialog):
    """A license's text, read inside the app rather than in Notepad."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        # Fixed width: the texts line up their lists and tables with spaces.
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        close = QPushButton(_("Close"))
        close.setAutoDefault(False)
        close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(buttons)
        self.resize(620, 640)

    def show_license(self, part: "Component") -> None:
        self.setWindowTitle(f"{part.name} · {part.license}")
        self.text.setPlainText((LICENSES_DIR / part.file).read_text(encoding="utf-8"))
        self.text.moveCursor(QTextCursor.MoveOperation.Start)
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    notice: str  # its copyright line
    license: str
    file: str  # the license text, shipped in capypanel/licenses


TABLER_URL = "https://tabler.io/icons"
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
        "Qt",
        qVersion(),
        "© The Qt Company Ltd. and other contributors",
        "LGPL-3.0",
        "lgpl-3.0.txt",
    ),
    Component(
        "Qt for Python",
        pyside_version,
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


def _text(text: str, on_link: Callable[[str], None] | None = None, *, wrap: bool = True) -> QLabel:
    """Plain text in the window's font and colour; links open through `on_link`."""
    label = QLabel(text)
    label.setWordWrap(wrap)
    if on_link is not None:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.linkActivated.connect(on_link)
    return label


def _rows(rows: list[tuple[str, str]], on_link: Callable[[str], None]) -> QGridLayout:
    """Label: value rows, labels and values each lined up on the left."""
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(8)
    for row, (label, value) in enumerate(rows):
        title = _text(label, wrap=False)
        grid.addWidget(title, row, 0)
        grid.addWidget(_text(value, on_link), row, 1)
    grid.setColumnStretch(1, 1)
    return grid


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def _link(url: str, text: str) -> str:
    return f'<a href="{url}">{text}</a>'
