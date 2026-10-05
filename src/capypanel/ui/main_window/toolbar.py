"""The toolbar: buttons in captioned groups (set here, not by users) and Refresh on the right,
lined up with the end of the host table. Left-click on Refresh picks one check for the
selected hosts; right-click opens a panel that remembers what to check and where."""

from typing import Any

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QFont, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpacerItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.icons import glyph_icon
from capypanel.ui.main_window.actions import Actions
from capypanel.ui.themes import engine as themes

WHERE_SELECTED, WHERE_GROUP = "selected", "group"


class RefreshPanel(QFrame):
    """Right-click on Refresh: what to check and on which hosts, then Run. It stays open while
    boxes are ticked; the choices are kept for next time."""

    run_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self._check_title, self._where_title = _section(""), _section("")
        self.status_box, self.users_box = QCheckBox(), QCheckBox()
        self.selected_radio, self.group_radio = QRadioButton(), QRadioButton()
        self.run_button = QPushButton()
        self.run_button.setDefault(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        for widget in (
            self._check_title, self.status_box, self.users_box,
            self._where_title, self.selected_radio, self.group_radio,
        ):  # fmt: skip
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
        self._check_title.setText(_("Check"))
        self._where_title.setText(_("Which hosts"))
        self.status_box.setText(_("&Status"))
        self.users_box.setText(_("&Logged-on users"))
        self.selected_radio.setText(_("S&elected hosts"))
        self.group_radio.setText(_("&Whole group"))
        self.run_button.setText(_("&Run"))

    def choices(self) -> dict[str, Any]:
        return {
            "status": self.status_box.isChecked(),
            "users": self.users_box.isChecked(),
            "where": WHERE_GROUP if self.group_radio.isChecked() else WHERE_SELECTED,
        }

    def set_choices(self, saved: object) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.status_box.setChecked(saved.get("status", True) is not False)
        self.users_box.setChecked(saved.get("users", True) is not False)
        group = saved.get("where") == WHERE_GROUP
        (self.group_radio if group else self.selected_radio).setChecked(True)
        self._update()

    def _update(self) -> None:
        self.run_button.setEnabled(self.status_box.isChecked() or self.users_box.isChecked())

    def _run(self) -> None:
        self.hide()
        self.run_clicked.emit()


class MainToolBar(QToolBar):
    refresh_panel_requested = Signal(QPoint)

    def __init__(self, commands: Actions) -> None:
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
        self.refresh_menu.addActions([commands.check_status, commands.check_users])
        self.refresh_button.setMenu(self.refresh_menu)
        self.refresh_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.refresh_button.customContextMenuRequested.connect(
            lambda _pos: self.refresh_panel_requested.emit(
                self.refresh_button.mapToGlobal(QPoint(0, self.refresh_button.height()))
            )
        )
        self._row.addWidget(self.refresh_button)
        # Keeps Refresh at the end of the host table rather than the window's edge.
        self._after_refresh = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed)
        self._row.addSpacerItem(self._after_refresh)
        self.addWidget(row)
        self.retranslate()

    def retranslate(self) -> None:
        texts = {"connect": _("Connect")}
        for label, key in self._captions:
            label.setText(texts[key])
        gap = " " if themes.current().engine == "custom" else ""  # QSS drops the icon gap
        self.connect_button.setText(gap + _("Connect"))
        self.connect_button.setToolTip(
            _("Connect to the selected hosts; the arrow connects once with another profile")
        )
        self.refresh_button.setText(gap + _("Refresh"))
        self.refresh_button.setToolTip(
            _("Check the selected hosts; right-click to choose what to check and where")
        )

    def align_end(self, right: int) -> None:
        """Puts Refresh's right edge at `right`, in this toolbar's coordinates."""
        row = self.refresh_button.parentWidget()
        if row is None:
            return
        end = row.mapTo(self, QPoint(row.width(), 0)).x()  # doesn't move with the spacer
        width = max(0, end - right)
        if width != self._after_refresh.sizeHint().width():
            self._after_refresh.changeSize(width, 0, QSizePolicy.Policy.Fixed)
            self._row.invalidate()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.restyle()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()

    def restyle(self) -> None:
        """Icons in the theme's text colour; captions in capitals in the CapyPanel themes."""
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.connect_button.setIcon(glyph_icon("connect", color))
        self.refresh_button.setIcon(glyph_icon("refresh", color))
        custom = themes.current().engine == "custom"
        for label, _key in self._captions:
            font = QFont(label.font())
            font.setCapitalization(
                QFont.Capitalization.AllUppercase if custom else QFont.Capitalization.MixedCase
            )
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8 if custom else 0)
            label.setFont(font)
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
