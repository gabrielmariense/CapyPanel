"""Tabler Icons (MIT, tabler/LICENSE)."""

from functools import cache, lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

TABLER_DIR = Path(__file__).resolve().parent / "tabler"


def _pixmap(px: int) -> QPixmap:
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    pixmap = QPixmap(round(px * ratio), round(px * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def tabler_icon(name: str, color: QColor, px: int = 16) -> QIcon:
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else 1.0
    return QIcon(_drawn(name, color.name(), px, ratio))


@cache
def _svg(name: str) -> str:
    return (TABLER_DIR / f"{name}.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=1024)
def _drawn(name: str, color: str, px: int, _ratio: float) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name).replace("currentColor", color).encode()))
    pixmap = _pixmap(px)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    return pixmap


def dot_icon(color: str, px: int = 10) -> QIcon:
    pixmap = _pixmap(px)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, px - 2, px - 2)
    painter.end()
    return QIcon(pixmap)
