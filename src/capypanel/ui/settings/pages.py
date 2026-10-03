"""The Settings pages. Each one shows the current values and reports the user's choices;
nothing here changes the app, except the host-list buttons that write a file when clicked."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.listfile import HostListFileError
from capypanel.core.hosts.locations import Access, ListKind
from capypanel.core.i18n import _
from capypanel.ui.hosts import list_file_filter
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
        recent: list[Path],
    ) -> None:
        super().__init__(_("General"))
        start = QGroupBox(_("Startup"))
        self.start_list = QComboBox()
        self.start_list.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.start_list.setMinimumContentsLength(24)
        self.start_list.addItem(_("The last used list"), locations.START_LAST)
        if default_list.is_file() or start_list == locations.START_DEFAULT:
            self.start_list.addItem(_("The default list"), locations.START_DEFAULT)
        self.start_list.addItem(_("My personal list"), locations.START_PERSONAL)
        others = [
            p
            for p in recent
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
        for row, (label, folder) in enumerate(
            ((_("Your files"), paths.user_dir), (_("Logs"), paths.log_dir))
        ):
            button = QPushButton(_("Open folder"))
            button.clicked.connect(lambda _checked=False, f=folder: _open_folder(f))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(PathLabel(folder), row, 1)
            grid.addWidget(button, row, 2)
        note = _(
            "Your settings, personal list and your own tool paths. Only you and administrators "
            "can open this folder. Each user's log is named after their account."
        )
        if paths.portable:
            note += " " + _("Portable mode: everything stays in the app's own folder.")
        grid.addWidget(hint(note), 2, 0, 1, 3)

        self.body.addWidget(start)
        self.body.addWidget(files)
        self.body.addStretch(1)

    def start_choice(self) -> str:
        return str(self.start_list.currentData())


# ---- Host lists ----


class HostListsPage(Page):
    """Pick the list to open: default, personal or any other file (e.g. on a network share)."""

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        recent: list[Path],
    ) -> None:
        super().__init__(_("Host lists"))
        self._default, self._personal, self._document = default_list, personal_list, document
        self.written: list[Path] = []  # files written from this page, so Save reopens them

        self.default_choice = QRadioButton(_("&Default list"))
        self.personal_choice = QRadioButton(_("&Personal list"))
        self.other_choice = QRadioButton(_("Shared or &other list"))
        self._choices = QButtonGroup(self)
        for button in (self.default_choice, self.personal_choice, self.other_choice):
            self._choices.addButton(button)
        self.default_state, self.personal_state, self.other_state = hint(), hint(), hint()
        for state in (self.default_state, self.personal_state, self.other_state):
            state.setWordWrap(False)
        self.other_path = QLineEdit()
        self.other_path.setPlaceholderText(_(r"For example \\server\share\hosts.json"))
        browse = QPushButton(_("&Browse…"))
        other_row = QHBoxLayout()
        other_row.addWidget(self.other_path, 1)
        other_row.addWidget(browse)

        box = QGroupBox(_("Open this list"))
        grid = QGridLayout(box)
        grid.setColumnStretch(0, 1)
        grid.setVerticalSpacing(4)
        rows = (
            (self.default_choice, self.default_state, PathLabel(default_list)),
            (self.personal_choice, self.personal_state, PathLabel(personal_list)),
        )
        for index, (choice, state, path_label) in enumerate(rows):
            grid.addWidget(choice, index * 3, 0)
            grid.addWidget(state, index * 3, 1, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(path_label, index * 3 + 1, 0, 1, 2)
            grid.setRowMinimumHeight(index * 3 + 2, 8)
        grid.addWidget(self.other_choice, 6, 0)
        grid.addWidget(self.other_state, 6, 1, Qt.AlignmentFlag.AlignRight)
        grid.addLayout(other_row, 7, 0, 1, 2)
        explain = _(
            "The default list is placed in the app's folder by whoever manages CapyPanel. The "
            "personal list is yours alone. Any list can be edited by people with write "
            "permission on its folder; for everyone else it opens read-only."
        )

        tools = QGroupBox(_("Create a list"))
        self.copy_button = QPushButton(_("&Copy current list to…"))
        self.copy_button.setEnabled(document is not None)
        self.new_button = QPushButton(_("&New empty list…"))
        tool_row = QHBoxLayout()
        tool_row.addWidget(self.copy_button)
        tool_row.addWidget(self.new_button)
        tool_row.addStretch(1)
        self.note = hint()
        self.note.hide()
        tools_layout = QVBoxLayout(tools)
        tools_layout.addLayout(tool_row)
        tools_layout.addWidget(self.note)

        self.body.addWidget(box)
        self.body.addWidget(hint(explain))
        self.body.addWidget(tools)
        self.body.addStretch(1)

        current = document.path if document else None
        others = [p for p in recent if self._kind(p) is ListKind.SHARED]
        if current is not None and self._kind(current) is ListKind.SHARED:
            others.insert(0, current)
        if others:
            self.other_path.setText(str(others[0]))
        self._select(current if current is not None else personal_list)

        # Only the button turning on: each refresh checks files, maybe on a slow share.
        self._choices.buttonToggled.connect(lambda _button, on: on and self._refresh())
        self.other_path.textEdited.connect(lambda _text: self.other_choice.setChecked(True))
        self.other_path.editingFinished.connect(self._refresh)
        browse.clicked.connect(self._browse)
        self.copy_button.clicked.connect(self._copy_current)
        self.new_button.clicked.connect(self._new_empty)
        self._refresh()

    def chosen(self) -> Path | None:
        if self.default_choice.isChecked():
            return self._default
        if self.personal_choice.isChecked():
            return self._personal
        text = self.other_path.text().strip().strip('"')
        return Path(text) if text else None

    def is_valid(self) -> bool:
        path = self.chosen()
        if path is None:
            return False
        # The personal list is created when it's missing; other lists must exist.
        return self._kind(path) is ListKind.PERSONAL or path.is_file()

    def _kind(self, path: Path) -> ListKind:
        return locations.list_kind(path, default=self._default, personal=self._personal)

    def _select(self, path: Path) -> None:
        kind = self._kind(path)
        if kind is ListKind.DEFAULT:
            self.default_choice.setChecked(True)
        elif kind is ListKind.PERSONAL:
            self.personal_choice.setChecked(True)
        else:
            self.other_path.setText(str(path))
            self.other_choice.setChecked(True)

    def _refresh(self) -> None:
        default = locations.list_access(self._default)
        self.default_choice.setEnabled(default is not Access.MISSING)
        self.default_state.setText(_state_text(default, _("Not found")))
        personal = locations.list_access(self._personal)
        self.personal_state.setText(_state_text(personal, _("Created when opened")))
        text = self.other_path.text().strip().strip('"')
        other = Path(text) if text else None
        if other is None:
            self.other_state.setText("")
        else:
            access = locations.list_access(other)
            self.other_state.setText(_state_text(access, _("File not found")))
        self.changed.emit()

    def _browse(self) -> None:
        start = self.other_path.text().strip() or str(self._personal.parent)
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Choose a host list"), start, list_file_filter()
        )
        if name:
            self._select(Path(name))
            self._refresh()

    def _ask_path(self, title: str) -> Path | None:
        start = self._document.path.parent if self._document else self._personal.parent
        name, _filter = QFileDialog.getSaveFileName(self, title, str(start), list_file_filter())
        return Path(name) if name else None

    def _copy_current(self) -> None:
        doc = self._document
        if doc is None:
            return
        path = self._ask_path(_("Copy the current list to"))
        # The file dialog already asked before choosing an existing file.
        if path is not None and self._write(
            path, lambda: OpenList.save_as(path, doc.hosts, replace_existing=path.exists())
        ):
            self.note.setText(
                _("List copied to “{path}”. Click Save to open it.").format(path=path)
            )
            self.note.show()

    def _new_empty(self) -> None:
        path = self._ask_path(_("New empty host list"))
        if path is not None and self._write(
            path, lambda: OpenList.create(path, replace_existing=path.exists())
        ):
            self.note.setText(
                _("List created at “{path}”. Click Save to open it.").format(path=path)
            )
            self.note.show()

    def _write(self, path: Path, write: Callable[[], object]) -> bool:
        try:
            write()
        except (HostListFileError, OSError) as e:
            message = _("Couldn't write “{path}”: {error}").format(path=path, error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return False
        self.written.append(path)
        self._select(path)
        self._refresh()
        return True


def _state_text(access: Access, missing: str) -> str:
    return {
        Access.READ_ONLY: _("Read-only"),
        Access.READ_WRITE: _("Read-write"),
        Access.MISSING: missing,
    }[access]


# ---- Language ----


class LanguagePage(Page):
    def __init__(self, current: str) -> None:
        super().__init__(_("Language"))
        self._group = QButtonGroup(self)
        box = QGroupBox(_("App language"))
        layout = QVBoxLayout(box)
        # Each language is named in its own language, so anyone can find theirs.
        for code, name in i18n.LANGUAGES.items():
            button = QRadioButton(name)
            button.setProperty("language", code)
            button.setChecked(code == current)
            self._group.addButton(button)
            layout.addWidget(button)
        layout.addWidget(hint(_("Changes take effect immediately, without restarting the app.")))
        self.body.addWidget(box)
        self.body.addWidget(hint(_("You can also change the language under View > Language.")))
        self.body.addStretch(1)

    def language(self) -> str:
        button = self._group.checkedButton()
        return str(button.property("language")) if button else i18n.DEFAULT_LANGUAGE

    def buttons(self) -> list[QRadioButton]:
        return [b for b in self._group.buttons() if isinstance(b, QRadioButton)]


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
