import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QSplashScreen

from capypanel.core import updates
from capypanel.core.i18n import _
from capypanel.ui.branding import BRANDING_DIR

log = logging.getLogger(__name__)

SPLASH = BRANDING_DIR / "splash.png"
BASELINE = 272  # where the launcher writes the version (packaging/capypanel.spec)
TEXT_PX = 16  # Segoe UI at 16 pixels, light, as the launcher writes it
TEXT_COLOR = "#dde3ee"
HAND_OVER = 1.5  # seconds


class UpdateSplash(QSplashScreen):
    """Qt's splash closes on a click; this one stays until the new CapyPanel's shows."""

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- Qt's name
        event.accept()


def splash_text(version: str) -> str:
    return _("Updating to {version}…").format(version=version)


def picture(text: str, ratio: float) -> QPixmap:
    pixmap = QPixmap(str(SPLASH))
    painter = QPainter(pixmap)
    font = QFont("Segoe UI")
    font.setPixelSize(TEXT_PX)
    painter.setFont(font)
    painter.setPen(QColor(TEXT_COLOR))
    left = (pixmap.width() - QFontMetrics(font).horizontalAdvance(text)) // 2
    painter.drawText(QPoint(max(0, left), BASELINE), text)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def run(
    app_dir: Path,
    pid: int,
    old: str,
    new: str,
    close_launcher_splash: Callable[[], None],
    staging: Path | None = None,
) -> int:
    app = QApplication.instance() or QApplication([])
    screen = QGuiApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    splash = UpdateSplash(picture(splash_text(new), ratio))
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
    splash.show()
    app.processEvents()
    close_launcher_splash()
    done: dict[str, int] = {}
    worker = threading.Thread(
        target=lambda: done.update(code=updates.run_helper(app_dir, pid, old, new, staging)),
        name="update-apply",
        daemon=True,
    )
    worker.start()
    while worker.is_alive():
        app.processEvents()
        worker.join(0.03)
    until = time.monotonic() + HAND_OVER
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(0.03)
    splash.close()
    return done.get("code", 1)
