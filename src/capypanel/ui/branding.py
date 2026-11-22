import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

log = logging.getLogger(__name__)
APP_ID = "CapyPanel.CapyPanel"
BRANDING_DIR = Path(__file__).resolve().parent / "branding"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(BRANDING_DIR / f"capypanel-icon-{size}.png"), QSize(size, size))
    return icon


def mascot(height: int, pixel_ratio: float = 1.0) -> QPixmap:
    svg = (BRANDING_DIR / "capypanel-mascot.svg").read_bytes()
    renderer = QSvgRenderer(QByteArray(svg))
    box = renderer.viewBoxF()
    width = round(height * box.width() / box.height()) if box.height() else height
    pixmap = QPixmap(round(width * pixel_ratio), round(height * pixel_ratio))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(pixmap.rect()))
    painter.end()
    pixmap.setDevicePixelRatio(pixel_ratio)
    return pixmap


def use_own_taskbar_icon() -> None:
    """From source, Windows would group the app under python.exe with its icon."""
    if getattr(sys, "frozen", False):
        return
    _set_app_id(APP_ID)


def _set_app_id(app_id: str) -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        log.debug("No taskbar app id")
