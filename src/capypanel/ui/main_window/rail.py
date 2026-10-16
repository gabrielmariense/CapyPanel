"""The rail on the window's left edge: one icon per tool, and Settings at the bottom."""

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon

RAIL_WIDTH = 52
ICON_SIZE = 22


class ToolRail(QWidget):
    """Icons only, each with a tooltip. The tool shown has a tinted square behind its icon."""

    settings_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("toolRail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)  # the stylesheet paints it
        self.setFixedWidth(RAIL_WIDTH)
        self.hosts_button = _button(checkable=True)
        self.hosts_button.setChecked(True)  # the only tool for now
        # One tool is always shown: clicking it again keeps it picked.
        self._tools = QButtonGroup(self)
        self._tools.setExclusive(True)
        self._tools.addButton(self.hosts_button)
        self.settings_button = _button(checkable=False)
        self.settings_button.clicked.connect(self.settings_requested)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.hosts_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        layout.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.retranslate()
        self.restyle()

    def retranslate(self) -> None:
        self.hosts_button.setToolTip(_("Hosts (Ctrl+1)"))
        self.settings_button.setToolTip(_("Settings (Ctrl+,)"))

    def restyle(self) -> None:
        """Icons in the theme's colours: the tool shown in the text colour, the rest dimmer."""
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.Text)
        back = palette.color(QPalette.ColorRole.Window)
        # Halfway to the background: SVG icons take no transparency.
        dim = QColor(
            (text.red() + back.red()) // 2,
            (text.green() + back.green()) // 2,
            (text.blue() + back.blue()) // 2,
        )
        self.hosts_button.setIcon(tabler_icon("device-desktop", text, ICON_SIZE))
        self.settings_button.setIcon(tabler_icon("settings", dim, ICON_SIZE))

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
