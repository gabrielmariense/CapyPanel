"""A supply's level as a bar with its marks, one drawing for Details and the Toner column."""

from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from capypanel.core.printers.reading import Supply
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.themes import engine as themes

HEIGHT = 8
MARK = 2  # px: each mark's width
REACH = 4  # px the marks stick out above and below the bar
OUTLINE = 1  # px of black around each mark, so it shows on any fill and any theme
ROOM = REACH + OUTLINE


def draw_meter(
    painter: QPainter, bar: QRectF, supply: Supply, marks: Sequence[Mark], text: QColor
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    track = QColor(text)
    track.setAlpha(36)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(track)
    corner = min(themes.current().control, bar.height() / 2)
    painter.drawRoundedRect(bar, corner, corner)
    fill = supply.percent / 100 if supply.percent is not None else 0.5 if supply.some_left else 0
    if fill:
        color, edge = status.supply_color(supply), status.supply_edge(supply)
        painter.setBrush(QColor(color))
        width = max(4.0, bar.width() * fill)
        filled = QRectF(bar.x(), bar.y(), width, bar.height())
        if edge != color:
            painter.setPen(QPen(QColor(edge), 1))
            filled.adjust(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(filled, corner, corner)
        painter.setPen(Qt.PenStyle.NoPen)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    top, bottom = round(bar.y()) - REACH, round(bar.bottom()) + REACH
    black = QColor(0, 0, 0)
    for mark in marks:
        x = round(bar.x() + bar.width() * mark.percent / 100) - MARK // 2
        colour = QColor(mark.color) if mark.color else text
        painter.fillRect(x - OUTLINE, top - OUTLINE, MARK + 2 * OUTLINE,
                         bottom - top + 2 * OUTLINE, black)  # fmt: skip
        painter.fillRect(x, top, MARK, bottom - top, colour)
    painter.restore()
