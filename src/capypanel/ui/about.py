"""Settings > About (Help > About CapyPanel opens it), the third-party licenses, and the Help
menu's links: the website and reporting a problem."""

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
    QScrollArea,
    QToolTip,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel import _COMMIT, BUILD, __version__
from capypanel.core import i18n, settings
from capypanel.core.i18n import _
from capypanel.ui import branding
from capypanel.ui.list_workspace.details import CopyValue
from capypanel.ui.settings.pages import FoldersSection, Page, Section
from capypanel.ui.tables import add_action, fit_rows, grid_table, row_menu, with_buttons
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


class AboutPage(Page):
    """Settings > About: the app (icon, name, version, what it is, its notices and links),
    Credits, Licenses as the one table design, then where CapyPanel keeps its files (with
    `paths`). Help > About opens it."""

    def __init__(
        self, log_dir: Path, *, portable: bool, paths: settings.Paths | None = None
    ) -> None:
        super().__init__(_("About"))
        self._portable = portable
        self.reader = LicenseReader(self)  # one, reused
        self.body.addWidget(self._app_section(log_dir))
        self.body.addWidget(self._credits_section())
        self.licenses_section = self._licenses_section()
        self.body.addWidget(self.licenses_section)
        self.folders = FoldersSection(paths) if paths is not None else None
        if self.folders is not None:
            self.body.addWidget(self.folders)
        self.body.addStretch(1)

    def _app_section(self, log_dir: Path) -> Section:
        """The mascot on the left; name and version, what CapyPanel is, its notices and links
        on the right; the tools for a problem report under them."""
        icon = QLabel()
        icon.setPixmap(branding.app_icon().pixmap(32, 32))
        name = QLabel("CapyPanel")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.4)
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
        text = QVBoxLayout()
        text.setSpacing(10)
        text.addLayout(top)
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
        self.report_button = QPushButton(_("&Report a problem"))
        self.logs_button = QPushButton(_("Open &log folder"))
        self.logs_button.setToolTip(_("The app's logs, to attach to a problem report"))
        self.report_button.clicked.connect(lambda: open_url(report_url(self._portable)))
        self.logs_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
        )
        buttons = QHBoxLayout()
        buttons.addWidget(self.report_button)
        buttons.addWidget(self.logs_button)
        buttons.addStretch(1)
        text.addLayout(buttons)
        picture = QLabel()
        picture.setPixmap(branding.mascot(96, self.devicePixelRatioF()))
        picture.setAlignment(Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        section = Section("CapyPanel")
        section.content.addLayout(row)
        return section

    def _credits_section(self) -> Section:
        rows = [(_("Created by:"), CREATOR)]
        if MASCOT_BY:
            rows.append((_("Mascot:"), MASCOT_BY))
        rows.append((_("Icons:"), f"{_link(TABLER_URL, 'Tabler Icons')} · © Paweł Kuna"))
        section = Section(_("Credits"))
        section.content.addLayout(_rows(rows, self._open_link))
        return section

    def _licenses_section(self) -> Section:
        """The software CapyPanel is built with, in the one table design: Read license opens
        the copy shipped with CapyPanel in a window here, so it reads offline."""
        self.licenses = grid_table([_("Software"), _("Version"), _("License"), _("Notice")])
        for part in COMPONENTS:
            item = QTreeWidgetItem([part.name, part.version, part.license, part.notice])
            item.setData(0, Qt.ItemDataRole.UserRole, part.file)
            item.setToolTip(3, part.notice)
            self.licenses.addTopLevelItem(item)
        first = self.licenses.topLevelItem(0)
        if first is not None:
            self.licenses.setCurrentItem(first)
        fit_rows(self.licenses)
        self.read_button = QPushButton(_("Read license"))
        self.folder_button = QPushButton(_("Open folder"))
        self.folder_button.setToolTip(_("The licenses folder, shipped with CapyPanel"))
        self.read_button.clicked.connect(self.read_picked)
        self.folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(LICENSES_DIR)))
        )
        self.licenses.itemDoubleClicked.connect(lambda *_a: self.read_picked())
        row_menu(self.licenses, lambda menu: add_action(menu, _("Read license"), self.read_picked))
        section = Section(_("Licenses"))
        section.content.addWidget(_text(_("CapyPanel is built with the following software:")))
        section.content.addWidget(
            with_buttons(self.licenses, [self.read_button, self.folder_button])
        )
        return section

    def read_picked(self) -> None:
        item = self.licenses.currentItem()
        if item is not None:
            file = item.data(0, Qt.ItemDataRole.UserRole)
            self.reader.show_license(next(c for c in COMPONENTS if c.file == file))

    def _open_link(self, url: str) -> None:
        if url == "#licenses":  # "see Licenses": scroll down to it
            area = self.parentWidget()
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parentWidget()
            if area is not None:
                area.ensureWidgetVisible(self.licenses_section)
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
