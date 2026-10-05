"""Icons drawn from Windows' own icon font, and the status dots."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap

GLYPHS = {"connect": "", "refresh": ""}  # Segoe Fluent Icons / MDL2 Assets
STATUS_COLORS = {"online": "#3fae4a", "offline": "#8a8a8a", "unknown-name": "#d29922"}


def _pixmap(px: int) -> QPixmap:
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    pixmap = QPixmap(round(px * ratio), round(px * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def glyph_icon(name: str, color: QColor, px: int = 16) -> QIcon:
    pixmap = _pixmap(px)
    painter = QPainter(pixmap)
    font = QFont()
    font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])  # Windows 11, Windows 10
    font.setPixelSize(px)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRect(0, 0, px, px), Qt.AlignmentFlag.AlignCenter, GLYPHS[name])
    painter.end()
    return QIcon(pixmap)


def dot_icon(color: str, px: int = 10) -> QIcon:
    pixmap = _pixmap(px)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, px - 2, px - 2)
    painter.end()
    return QIcon(pixmap)
