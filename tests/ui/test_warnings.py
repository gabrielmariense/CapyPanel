"""Printers' warnings: which printers need attention, the strip above the table with Show and
Show all, and the red count on the Printers rail icon. Invented printers only."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.printers.reading import Device, Problem, Reading, Supply, SupplyKind
from capypanel.ui.main_window import window as window_module
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


def test_closing_asks_keeps_running_in_the_tray_and_quits_from_there(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[bool] = []
    monkeypatch.setattr(window.tray, "set_shown", shown.append)  # no real tray icon in tests
    monkeypatch.setattr(window.tray, "available", lambda: True)
    asked: list[object] = []

    def answer(choice: str | None, remember: bool):  # noqa: ANN202
        def ask(parent: object) -> tuple[str | None, bool]:
            asked.append(parent)
            return choice, remember

        return ask

    window.show()
    tool = _printers(window)
    window.close()  # nothing works on its own: no question, it just closes
    assert asked == [] and not window.isVisible()

    window.show()
    tool.set_auto_refresh(15)
    monkeypatch.setattr(window_module, "ask_closing", answer(None, False))
    window.close()  # Cancel
    assert len(asked) == 1 and window.isVisible()

    monkeypatch.setattr(window_module, "ask_closing", answer(settings.CLOSE_TRAY, True))
    window.close()  # Keep in tray, and don't ask again
    assert not window.isVisible() and window._in_tray and shown[-1] is True
    assert window.prefs[settings.CLOSE_KEY] == settings.CLOSE_TRAY
    assert not QApplication.quitOnLastWindowClosed()  # a box closing now mustn't end the app
    window.open_from_tray()
    assert window.isVisible() and not window._in_tray and QApplication.quitOnLastWindowClosed()
    window.close()  # remembered: straight to the tray
    assert len(asked) == 2 and window._in_tray

    quits: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", lambda: quits.append(True))
    window.tray.quit_requested.emit()  # the tray's Quit CapyPanel
    assert quits == [True] and shown[-1] is False and QApplication.quitOnLastWindowClosed()


def test_the_tray_menu_and_a_notification_open_what_needs_attention(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window.tray, "set_shown", lambda shown: None)
    tool = _printers(window)
    window.show_home()
    ids = {h.name: h.id for h in tool.document.hosts.hosts}  # type: ignore[union-attr]
    tool._checked[ids["PRN-2F-02"]] = OFFLINE
    tool._count_attention()
    texts = [a.text() for a in window.tray.menu.actions() if not a.isSeparator()]
    assert texts == ["&Open CapyPanel", "1 printer needs attention…", "&Quit CapyPanel"]
    assert window.tray.menu.defaultAction() is window.tray.menu.actions()[0]  # bold: the click
    assert window.tray.icon.toolTip() == "CapyPanel\n1 printer needs attention"
    window.tray.menu.actions()[2].trigger()
    assert window.shown_tool() is tool and _shown(tool) == ["PRN-2F-02"]

    tool._leave_attention()
    window.show_home()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(window.tray, "notify", lambda title, text: sent.append((title, text)))
    tool.notify_requested.emit("1 printer needs attention", "PRN-2F-02: Offline")
    assert sent == [("1 printer needs attention", "PRN-2F-02: Offline")]
    window.tray.message_clicked.emit()  # a click on the notification: Show
    assert window.shown_tool() is tool and _shown(tool) == ["PRN-2F-02"]


def test_settings_keeps_the_when_closing_choice(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    closing = dialog.general.closing
    assert closing.currentData() == settings.CLOSE_ASK  # the default
    closing.setCurrentIndex(closing.findData(settings.CLOSE_QUIT))
    assert window.prefs[settings.CLOSE_KEY] == settings.CLOSE_QUIT
    dialog.close()


def test_the_close_question_offers_tray_quit_and_cancel(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    from capypanel.ui.main_window import tray

    def click(label: str, tick: bool):  # noqa: ANN202
        def run(box: QMessageBox) -> int:
            box.checkBox().setChecked(tick)  # the box must still hold its tick box
            texts = [b.text() for b in box.buttons()]
            assert sorted(texts) == ["&Quit", "Cancel", "Keep in &tray"]
            assert box.defaultButton().text() == texts[0]
            [button] = [b for b in box.buttons() if b.text() == label]
            button.click()
            return 0

        return run

    monkeypatch.setattr(tray, "run_modal", click("Keep in &tray", True))
    assert tray.ask_closing(window) == (settings.CLOSE_TRAY, True)
    monkeypatch.setattr(tray, "run_modal", click("&Quit", False))
    assert tray.ask_closing(window) == (settings.CLOSE_QUIT, False)
    monkeypatch.setattr(tray, "run_modal", click("Cancel", True))
    assert tray.ask_closing(window) == (None, False)
