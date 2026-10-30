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
REACH = 3  # px the low tick sticks out above and below the bar; the half mark, one less


def draw_meter(
    painter: QPainter, bar: QRectF, supply: Supply, low: int, text: QColor, back: QColor
) -> None:
    """The bar in `bar`, its track tinted from the text colour, so it reads in every theme.
    The marks are in the text colour and stick out past the bar, with a cut in the background
    colour on each side, so they show on the filled and the empty part alike. Leave REACH px
    above and below `bar` for them. "Some left" fills half; an unknown level, none."""
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
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # crisp 2 px marks
    top, bottom = round(bar.y()), round(bar.bottom())
    for level, strong in ((HALF, False), (low, True)):
        x = round(bar.x() + bar.width() * level / 100) - MARK // 2
        mark = QColor(text)
        mark.setAlpha(255 if strong else 170)
        reach = REACH if strong else REACH - 1
        painter.fillRect(x - 1, top, MARK + 2, bottom - top, back)  # stands out on the fill
        painter.fillRect(x, top - reach, MARK, bottom - top + 2 * reach, mark)
    painter.restore()
