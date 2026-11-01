"""Printers' warnings: which printers need attention, the strip above the table with Show and
Show all, and the red count on the Printers rail icon. Invented printers only."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.printers.reading import Device, Problem, Reading, Supply, SupplyKind
from capypanel.ui.printers_tool import refresh, status
from capypanel.ui.printers_tool.attention import reasons_text
from capypanel.ui.printers_tool.status import Attention, Checked
from capypanel.ui.printers_tool.tool import PrintersTool

NOW = datetime(2026, 10, 30, 14, 32)
JAMMED = Checked(NOW, Reading(problems=frozenset({Problem.JAMMED})))
OFFLINE = Checked(NOW, offline=True)
LOW = Checked(NOW, Reading(supplies=(Supply("Black Cartridge", SupplyKind.TONER, 7),)))
FINE = Checked(NOW, Reading(device=Device.RUNNING))


def test_attention_is_stopped_offline_or_low() -> None:
    assert status.attention(None, 10) is None
    assert status.attention(JAMMED, 10) is Attention.STOPPED
    assert status.attention(OFFLINE, 10) is Attention.OFFLINE
    assert status.attention(LOW, 10) is Attention.LOW
    assert status.attention(LOW, 5) is None  # above the low level
    assert status.attention(FINE, 10) is None
    assert status.attention(Checked(NOW, error="bad"), 10) is None  # unreadable isn't a warning
    assert status.attention(Checked(NOW, refused="user"), 10) is None
    found = [Attention.LOW, Attention.STOPPED, Attention.OFFLINE, Attention.LOW]
    assert reasons_text(found) == "1 stopped, 1 offline, 2 low"


@pytest.fixture
def window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    monkeypatch.setattr(refresh, "community", lambda: "public")  # never the real vault
    hl, floor = HostList().add_group("Second floor")
    for name in ("PRN-2F-01", "PRN-2F-02", "PRN-1F-02", "PRN-1F-01"):
        hl, _ = hl.add_host(name, floor.id, address="192.0.2.10", tags=("mono",))
    path = tmp_path / "printers.json"
    listfile.save(path, hl, expected=None, kind="printers")
    win = CapyWindow(
        settings.resolve_paths(tmp_path), {"schema": 1, settings.START_KEY: "printers"}
    )
    printers = win.tools["printers"]
    assert isinstance(printers, PrintersTool) and printers.open_list(path)
    yield win
    win.close()


def _printers(win: CapyWindow) -> PrintersTool:
    tool = win.tools["printers"]
    assert isinstance(tool, PrintersTool)
    return tool


def _shown(tool: PrintersTool) -> list[str]:
    rows = (tool.table.topLevelItem(i) for i in range(tool.table.topLevelItemCount()))
    return sorted(r.text(0) for r in rows if r is not None)


def test_the_strip_and_the_rail_count_show_what_needs_attention(window: CapyWindow) -> None:
    tool = _printers(window)
    strip, badge = tool.attention_strip, window.rail.badges["printers"]
    assert strip.isHidden() and badge.isHidden()  # nothing checked yet
    ids = {h.name: h.id for h in tool.document.hosts.hosts}  # type: ignore[union-attr]
    for name, checked in (("PRN-2F-01", JAMMED), ("PRN-2F-02", OFFLINE), ("PRN-1F-02", LOW),
                          ("PRN-1F-01", FINE)):  # fmt: skip
        tool._checked[ids[name]] = checked
    tool._count_attention()
    assert not strip.isHidden() and not badge.isHidden() and badge.text() == "3"
    assert strip._text.text() == "<b>3 printers</b> need attention: 1 stopped, 1 offline, 1 low."
    assert (
        window.rail.buttons["printers"].toolTip() == "Printers (Ctrl+2)\n3 printers need attention"
    )

    tool.search.setText("PRN-1F")  # a search hides some: Show lists all three anyway
    tool._show_items()
    strip.button.click()
    assert _shown(tool) == ["PRN-1F-02", "PRN-2F-01", "PRN-2F-02"] and tool.search.text() == ""
    assert strip._text.text() == "Showing the <b>3 printers</b> that need attention."
    assert strip.button.text() == "Show all"
    assert len(tool.visible_items()) == 3  # F5 checks just these three

    strip.button.click()  # Show all
    assert len(_shown(tool)) == 4 and strip.button.text() == "Show"
    strip.button.click()
    tool.nav.select_group(tool.document.hosts.groups[0].id)  # type: ignore[union-attr]
    tool.nav.filter_changed.emit()  # picking a group means browsing again
    assert len(_shown(tool)) == 4

    tool._checked[ids["PRN-2F-01"]] = FINE  # the jam is cleared
    tool._count_attention()
    assert badge.text() == "2"
    for name in ("PRN-2F-02", "PRN-1F-02"):
        tool._checked[ids[name]] = FINE
    tool._count_attention()
    assert strip.isHidden() and badge.isHidden()
    assert window.rail.buttons["printers"].toolTip() == "Printers (Ctrl+2)"
