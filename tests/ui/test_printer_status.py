"""Refresh on printers: the Status and Toner cells, Details, Settings' Refresh section, against
a pretend printer on 127.0.0.1 with invented data."""

import time
from collections.abc import Iterator
from datetime import datetime
from functools import partial
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QTreeWidgetItem
from snmp_agent import Objects, running

from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.printers import reading, snmp
from capypanel.core.printers.printer import PrinterInfo, info_of, with_info
from capypanel.core.printers.reading import Device, Problem, Reading, State, Supply, SupplyKind
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.printers_tool import refresh, status
from capypanel.ui.printers_tool import settings as settings_module
from capypanel.ui.printers_tool.settings import BARS, TONER_VIEW
from capypanel.ui.printers_tool.status import AMBER, GREEN, GREY, RED, Checked
from capypanel.ui.printers_tool.table import BAR_WIDTH, ROLE_SUPPLY
from capypanel.ui.printers_tool.tool import PrintersTool

NOW = datetime(2026, 10, 28, 14, 32)
S = reading.SUPPLIES


def _supply(
    name: str, percent: int | None, kind: SupplyKind = SupplyKind.TONER, **more: bool
) -> Supply:
    return Supply(name, kind, percent, **more)


def _checked(**reading_args: object) -> Checked:
    return Checked(NOW, Reading(**reading_args))  # type: ignore[arg-type]


# ---- the words and colours ----


def test_status_says_what_is_wrong_most_first() -> None:
    assert status.status(None, 10).text == "" and status.status(None, 10).quiet
    offline = status.status(Checked(NOW, offline=True), 10)
    assert (offline.text, offline.color, offline.quiet) == ("Offline", GREY, True)
    assert status.status(Checked(NOW, error="bad"), 10).text == "Unreadable"
    idle = status.status(_checked(state=State.IDLE, device=Device.RUNNING), 10)
    assert (idle.text, idle.color) == ("Idle", GREEN)
    # Many printers call their state "other" while running fine.
    assert status.status(_checked(state=State.OTHER, device=Device.RUNNING), 10).text == "Ready"
    jam = status.status(_checked(problems=frozenset({Problem.JAMMED})), 10)
    assert (jam.text, jam.color) == ("Paper jam", RED)
    # The printer's own words can be long: they go in the tip (and Details), not the cell.
    said = _checked(problems=frozenset({Problem.JAMMED}), messages=("Jam in tray 2",))
    assert status.status(said, 10).text == "Paper jam"
    assert "Jam in tray 2" in status.status(said, 10).tip
    assert status.status(_checked(device=Device.DOWN), 10).text == "Stopped"
    message = _checked(state=State.IDLE, messages=("Bypass tray paper empty(warning)",))
    assert (status.status(message, 10).text, status.status(message, 10).color) == (
        "Needs attention",
        AMBER,
    )
    low = status.status(_checked(state=State.IDLE, supplies=(_supply("Cyan Toner", 8),)), 10)
    assert (low.text, low.color) == ("Toner low", AMBER)
    worn = _checked(state=State.IDLE, supplies=(_supply("MP Roller", 3, SupplyKind.OTHER),))
    assert status.status(worn, 10).color == GREEN  # a worn roller isn't a warning here
    waste = _supply("Waste Toner Box", 5, SupplyKind.WASTE, receptacle=True)
    assert status.status(_checked(supplies=(waste,)), 10).text == "Waste Toner Box nearly full"


def test_toner_shows_the_lowest_toner_or_ink() -> None:
    colour = _checked(supplies=(
        _supply("Black Cartridge", 64), _supply("Cyan Cartridge", 8),
        _supply("Imaging Drum", 2, SupplyKind.DRUM),
    ))  # fmt: skip
    cell = status.toner(colour, 10)
    assert (cell.text, cell.warn, cell.color) == ("Cyan 8 % · low", True, status.INKS["cyan"])
    assert "Black Cartridge: 64 %" in cell.tip
    assert not status.toner(colour, 5).warn
    mono = _checked(supplies=(_supply("Toner Cartridge 051", 83),))
    assert status.toner(mono, 10).text == "Toner 83 %"  # no colour in its name
    some = _checked(supplies=(_supply("Black Cartridge", None, some_left=True),))
    assert status.toner(some, 10).text == "Black: some left"
    assert status.toner(_checked(), 10).text == ""  # no toner reported
    assert status.toner(Checked(NOW, offline=True), 10).text == ""


# ---- in the tool ----


@pytest.fixture
def lab(tmp_path: Path) -> Path:
    hl, floor = HostList().add_group("Lab")
    hl, printer = hl.add_host("3F-LAB-01", floor.id, address="127.0.0.1")
    hl = hl.update_host(with_info(printer, PrinterInfo(brand="HP", serial="SAMPLE0001")))
    hl, _ = hl.add_host("NO-ANSWER", NO_GROUP, address="192.0.2.99")
    path = tmp_path / "lab.json"
    listfile.save(path, hl, expected=None, kind="printers")
    return path


COLOUR: Objects = {
    reading.SYS_OBJECT_ID: "1.3.6.1.4.1.11.2.3.9.1",
    f"{reading.HR_DEVICE_DESCR}.1": b"HP Color LaserJet SAMPLE-M479",
    f"{reading.HR_PRINTER_STATUS}.1": 3,
    f"{reading.HR_DEVICE_STATUS}.1": 2,
    f"{reading.SERIAL_NUMBER}.1": b"SAMPLE0099",
    f"{reading.LIFE_COUNT}.1.1": snmp.counter(21_877),
    **{
        f"{S}.{col}.1.1": v
        for col, v in ((4, 3), (5, 21), (6, b"Cyan Cartridge"), (8, 100), (9, 8))
    },
    **{
        f"{S}.{col}.1.2": v
        for col, v in ((4, 3), (5, 21), (6, b"Black Cartridge"), (8, 100), (9, 71))
    },
}


@pytest.fixture
def printers(
    qapp: QApplication, tmp_path: Path, lab: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[PrintersTool]:
    from test_printers_tool import FakeShell  # the same pretend shell as the other tests

    from capypanel.core import settings

    (tmp_path / settings.PORTABLE_MARKER).touch()
    monkeypatch.setattr(refresh, "community", lambda: "public")  # never the real vault
    tool = PrintersTool(FakeShell(settings.resolve_paths(tmp_path)))
    assert tool.open_list(lab)
    yield tool
    tool.close()
    tool.deleteLater()


def _row(tool: PrintersTool, name: str) -> QTreeWidgetItem:
    return next(r for r in tool.table._rows.values() if r.text(0) == name)


def _wait(tool: PrintersTool) -> None:
    deadline = time.monotonic() + 10
    while tool._run is not None and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert tool._run is None


def test_refresh_reads_each_printer_and_fills_status_toner_and_details(
    printers: PrintersTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running(COLOUR) as agent:
        monkeypatch.setattr(reading, "read", partial(reading.read, port=agent.port, timeout=0.2))
        printers.commands.refresh_shown.trigger()
        assert not printers.commands.refresh_shown.isEnabled()  # one Refresh at a time
        _wait(printers)
    table = printers.table
    lab = _row(printers, "3F-LAB-01")
    assert lab.text(table.STATUS) == "Toner low"  # cyan at 8 %, as the mockup shows
    assert lab.text(table.TONER) == "Cyan 8 % · low"
    assert _row(printers, "NO-ANSWER").text(table.STATUS) == "Offline"
    assert printers.commands.refresh_shown.isEnabled()
    assert printers._shell.messages[-1] == "Checked 2 printers."  # type: ignore[attr-defined]

    table.select_ids([lab.data(0, ROLE_ID)])  # its Details
    labels = [w.text() for w in printers.details.findChildren(QLabel)]
    assert "Supplies" in labels and "Cyan Cartridge" in labels and "8 % · Low" in labels
    assert "21,877" in labels or "21.877" in labels  # in the language's own digits
    [says] = [
        w for w in printers.details.findChildren(QLabel) if w.objectName() == "printerSays_serial"
    ]
    assert "SAMPLE0099" in says.text() and "Use this" in says.text()


def test_use_this_copies_the_printer_s_value_into_the_list(printers: PrintersTool) -> None:
    lab = next(h for h in printers.document.hosts.hosts if h.name == "3F-LAB-01")  # type: ignore[union-attr]
    printers.use_value(lab.id, "serial", "sample0099")
    after = printers.document.hosts.host(lab.id)  # type: ignore[union-attr]
    assert after is not None and info_of(after).serial == "SAMPLE0099"  # capitals, as typed ones


def test_the_low_level_comes_from_settings(printers: PrintersTool) -> None:
    lab = next(h for h in printers.document.hosts.hosts if h.name == "3F-LAB-01")  # type: ignore[union-attr]
    printers._checked[lab.id] = _checked(supplies=(_supply("Black Cartridge", 15),))
    printers.table.show_cells(lab.id)
    assert printers.table._rows[lab.id].text(printers.table.TONER) == "Black 15 %"
    printers.set_low_level(20)
    assert printers.prefs["low_level"] == 20
    assert printers.table._rows[lab.id].text(printers.table.TONER) == "Black 15 % · low"


def test_the_printer_s_own_words_show_as_plain_text(printers: PrintersTool) -> None:
    lab = next(h for h in printers.document.hosts.hosts if h.name == "3F-LAB-01")  # type: ignore[union-attr]
    printers._checked[lab.id] = _checked(
        messages=("<b>Tray 2</b> <img src='x'>",), supplies=(_supply("<i>Black</i>", 40),)
    )
    printers.table.show_cells(lab.id)
    tip = printers.table._rows[lab.id].toolTip(printers.table.STATUS)
    assert "&lt;b&gt;Tray 2&lt;/b&gt;" in tip and "<b>" not in tip
    assert "&lt;i&gt;Black&lt;/i&gt;" in printers.table._rows[lab.id].toolTip(printers.table.TONER)
    printers.table.select_ids([lab.id])
    shown = {w.text(): w for w in printers.details.findChildren(QLabel)}
    assert shown["<i>Black</i>"].textFormat() == Qt.TextFormat.PlainText
    assert shown["<b>Tray 2</b> <img src='x'>"].textFormat() == Qt.TextFormat.PlainText


def test_the_toner_column_shows_a_bar_when_settings_asks(printers: PrintersTool) -> None:
    lab = next(h for h in printers.document.hosts.hosts if h.name == "3F-LAB-01")  # type: ignore[union-attr]
    black = _supply("Black Cartridge", 15)
    printers._checked[lab.id] = _checked(supplies=(black,))
    printers.table.show_cells(lab.id)
    row = printers.table._rows[lab.id]
    assert row.data(printers.table.TONER, ROLE_SUPPLY) is None  # text, the default
    group = printers.settings_group()
    group.build()
    page = group.general
    page.toner_view.setCurrentIndex(page.toner_view.findData(BARS))
    assert printers.prefs[TONER_VIEW] == BARS
    assert row.data(printers.table.TONER, ROLE_SUPPLY) == black
    assert row.text(printers.table.TONER) == "Black 15 %"  # still what Copy and the Report use
    printers.table.resize(900, 300)
    printers.table.show()
    QApplication.processEvents()
    assert not printers.table.grab().isNull()  # the bar draws without an error
    # Fit columns to content leaves room for the bar and the widest %, beside each other.
    words = printers.table.fontMetrics().horizontalAdvance("100 %")
    assert printers.table.sizeHintForColumn(printers.table.TONER) >= BAR_WIDTH + words
    printers.table.hide()


def test_settings_keeps_the_community_in_the_vault_only(
    printers: PrintersTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    kept: list[tuple[str, str | None]] = []
    monkeypatch.setattr(settings_module.credstore, "save", lambda n, s: kept.append((n, s)))
    monkeypatch.setattr(settings_module.credstore, "forget", lambda n: kept.append((n, None)))
    monkeypatch.setattr(settings_module, "community_is_set", lambda: False)
    group = printers.settings_group()
    group.build()
    page = group.general
    assert "public" in page.community_row.description.text()

    def answer(dialog: QDialog) -> QDialog.DialogCode:
        dialog.field.setText("SAMPLE-community")  # type: ignore[attr-defined]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", answer)
    page.change_button.click()
    assert kept == [(refresh.COMMUNITY, "SAMPLE-community")]
    assert page.community_row.description.text().startswith("Set.")
    assert "SAMPLE-community" not in str(printers.prefs)  # never in the settings file
