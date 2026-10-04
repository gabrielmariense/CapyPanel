"""The Settings pages. Each one shows the current values and reports the user's choices;
nothing here changes the app, except the host-list buttons that write a file when clicked."""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.locations import ListKind
from capypanel.core.i18n import _
from capypanel.ui.host_lists import HostListsView
from capypanel.ui.themes import engine as themes


class Page(QWidget):
    """A settings page: a title, then its content. `changed` fires when validity may change."""

    changed = Signal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        font = heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        font.setBold(True)
        heading.setFont(font)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(heading)

    def is_valid(self) -> bool:
        return True


def hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


class PathLabel(QLabel):
    """A file path cut in the middle ("C:\\Users\\…\\hosts.json") when it doesn't fit."""

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self.setObjectName("hint")
        self.setMinimumWidth(80)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._full = ""
        if path is not None:
            self.set_path(path)

    def set_path(self, path: Path) -> None:
        self._full = str(path)
        self.setToolTip(self._full)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(self.width(), self.minimumWidth())
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width))


def _open_folder(folder: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


# ---- General ----


class GeneralPage(Page):
    def __init__(
        self,
        paths: settings.Paths,
        *,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        added: list[Path],
        language: str,
    ) -> None:
        super().__init__(_("General"))
        # Each language is named in its own language, so anyone can find theirs.
        self.language = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(self.language.findData(language), 0))
        language_label = QLabel(_("&Language:"))
        language_label.setBuddy(self.language)
        language_row = QHBoxLayout()
        language_row.addWidget(language_label)
        language_row.addWidget(self.language)
        language_row.addStretch(1)
        start = QGroupBox(_("Startup"))
        self.start_list = QComboBox()
        self.start_list.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.start_list.setMinimumContentsLength(24)
        self.start_list.addItem(_("The last used list"), locations.START_LAST)
        self.start_list.addItem(_("The default list"), locations.START_DEFAULT)
        self.start_list.addItem(_("My personal list"), locations.START_PERSONAL)
        others = [
            p
            for p in added
            if locations.list_kind(p, default=default_list, personal=personal_list)
            is ListKind.SHARED
        ]
        if (
            isinstance(start_list, str)
            and start_list
            not in (locations.START_LAST, locations.START_DEFAULT, locations.START_PERSONAL)
            and not any(locations.same_path(Path(start_list), p) for p in others)
        ):
            others.insert(0, Path(start_list))
        for path in others:
            self.start_list.addItem(str(path), str(path))
            self.start_list.setItemData(
                self.start_list.count() - 1, str(path), Qt.ItemDataRole.ToolTipRole
            )
        index = self.start_list.findData(start_list)
        self.start_list.setCurrentIndex(max(index, 0))
        label = QLabel(_("&Open on startup:"))
        label.setBuddy(self.start_list)
        row = QHBoxLayout()
        row.addWidget(label)
        row.addWidget(self.start_list, 1)
        start_layout = QVBoxLayout(start)
        start_layout.addLayout(row)
        start_layout.addWidget(
            hint(
                _(
                    "If that list can't be opened, CapyPanel tries the default list. If that "
                    "also fails, it opens your personal list."
                )
            )
        )

        files = QGroupBox(_("Where CapyPanel keeps its files"))
        grid = QGridLayout(files)
        grid.setColumnStretch(1, 1)
        folders = (
            (_("Shared files"), paths.root),
            (_("Your files"), paths.user_dir),
            (_("Logs"), paths.log_dir),
        )
        for row, (label, folder) in enumerate(folders):
            button = QPushButton(_("Open folder"))
            button.clicked.connect(lambda _checked=False, f=folder: _open_folder(f))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(PathLabel(folder), row, 1)
            grid.addWidget(button, row, 2)
        note = _(
            "Shared by everyone on this PC: the default list, connection profiles, the "
            "company's tool definitions and where each tool is installed. Your files are your "
            "settings and personal list; only you and administrators can open them. Each "
            "user's log is named after their account."
        )
        if paths.portable:
            note += " " + _("Portable mode: everything stays in the app's own folder.")
        grid.addWidget(hint(note), len(folders), 0, 1, 3)

        self.body.addLayout(language_row)
        self.body.addWidget(start)
        self.body.addWidget(files)
        self.body.addStretch(1)

    def start_choice(self) -> str:
        return str(self.start_list.currentData())

    def language_choice(self) -> str:
        return str(self.language.currentData() or i18n.DEFAULT_LANGUAGE)


# ---- Host lists ----


class HostListsPage(Page):
    """The same lists as File > Host lists…; the one picked here opens on Save."""

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
    ) -> None:
        super().__init__(_("Host lists"))
        self.view = HostListsView(
            default_list=default_list, personal_list=personal_list, added=added, document=document
        )
        self.body.addWidget(self.view, 1)
        self.view.changed.connect(self.changed.emit)

    @property
    def written(self) -> list[Path]:
        return self.view.written

    def chosen(self) -> Path | None:
        return self.view.selected()

    def added(self) -> list[Path]:
        return list(self.view.added)

    def is_valid(self) -> bool:
        return self.view.can_open(self.chosen())


# ---- Appearance ----


class AppearancePage(Page):
    def __init__(self, registry: themes.Registry, current_id: str) -> None:
        super().__init__(_("Appearance"))
        self._group = QButtonGroup(self)
        native = QGroupBox(_("Windows"))
        native_layout = QVBoxLayout(native)
        native_layout.addWidget(hint(_("Native Windows styling, with your accent color.")))
        custom = QGroupBox(_("CapyPanel"))
        custom_layout = QVBoxLayout(custom)
        custom_layout.addWidget(hint(_("CapyPanel's own appearance, the same on every computer.")))
        for theme in registry.all():
            button = QRadioButton(theme.title())
            button.setIcon(theme_swatch(theme))
            button.setIconSize(SWATCH.size().toSize())
            button.setProperty("theme_id", theme.id)
            button.setChecked(theme.id == current_id)
            self._group.addButton(button)
            (native_layout if theme.engine == "native" else custom_layout).addWidget(button)
        self.body.addWidget(native)
        self.body.addWidget(custom)
        self.body.addWidget(hint(_("You can also change the theme under View > Theme.")))
        self.body.addStretch(1)

    def theme_id(self) -> str:
        button = self._group.checkedButton()
        return str(button.property("theme_id")) if button else themes.DEFAULT_THEME.id

    def buttons(self) -> list[QRadioButton]:
        return [b for b in self._group.buttons() if isinstance(b, QRadioButton)]


SWATCH = QRectF(0, 0, 44, 30)
WINDOWS_BLUE = QColor("#0078d4")  # a stand-in: the real accent is only known once applied


def theme_swatch(theme: themes.Theme) -> QIcon:
    """A tiny picture of the theme: background, header bar, a pane with a selected row."""
    pixmap = QPixmap(SWATCH.size().toSize())
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if theme.scheme == "system":  # follow system: half light, half dark
        half = SWATCH.width() / 2
        _paint_scheme(painter, _swatch_colors(theme, "light"), QRectF(0, 0, half, SWATCH.height()))
        _paint_scheme(
            painter, _swatch_colors(theme, "dark"), QRectF(half, 0, half, SWATCH.height())
        )
    else:
        _paint_scheme(painter, _swatch_colors(theme, theme.scheme), SWATCH)
    painter.setPen(QColor(128, 128, 128))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(SWATCH.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
    painter.end()
    return QIcon(pixmap)


def _swatch_colors(theme: themes.Theme, scheme: str) -> dict[str, str]:
    if theme.engine == "custom":
        c = theme.colors
        return {"bg": c["bg"], "chrome": c["chrome"], "card": c["card"], "border": c["border"],
                "sel": c["sel_solid"], "text": c["text2"]}  # fmt: skip
    t = themes.NATIVE_TOKENS[scheme]
    sel = themes.selection_tint(WINDOWS_BLUE, t["card"], t["text"])
    return {"bg": t["bg"], "chrome": t["chrome"], "card": t["card"], "border": t["border"],
            "sel": sel, "text": t["text2"]}  # fmt: skip


def _paint_scheme(painter: QPainter, c: dict[str, str], area: QRectF) -> None:
    painter.save()
    painter.setClipRect(area)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(c["bg"]))
    painter.drawRoundedRect(SWATCH, 4, 4)
    painter.setBrush(QColor(c["chrome"]))
    painter.drawRect(QRectF(0, 0, SWATCH.width(), 7))
    pane = QRectF(5, 10, SWATCH.width() - 10, SWATCH.height() - 14)
    painter.setPen(QColor(c["border"]))
    painter.setBrush(QColor(c["card"]))
    painter.drawRect(pane)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(c["sel"]))
    painter.drawRect(QRectF(pane.left() + 1, pane.top() + 3, pane.width() - 2, 5))
    painter.setBrush(QColor(c["text"]))
    painter.drawRect(QRectF(pane.left() + 4, pane.top() + 11, pane.width() * 0.5, 2))
    painter.restore()
