"""A supply's level as a bar with a tick at the low level: in Details, and in the Toner column
when Settings asks for bars. One drawing, so both look the same."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from capypanel.core.printers.reading import Supply
from capypanel.ui.printers_tool import status

HEIGHT = 6


def draw_meter(painter: QPainter, bar: QRectF, supply: Supply, low: int, text: QColor) -> None:
    """The bar in `bar`, its track and tick tinted from the text colour, so they read in every
    theme. "Some left" fills half; an unknown level, none."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QColor(text)
    track.setAlpha(36)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(bar, 3, 3)
    fill = supply.percent / 100 if supply.percent is not None else 0.5 if supply.some_left else 0
    if fill:
        painter.setBrush(QColor(status.supply_color(supply)))
        width = max(4.0, bar.width() * fill)
        painter.drawRoundedRect(QRectF(bar.x(), bar.y(), width, bar.height()), 3, 3)
    mark = QColor(text)
    mark.setAlpha(150)
    painter.setPen(mark)
    x = round(bar.x() + bar.width() * low / 100)
    painter.drawLine(x, round(bar.y()) - 1, x, round(bar.bottom()) + 1)
    painter.restore()
