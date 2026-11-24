import math
from collections.abc import Sequence

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui import branding
from capypanel.ui.icons import tabler_icon
from capypanel.ui.notes import hint, notes
from capypanel.ui.tool_catalog import ToolInfo

MASCOT_HEIGHT = 150
TILE_SIZE = (330, 84)
TILE_GAP = 14
ICON_SIZE = 24
PRESS_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
KEYPAD = Qt.KeyboardModifier.KeypadModifier
ARROWS = {Qt.Key.Key_Left: (0, -1), Qt.Key.Key_Right: (0, 1),
          Qt.Key.Key_Up: (-1, 0), Qt.Key.Key_Down: (1, 0)}  # fmt: skip


class ToolTile(QFrame):
    clicked = Signal()

    def __init__(self, tool: ToolInfo, shortcut: str) -> None:
        super().__init__()
        self.tool = tool
        self.setObjectName("homeTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedSize(*TILE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.badge = QLabel()
        self.badge.setObjectName("tileBadge")
        self.badge.setFixedSize(44, 44)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel()
        font = self.name.font()
        font.setPointSizeF(font.pointSizeF() + 1.5)
        font.setBold(True)
        self.name.setFont(font)
        self.about = notes("")
        self.keys = hint(shortcut)
        self.keys.setWordWrap(False)
        words = QVBoxLayout()
        words.setSpacing(2)
        words.addWidget(self.name)
        words.addWidget(self.about)
        words.addStretch(1)
        head = QHBoxLayout()
        head.addLayout(words, 1)
        head.addWidget(self.keys, 0, Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(14)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(head, 1)
        self.retranslate()
        self.restyle()

    def retranslate(self) -> None:
        self.name.setText(_(self.tool.name))
        self.about.setText(_(self.tool.blurb))

    def restyle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.Text)
        self.badge.setPixmap(tabler_icon(self.tool.icon, color, ICON_SIZE).pixmap(ICON_SIZE))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in PRESS_KEYS and not event.modifiers() & ~KEYPAD:
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class HomePage(QWidget):
    tool_picked = Signal(str)

    def __init__(self, tools: Sequence[ToolInfo]) -> None:
        super().__init__()
        self.mascot = QLabel()
        self.title = QLabel("CapyPanel")
        font = self.title.font()
        font.setPointSizeF(font.pointSizeF() + 10)
        font.setBold(True)
        self.title.setFont(font)
        self.tagline = notes("")
        self.tagline.setWordWrap(False)
        self.tiles = [ToolTile(tool, f"Ctrl+{index}") for index, tool in enumerate(tools, start=1)]
        for tile in self.tiles:
            tile.clicked.connect(lambda t=tile: self.tool_picked.emit(t.tool.tool_id))
        self._grid = QGridLayout()
        self._grid.setSpacing(TILE_GAP)
        self._columns = 0
        column = QVBoxLayout(self)
        column.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        column.setContentsMargins(40, 24, 40, 24)
        column.addStretch(2)
        column.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(10)
        column.addWidget(self.title, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.tagline, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(26)
        tiles = QHBoxLayout()
        tiles.addStretch(1)
        tiles.addLayout(self._grid)
        tiles.addStretch(1)
        column.addLayout(tiles)
        column.addStretch(3)
        self._place_tiles(len(self.tiles))
        self.retranslate()
        self.restyle()

    def retranslate(self) -> None:
        self.tagline.setText(_("Every computer you look after, in one window."))
        for tile in self.tiles:
            tile.retranslate()

    def restyle(self) -> None:
        self.mascot.setPixmap(branding.mascot(MASCOT_HEIGHT, self.devicePixelRatioF()))
        for tile in self.tiles:
            tile.restyle()

    def _place_tiles(self, fit: int) -> None:
        count = len(self.tiles)
        if not count:
            return
        widest = count if count < 4 else math.ceil(count / 2)
        columns = max(1, min(fit, widest))
        columns = math.ceil(count / math.ceil(count / columns))  # 3 + 3 + 3, never 4 + 4 + 1
        if columns == self._columns:
            return
        self._columns = columns
        for tile in self.tiles:
            self._grid.removeWidget(tile)
        for index, tile in enumerate(self.tiles):
            self._grid.addWidget(tile, index // columns, index % columns)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        step = ARROWS.get(Qt.Key(event.key()))
        tile = next((t for t in self.tiles if t.hasFocus()), None)
        if step is None or tile is None or event.modifiers() & ~KEYPAD or not self._columns:
            super().keyPressEvent(event)
            return
        index = self.tiles.index(tile)
        row, column = divmod(index, self._columns)
        row, column = row + step[0], column + step[1]
        to = row * self._columns + column
        if 0 <= column < self._columns and 0 <= to < len(self.tiles):
            self.tiles[to].setFocus(Qt.FocusReason.OtherFocusReason)

    def minimumSizeHint(self) -> QSize:
        return QSize(TILE_SIZE[0] + 80, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        room = self.width() - 80
        self._place_tiles((room + TILE_GAP) // (TILE_SIZE[0] + TILE_GAP))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()
