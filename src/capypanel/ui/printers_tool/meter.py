"""A supply's level as a bar with a tick at the low level and a fainter mark at half: in
Details, and in the Toner column when Settings asks for bars. One drawing, so both look the
same."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from capypanel.core.printers.reading import Supply
from capypanel.ui.printers_tool import status

HEIGHT = 8
HALF = 50  # %: the fainter mark
MARK = 2  # px: each mark's width


def draw_meter(
    painter: QPainter, bar: QRectF, supply: Supply, low: int, text: QColor, back: QColor
) -> None:
    """The bar in `bar`, its track tinted from the text colour, so it reads in every theme.
    The marks are cut in the background colour where the bar is filled, and drawn in the text
    colour where it's empty, so they show on both. "Some left" fills half; unknown, none."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QColor(text)
    track.setAlpha(36)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    painter.drawRoundedRect(bar, 3, 3)
    fill = supply.percent / 100 if supply.percent is not None else 0.5 if supply.some_left else 0
    filled = 0.0
    if fill:
        painter.setBrush(QColor(status.supply_color(supply)))
        filled = max(4.0, bar.width() * fill)
        painter.drawRoundedRect(QRectF(bar.x(), bar.y(), filled, bar.height()), 3, 3)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # crisp 2 px marks
    top, bottom = round(bar.y()), round(bar.bottom())
    for level, strong in ((HALF, False), (low, True)):
        x = round(bar.x() + bar.width() * level / 100) - MARK // 2
        on_fill = x + MARK <= bar.x() + filled
        mark = QColor(back if on_fill else text)
        mark.setAlpha(255 if strong else 190)
        if strong:  # the low level reaches past the bar
            painter.fillRect(x, top - 1, MARK, bottom - top + 2, mark)
        else:
            painter.fillRect(x, top + 1, MARK, bottom - top - 2, mark)
    painter.restore()
