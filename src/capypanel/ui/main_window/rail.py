from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

from capypanel.ui.icons import tabler_icon

RAIL_WIDTH = 52
ICON_SIZE = 22
BADGE = 16


class ToolRail(QWidget):
    home_requested = Signal()
    settings_requested = Signal()
    tool_picked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("toolRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedWidth(RAIL_WIDTH)
        self.buttons: dict[str, QToolButton] = {}
        self.badges: dict[str, QLabel] = {}
        self._icons: dict[str, str] = {}
        self._tools = QButtonGroup(self)
        self._tools.setExclusive(True)
        self.home_button = _button(checkable=True)
        self._tools.addButton(self.home_button)
        self.home_button.clicked.connect(self.home_requested)
        self.home_button.toggled.connect(lambda _on: self.restyle())
        line = QFrame()
        line.setObjectName("toolDivider")
        line.setFixedSize(28, 1)
        self.help_button = _button(checkable=False)
        self.help_button.setObjectName("railHelp")
        self.settings_button = _button(checkable=False)
        self.settings_button.clicked.connect(self.settings_requested)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        self._layout.addWidget(self.home_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addWidget(line, 0, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addStretch(1)
        self._layout.addWidget(self.help_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.restyle()

    def add_tool(self, tool_id: str, icon: str) -> QToolButton:
        button = _button(checkable=True)
        self.buttons[tool_id] = button
        self._icons[tool_id] = icon
        self._tools.addButton(button)
        self._layout.insertWidget(len(self.buttons) + 1, button, 0, Qt.AlignmentFlag.AlignHCenter)
        button.clicked.connect(lambda: self.tool_picked.emit(tool_id))
        button.toggled.connect(lambda _on: self.restyle())
        badge = QLabel(button)
        badge.setObjectName("railBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        badge.hide()
        self.badges[tool_id] = badge
        self.restyle()
        return button

    def set_badge(self, tool_id: str, count: int) -> None:
        badge = self.badges[tool_id]
        badge.setVisible(count > 0)
        if count > 0:
            badge.setText(str(count) if count < 100 else "99+")
            self._place_badge(tool_id)

    def _place_badge(self, tool_id: str) -> None:
        badge, button = self.badges[tool_id], self.buttons[tool_id]
        font = badge.font()
        font.setBold(True)
        font.setPixelSize(BADGE - 5)
        badge.setFont(font)
        width = max(BADGE, badge.fontMetrics().horizontalAdvance(badge.text()) + 8)
        badge.setFixedSize(width, BADGE)
        badge.move(button.width() - width, 0)

    def show_tool(self, tool_id: str | None) -> None:
        (self.home_button if tool_id is None else self.buttons[tool_id]).setChecked(True)

    def restyle(self) -> None:
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        back = palette.color(QPalette.ColorRole.Window)
        dim = QColor(
            (text.red() + back.red()) // 2,
            (text.green() + back.green()) // 2,
            (text.blue() + back.blue()) // 2,
        )
        for tool_id, button in self.buttons.items():
            color = text if button.isChecked() else dim
            button.setIcon(tabler_icon(self._icons[tool_id], color, ICON_SIZE))
        home = text if self.home_button.isChecked() else dim
        self.home_button.setIcon(tabler_icon("home", home, ICON_SIZE))
        self.help_button.setIcon(tabler_icon("help", dim, ICON_SIZE))
        self.settings_button.setIcon(tabler_icon("settings", dim, ICON_SIZE))
        for tool_id, badge in self.badges.items():
            if not badge.isHidden():
                self._place_badge(tool_id)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()


def _button(*, checkable: bool) -> QToolButton:
    button = QToolButton()
    button.setCheckable(checkable)
    button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
    button.setFixedSize(36, 36)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button
