"""The toolbar: buttons in captioned groups (set here, not by users), Refresh lined up with the
end of the host table, and the search box over the details pane. Refresh always checks every
host the table shows; one host is checked from its own right-click menu. Left-click picks one
check; right-click opens a panel to run several at once."""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QFont, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.icons import glyph_icon
from capypanel.ui.main_window.actions import Actions
from capypanel.ui.themes import engine as themes

SEARCH_WIDTH = 240  # the search box's width when the details pane leaves no room


class RefreshPanel(QFrame):
    """Right-click on Refresh: tick what to check on the hosts shown, then Run. It stays open
    while boxes are ticked; the ticks are kept for next time."""

    run_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self._check_title = _section("")
        self.status_box, self.users_box = QCheckBox(), QCheckBox()
        self.run_button = QPushButton()
        self.run_button.setDefault(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        for widget in (self._check_title, self.status_box, self.users_box):
            layout.addWidget(widget)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.run_button)
        layout.addSpacing(6)
        layout.addLayout(row)
        self.status_box.toggled.connect(self._update)
        self.users_box.toggled.connect(self._update)
        self.run_button.clicked.connect(self._run)
        self.retranslate()

    def retranslate(self) -> None:
        self._check_title.setText(_("Check every host shown"))
        self.status_box.setText(_("&Status"))
        self.users_box.setText(_("&Logged-on users"))
        self.run_button.setText(_("&Run"))

    def choices(self) -> dict[str, bool]:
        return {"status": self.status_box.isChecked(), "users": self.users_box.isChecked()}

    def set_choices(self, saved: object) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.status_box.setChecked(saved.get("status", True) is not False)
        self.users_box.setChecked(saved.get("users", True) is not False)
        self._update()

    def _update(self) -> None:
        self.run_button.setEnabled(self.status_box.isChecked() or self.users_box.isChecked())

    def _run(self) -> None:
        self.hide()
        self.run_clicked.emit()


class MainToolBar(QToolBar):
    refresh_panel_requested = Signal(QPoint)
    refresh_requested = Signal(bool, bool)  # status, users: on every host shown

    def __init__(self, commands: Actions, search: QWidget) -> None:
        super().__init__()
        self.setObjectName("main")
        self.setMovable(False)
        self.setFloatable(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)  # no hide-me menu
        self._commands = commands
        self._captions: list[tuple[QLabel, str]] = []

        # Connect: the host's own profile; the arrow connects once with another profile.
        self.connect_button = _button()
        self.connect_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.connect_menu = QMenu(self.connect_button)
        self.connect_button.setMenu(self.connect_menu)
        self.connect_button.clicked.connect(commands.connect_host.trigger)
        commands.connect_host.enabledChanged.connect(self.connect_button.setEnabled)

        # One row in a plain layout: QToolBar's own layout moves fixed-size spacers into its
        # overflow menu, so Refresh couldn't be lined up with the host table.
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._row = QHBoxLayout(row)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        self._row.addWidget(self._group("connect", [self.connect_button]))
        self._row.addStretch(1)
        self.refresh_button = _button()
        self.refresh_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.refresh_menu = QMenu(self.refresh_button)
        self.refresh_status = self.refresh_menu.addAction("")
        self.refresh_users = self.refresh_menu.addAction("")
        self.refresh_status.triggered.connect(lambda: self.refresh_requested.emit(True, False))
        self.refresh_users.triggered.connect(lambda: self.refresh_requested.emit(False, True))
        self.refresh_button.setMenu(self.refresh_menu)
        self.refresh_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.refresh_button.customContextMenuRequested.connect(
            lambda _pos: self.refresh_panel_requested.emit(
                self.refresh_button.mapToGlobal(QPoint(0, self.refresh_button.height()))
            )
        )
        self._row.addWidget(self.refresh_button)
        # The search box, over the details pane: it keeps Refresh at the end of the host table.
        self._search_slot = QWidget()
        self._slot = QHBoxLayout(self._search_slot)
        self._slot.setContentsMargins(0, 0, 0, 0)
        self._slot.addWidget(search)
        self._search_slot.setFixedWidth(SEARCH_WIDTH)
        self._row.addWidget(self._search_slot)
        self.addWidget(row)
        self.retranslate()

    def retranslate(self) -> None:
        custom = themes.current().engine == "custom"
        texts = {"connect": _("Connect")}
        for label, key in self._captions:
            # Capitals in the CapyPanel looks, in the text itself: a theme switch resets fonts.
            label.setText(texts[key].upper() if custom else texts[key])
        gap = " " if custom else ""  # QSS drops the icon gap
        self.connect_button.setText(gap + _("Connect"))
        self.connect_button.setToolTip(
            _("Connect to the selected hosts; the arrow connects once with another profile")
        )
        self.refresh_button.setText(gap + _("Refresh"))
        self.refresh_button.setToolTip(
            _("Check every host shown; right-click to run several checks at once")
        )
        self.refresh_status.setText(_("&Status"))
        self.refresh_users.setText(_("&Logged-on users"))

    def align_end(self, right: int, gap: int) -> None:
        """Puts Refresh's right edge at `right` (in this toolbar's coordinates) and the search
        box over the details pane, `gap` further on. With the details pane hidden, there's no
        room: the search box keeps its own width and Refresh moves left of it."""
        row = self.refresh_button.parentWidget()
        if row is None:
            return
        end = row.mapTo(self, QPoint(row.width(), 0)).x()  # doesn't move with the slot
        width = end - right
        fits = width - gap >= SEARCH_WIDTH
        self._slot.setContentsMargins(gap if fits else 8, 0, 0, 0)
        self._search_slot.setFixedWidth(width if fits else SEARCH_WIDTH + 8)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.restyle()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()

    def restyle(self) -> None:
        """Icons in the theme's text colour, and captions for the theme (see retranslate)."""
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.connect_button.setIcon(glyph_icon("connect", color))
        self.refresh_button.setIcon(glyph_icon("refresh", color))
        self.retranslate()

    def _group(self, key: str, buttons: list[QToolButton]) -> QWidget:
        group = QWidget()
        column = QVBoxLayout(group)
        column.setContentsMargins(6, 0, 6, 0)
        column.setSpacing(0)
        row = QHBoxLayout()
        row.setSpacing(2)
        for button in buttons:
            row.addWidget(button)
        caption = QLabel()
        caption.setObjectName("toolCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont(caption.font())
        font.setPointSizeF(font.pointSizeF() * 0.85)
        caption.setFont(font)
        column.addLayout(row)
        column.addWidget(caption)
        # A caption names a group of buttons; over one button it would only repeat its name.
        caption.setVisible(len(buttons) > 1)
        self._captions.append((caption, key))
        return group


def _button() -> QToolButton:
    button = QToolButton()
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    return button


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("menuSection")
    return label
