"""A supply's level as a bar with its marks (the low level's, and any added in Settings): in
Details, and in the Toner column when Settings asks for bars. One drawing, so both look the
same."""

from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter

from capypanel.core.printers.reading import Supply
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.themes import engine as themes

HEIGHT = 8
MARK = 2  # px: each mark's width
REACH = 4  # px the marks stick out above and below the bar
OUTLINE = 1  # px of black around each mark, so it shows on any fill and any theme
ROOM = REACH + OUTLINE  # px to leave above and below the bar


def draw_meter(
    painter: QPainter, bar: QRectF, supply: Supply, marks: Sequence[Mark], text: QColor
) -> None:
    """The bar in `bar`, its track tinted from the text colour, so it reads in every theme.
    Each mark is in its own colour (the text colour unless one was picked), outlined in black,
    and sticks out past the bar. Leave ROOM px above and below `bar` for them. "Some left"
    fills half; an unknown level, none."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QColor(text)
    track.setAlpha(36)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    corner = min(themes.current().control, bar.height() / 2)  # a control's corner, as buttons
    painter.drawRoundedRect(bar, corner, corner)
    fill = supply.percent / 100 if supply.percent is not None else 0.5 if supply.some_left else 0
    if fill:
        painter.setBrush(QColor(status.supply_color(supply)))
        width = max(4.0, bar.width() * fill)
        painter.drawRoundedRect(QRectF(bar.x(), bar.y(), width, bar.height()), corner, corner)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)  # crisp marks
    top, bottom = round(bar.y()) - REACH, round(bar.bottom()) + REACH
    black = QColor(0, 0, 0)
    for mark in marks:
        x = round(bar.x() + bar.width() * mark.percent / 100) - MARK // 2
        colour = QColor(mark.color) if mark.color else text
        painter.fillRect(x - OUTLINE, top - OUTLINE, MARK + 2 * OUTLINE,
                         bottom - top + 2 * OUTLINE, black)  # fmt: skip
        painter.fillRect(x, top, MARK, bottom - top, colour)
    painter.restore()
