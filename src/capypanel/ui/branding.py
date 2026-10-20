"""The app's icon and its mascot. Early artwork: the final versions replace the files in
branding/ under the same names."""

import ctypes
import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from capypanel.core import identity

log = logging.getLogger(__name__)
BRANDING_DIR = Path(__file__).resolve().parent / "branding"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # drawn for each size, not scaled down


def app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addFile(str(BRANDING_DIR / f"capypanel-icon-{size}.png"), QSize(size, size))
    return icon


def mascot(height: int, pixel_ratio: float = 1.0) -> QPixmap:
    """The mascot at its desk, `height` px tall, sharp on high-DPI screens."""
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
    """Run from Python, Windows groups the app under python.exe and shows Python's icon on the
    taskbar; its own app id makes it show the app's."""
    try:
        app_id = identity.current().windows_app_id
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):  # not Windows
        log.debug("No taskbar app id")
