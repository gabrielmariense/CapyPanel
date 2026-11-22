import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.inventory import PowerShellBlocked
from capypanel.ui import help_links
from capypanel.ui.hosts_tool.result_strip import ResultStrip
from capypanel.ui.hosts_tool.runner import Outcome, reason_place
from capypanel.ui.themes import engine as themes

SHORT = "Couldn't log off <b>bruno</b> on PC-1: access denied."
LONG = (
    "Couldn't open Startup folder on PC-1: it didn't answer. It may be off, asleep or out of"
    " reach, or a firewall stops the request on its way there."
)


def _strip(qapp: QApplication, text: str, width: int) -> ResultStrip:
    strip = ResultStrip()
    strip.show_outcome(Outcome(text, error=RuntimeError("denied"), retry=lambda: None))
    strip.resize(width, strip.heightForWidth(width))
    qapp.processEvents()
    return strip


def _first_line_middle(strip: ResultStrip) -> float:
    label = strip._text  # noqa: SLF001
    rect = label.contentsRect()
    block = label.heightForWidth(rect.width())
    top = label.mapTo(strip, rect.topLeft()).y() + max(0, (rect.height() - block) // 2)
    return top + label.fontMetrics().lineSpacing() / 2


def _icon_middle(strip: ResultStrip) -> float:
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
    strip = _strip(qapp, SHORT, 1600)
    line = strip._text.fontMetrics().lineSpacing()  # noqa: SLF001
    assert strip._text.heightForWidth(strip._text.width()) == line  # noqa: SLF001  one line
    assert strip.retry_button.height() > line
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
    strip.setFont(font)
    strip.resize(900, strip.heightForWidth(900))
    qapp.processEvents()
    assert _icon_middle(strip) == pytest.approx(_first_line_middle(strip), abs=1)


def test_a_failure_the_docs_explain_links_its_line_and_one_that_worked_links_nothing(
    qapp: QApplication, no_browser: list[str]
) -> None:
    strip = ResultStrip()
    strip.show_outcome(Outcome(SHORT, RemoteError(Reason.NOT_ADMIN), retry=lambda: None))
    label = strip._text  # noqa: SLF001
    assert strip.text() == SHORT and strip.help_place() == "command-access-denied"
    assert label.text().startswith(SHORT) and "What does this mean?" in label.text()
    label.linkActivated.emit("")
    assert no_browser == [help_links.url("command-access-denied")]
    strip.show_outcome(Outcome("Logged off <b>bruno</b> on PC-1."))
    assert strip.help_place() == "" and label.text() == "Logged off <b>bruno</b> on PC-1."


def test_each_reason_links_a_line_the_docs_have_or_nothing() -> None:
    linked = [
        (RemoteError(Reason.UNREACHABLE), "pc-unreachable"),
        (RemoteError(Reason.NOT_ADMIN), "command-access-denied"),
        (RemoteError(Reason.REJECTED), "pc-account-rejected"),
        (RemoteError(Reason.OTHER, 1722), "command-windows-error"),
        (PowerShellBlocked(OSError(1260, "blocked")), "pc-powershell-blocked"),
        (TimeoutError(), "command-timed-out"),
        (NotADirectoryError(), "command-no-folder"),
    ]
    for error, place in linked:
        assert reason_place(error) == place and place in help_links.PLACES
    assert reason_place(RuntimeError("busy")) == "" and reason_place(OSError("odd")) == ""
