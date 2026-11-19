"""Hosts' result strip: its icon sits on the middle of the text's first line, whether the text
takes one line beside the taller "Try another account…" button or wraps."""

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from capypanel.ui.hosts_tool.result_strip import ResultStrip
from capypanel.ui.hosts_tool.runner import Outcome
from capypanel.ui.themes import engine as themes

SHORT = "Couldn't log off <b>bruno</b> on PC-1: access denied."
LONG = (
    "Couldn't open Startup folder on PC-1: it didn't answer. It may be off, asleep or out of"
    " reach, or a firewall stops the request on its way there."
)


def _strip(qapp: QApplication, text: str, width: int) -> ResultStrip:
    strip = ResultStrip()
    strip.show_outcome(Outcome(text, error=RuntimeError("denied"), retry=lambda: None))
    strip.resize(width, strip.heightForWidth(width))  # as the Hosts column sizes it
    qapp.processEvents()
    return strip


def _first_line_middle(strip: ResultStrip) -> float:
    """Where QLabel paints the text's first line, in the strip: the text is a block centred in
    the label (AlignVCenter), its lines lineSpacing apart."""
    label = strip._text  # noqa: SLF001
    rect = label.contentsRect()
    block = label.heightForWidth(rect.width())
    top = label.mapTo(strip, rect.topLeft()).y() + max(0, (rect.height() - block) // 2)
    return top + label.fontMetrics().lineSpacing() / 2


def _icon_middle(strip: ResultStrip) -> float:
    """The middle of the icon as drawn: the rows holding its red, read from a grab."""
    icon = strip._icon  # noqa: SLF001
    red = QColor(themes.status_color("stopped"))
    image = strip.grab().toImage()
    left = icon.mapTo(strip, QPoint(0, 0)).x()
    rows = [
        y
        for y in range(image.height())
        for x in range(left, left + icon.width())
        if _near(image.pixelColor(x, y), red)
    ]
    assert rows, "the icon isn't drawn"
    return (min(rows) + max(rows)) / 2


def _near(a: QColor, b: QColor) -> bool:
    return abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue()) < 60


def test_one_line_beside_the_button_brings_the_icon_down_with_it(qapp: QApplication) -> None:
    strip = _strip(qapp, SHORT, 1600)  # one line in any font the earlier tests leave
    line = strip._text.fontMetrics().lineSpacing()  # noqa: SLF001
    assert strip._text.heightForWidth(strip._text.width()) == line  # noqa: SLF001  one line
    assert strip.retry_button.height() > line  # so the line sits lower than the strip's top
    assert _icon_middle(strip) == pytest.approx(_first_line_middle(strip), abs=1)


def test_a_wrapped_text_keeps_the_icon_on_its_first_line(qapp: QApplication) -> None:
    strip = _strip(qapp, LONG, 360)
    line = strip._text.fontMetrics().lineSpacing()  # noqa: SLF001
    assert strip._text.heightForWidth(strip._text.width()) >= 2 * line  # noqa: SLF001  wraps
    assert _icon_middle(strip) == pytest.approx(_first_line_middle(strip), abs=1)


def test_a_bigger_font_keeps_the_icon_on_the_line(qapp: QApplication) -> None:
    strip = _strip(qapp, SHORT, 900)
    font = QFont(strip.font())
    font.setPointSizeF(font.pointSizeF() * 2)
    strip.setFont(font)  # as a theme with its own font does, through the app's font
    strip.resize(900, strip.heightForWidth(900))
    qapp.processEvents()
    assert _icon_middle(strip) == pytest.approx(_first_line_middle(strip), abs=1)
