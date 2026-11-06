"""The supply bars' marks: kept in Settings, set in their own window, drawn with an outline."""

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog, QInputDialog, QLabel, QMessageBox
from test_printer_status import _checked, _supply, lab, printers  # noqa: F401  (fixtures)

from capypanel.core.printers.reading import Supply, SupplyKind
from capypanel.ui.printers_tool import marks
from capypanel.ui.printers_tool import settings as settings_module
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.printers_tool.meter import HEIGHT, OUTLINE, REACH, ROOM, draw_meter
from capypanel.ui.printers_tool.settings import BarMarksDialog
from capypanel.ui.printers_tool.tool import PrintersTool


def test_by_default_only_the_low_mark() -> None:
    assert marks.load({}, 10) == (Mark(10, low=True),)
    assert marks.hint((Mark(10, low=True),)) == "The mark shows the low level, 10 %."


def test_load_skips_odd_entries_and_keeps_the_low_mark_first() -> None:
    prefs = {
        marks.EXTRA: [
            {"percent": 75, "color": "#FF0000"},
            {"percent": 25},
            {"percent": 10, "color": "#00ff00"},  # where the low mark is: skipped
            {"percent": 25, "color": "#0000ff"},  # twice: the first one
            {"percent": 0}, {"percent": 100}, {"percent": True}, {"percent": "50"}, "x",
            {"percent": 50, "color": "red"},  # not #rrggbb: the theme's colour
        ],
        marks.LOW_COLOR: "#123456",
    }  # fmt: skip
    assert marks.load(prefs, 10) == (
        Mark(10, "#123456", low=True), Mark(25), Mark(50), Mark(75, "#ff0000"),
    )  # fmt: skip
    assert marks.percents_text(marks.load(prefs, 10)) == "10 % (low), 25 %, 50 %, 75 %"


def test_save_and_load_round_trip() -> None:
    prefs: dict[str, object] = {}
    chosen = (Mark(10, "#ffffff", low=True), Mark(50, "#ff00ff"))
    marks.save(prefs, chosen)
    assert marks.load(prefs, 10) == chosen
    marks.save(prefs, (Mark(10, low=True),))
    assert prefs == {}  # the default leaves nothing behind


def test_the_low_mark_follows_the_low_level(printers: PrintersTool) -> None:  # noqa: F811
    printers.set_bar_marks((Mark(10, low=True), Mark(50)))
    printers.set_low_level(20)
    assert printers.bar_marks() == (Mark(20, low=True), Mark(50))
    assert printers.table.marks == printers.bar_marks()


def test_details_shows_where_the_marks_are(printers: PrintersTool) -> None:  # noqa: F811
    doc = printers.document
    assert doc is not None
    printer = next(h for h in doc.hosts.hosts if h.name == "3F-LAB-01")
    printers._checked[printer.id] = _checked(supplies=(_supply("Black Cartridge", 40),))
    printers.table.select_ids([printer.id])
    labels = [w.text() for w in printers.details.findChildren(QLabel)]
    assert "The mark shows the low level, 10 %." in labels
    printers.set_bar_marks((Mark(10, low=True), Mark(50, "#ff0000")))
    labels = [w.text() for w in printers.details.findChildren(QLabel)]
    assert "The marks show 10 % (low), 50 %." in labels


def test_the_window_adds_colours_and_removes_marks(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = BarMarksDialog(None, (Mark(10, low=True),))
    assert dialog.picked() == 0 and not dialog.remove_button.isEnabled()  # the low mark stays
    monkeypatch.setattr(QInputDialog, "getInt", lambda *a, **k: (50, True))
    dialog.add_button.click()
    assert dialog.marks() == (Mark(10, low=True), Mark(50))
    assert dialog.picked() == 1 and dialog.remove_button.isEnabled()
    monkeypatch.setattr(QColorDialog, "getColor", lambda *a, **k: QColor("#ff8800"))
    dialog.colour_button.click()
    assert dialog.marks()[1] == Mark(50, "#ff8800")
    assert dialog.table.topLevelItem(1).text(1) == "#ff8800"  # type: ignore[union-attr]
    dialog.theme_button.click()
    assert dialog.marks()[1] == Mark(50)
    told: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: told.append(text))
    dialog.add_button.click()  # 50 again: refused, nothing added
    assert len(dialog.marks()) == 2 and told == ["There's a mark at 50 % already."]
    dialog.remove_button.click()
    assert dialog.marks() == (Mark(10, low=True),)
    dialog.colour_button.click()  # the low mark can have a colour too
    dialog.add_button.click()
    dialog.reset_button.click()
    assert dialog.marks() == (Mark(10, low=True),)


def test_settings_row_opens_the_window_and_keeps_its_answer(
    printers: PrintersTool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = printers.settings_group()
    group.build()
    page = group.general
    assert page.marks_row.description.text() == "Lines across the supply bars at 10 % (low)."

    def answer(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, BarMarksDialog)
        dialog._marks.append(Mark(50, "#ffffff"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", answer)
    page.marks_button.click()
    assert printers.bar_marks() == (Mark(10, low=True), Mark(50, "#ffffff"))
    assert page.marks_row.description.text() == "Lines across the supply bars at 10 % (low), 50 %."


def test_each_mark_has_a_black_outline_and_its_colour(qapp: QApplication) -> None:
    width = 200
    image = QImage(width, HEIGHT + 2 * ROOM, QImage.Format.Format_RGB32)
    image.fill(QColor("#336699"))
    painter = QPainter(image)
    supply = Supply("Black", SupplyKind.TONER, 100)  # a full bar: the marks sit on the fill
    draw_meter(painter, QRectF(0, ROOM, width, HEIGHT), supply,
               (Mark(50, "#ff0000"),), QColor("#ffffff"))  # fmt: skip
    painter.end()
    x = round(width * 0.5) - 1
    top = ROOM - REACH
    assert QColor(image.pixel(x, top + 1)).name() == "#ff0000"  # its own colour
    assert QColor(image.pixel(x - OUTLINE, top + 1)).name() == "#000000"  # outlined
    assert QColor(image.pixel(x, top - OUTLINE)).name() == "#000000"
