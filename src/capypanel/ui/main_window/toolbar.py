"""The toolbar: outlined buttons in groups split by thin lines (set here, not by users) and Refresh,
lined up with the end of the host table. Refresh always checks every host the table shows (the
group picked on the left); one host is checked from its own right-click menu. Left-click picks
one check; right-click opens a panel to run several at once."""

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
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

    def __init__(self, commands: Actions) -> None:
        super().__init__()
        self.setObjectName("main")
        self.setMovable(False)
        self.setFloatable(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)  # no hide-me menu
        self._commands = commands

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
        self._groups = 0
        self._row.addWidget(self._group([self.connect_button]))
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
        # Keeps Refresh at the end of the host table rather than the window's edge.
        self._after_refresh = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed)
        self._row.addSpacerItem(self._after_refresh)
        self.addWidget(row)
        self.retranslate()

    def retranslate(self) -> None:
        gap = " "  # the stylesheet drops the gap between icon and text
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

    def align(self, left: int, right: int) -> None:
        """Lines the buttons up with the panes, in this toolbar's coordinates: the first group
        starts at `left` and Refresh ends at `right`. Measured, so it holds in every theme."""
        row = self.refresh_button.parentWidget()
        if row is None:
            return
        start = row.mapTo(self, QPoint(0, 0)).x()  # the margins move what's inside, not the row
        margins = self._row.contentsMargins()
        if margins.left() != max(0, left - start):
            self._row.setContentsMargins(max(0, left - start), 0, 0, 0)
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
        """Icons in the theme's text colour."""
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.connect_button.setIcon(glyph_icon("connect", color))
        self.refresh_button.setIcon(glyph_icon("refresh", color))
        self.retranslate()

    def _group(self, buttons: list[QToolButton]) -> QWidget:
        """Buttons that belong together; a thin line sets each group apart from the one before."""
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(6)
        if self._groups:
            divider = QFrame()
            divider.setObjectName("toolDivider")
            divider.setFixedWidth(1)
            row.addWidget(divider)
        self._groups += 1
        for button in buttons:
            row.addWidget(button)
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
