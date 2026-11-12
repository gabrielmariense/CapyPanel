"""The Commands window: picking and running commands, the keyboard, search, the results side and
Add to list…. Every call to another PC is replaced: nothing here reaches the network."""

import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import shiboken6
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QTreeWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import access, drives, host_printers, inventory, places, services
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.drives import Drive, Person
from capypanel.core.remote.host_printers import HostPrinter
from capypanel.core.remote.inventory import DiskSpace, Program
from capypanel.core.tools.connect import Target
from capypanel.ui.hosts_tool import commands_window as commands_module
from capypanel.ui.hosts_tool import tool as tool_module
from capypanel.ui.hosts_tool.command_windows import ProgramsDialog
from capypanel.ui.hosts_tool.commands_window import CommandsWindow, Shown, split_address


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, desks = HostList().add_group("Front desks")
    for name, address in [("DESK-01", "192.0.2.11"), ("DESK-02", "192.0.2.12")]:
        hl, _host = hl.add_host(name, desks.id, address=address)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    seen: list[tuple[Any, ...]] = []
    monkeypatch.setattr(access, "check_reachable", lambda host: seen.append(("reach", host)))
    monkeypatch.setattr(places, "open_folder", lambda path: seen.append(("folder", path)))
    monkeypatch.setattr(places, "require_folder", lambda path: None)  # no file sharing here
    return seen


def _open(win: CapyWindow, name: str | None) -> CommandsWindow:
    if name is None:
        win.hosts.manual_connect()
    else:
        assert win.hosts.document is not None
        host = next(h for h in win.hosts.document.hosts.hosts if h.name == name)
        win.hosts.table.select_ids([host.id])
        win.hosts.open_commands(win.hosts.selected_target())
    commands = win.hosts._commands_window  # pyright: ignore[reportPrivateUsage]
    assert isinstance(commands, CommandsWindow)
    return commands


def _settle(win: CapyWindow) -> None:
    deadline = time.monotonic() + 10  # a deadline, not a count: threads can be slow
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not win.hosts.runner.busy():
            QApplication.processEvents()
            return
    pytest.fail("a host command never finished")


def _key(widget: Any, key: Qt.Key, text: str = "") -> None:
    press = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text)
    QApplication.sendEvent(widget, press)


def test_a_port_after_the_address_is_the_connection_s_port() -> None:
    assert split_address("PC-01") == Target("PC-01")
    assert split_address(" 192.0.2.7:5901 ") == Target("192.0.2.7", 5901)
    assert split_address("fe80::1") == Target("fe80::1")  # IPv6 keeps its colons


def test_from_a_selected_host_it_names_the_host_and_hides_add_to_host_list(
    window: CapyWindow,
) -> None:
    commands = _open(window, "DESK-02")
    assert commands.windowTitle() == "Commands · DESK-02"
    assert commands.address.currentText() == "DESK-02 · 192.0.2.12"
    assert commands.add_button.isHidden()  # already in the list: nothing to add


def test_the_host_can_be_picked_from_the_list_typed_or_stepped_with_the_arrows(
    window: CapyWindow,
) -> None:
    commands = _open(window, "DESK-02")
    shown = [commands.address.itemText(i) for i in range(commands.address.count())]
    assert shown[:2] == ["DESK-01 · 192.0.2.11", "DESK-02 · 192.0.2.12"]  # the panel's order
    _key(commands.address, Qt.Key.Key_Up)  # host by host
    target = commands.target()
    assert target is not None and target.name == "DESK-01" and not target.key.startswith("@")
    assert commands.windowTitle() == "Commands · DESK-01"
    commands.address.setEditText("desk-02")  # a list host's name, typed: that host
    target = commands.target()
    assert target is not None and target.address == "192.0.2.12"
    assert not target.key.startswith("@")
    commands.address.setEditText("192.0.2.11")  # or its address
    assert (target := commands.target()) is not None and target.name == "DESK-01"
    commands.address.setEditText("192.0.2.99")  # not in the list: a manual connection
    target = commands.target()
    assert target is not None and target.key == "@192.0.2.99"
    assert commands.windowTitle() == "Manual connection · 192.0.2.99"
    assert not commands.add_button.isHidden()


def test_typed_addresses_come_under_a_recent_heading_the_arrows_skip(window: CapyWindow) -> None:
    window.hosts.prefs["recent_addresses"] = ["198.51.100.40"]
    commands = _open(window, "DESK-02")
    shown = [commands.address.itemText(i) for i in range(commands.address.count())]
    assert shown == ["DESK-01 · 192.0.2.11", "DESK-02 · 192.0.2.12", "RECENT", "198.51.100.40"]
    heading = commands.address.model().index(2, 0)
    assert not commands.address.model().flags(heading) & Qt.ItemFlag.ItemIsEnabled
    _key(commands.address, Qt.Key.Key_Down)  # from DESK-02, past the heading
    assert commands.address.currentText() == "198.51.100.40"


def test_it_is_a_window_of_its_own_that_closes_when_capypanel_quits(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    assert commands.parent() is None  # not owned: the main window can come in front of it
    window.show()
    commands.show()
    window.close()
    QApplication.processEvents()
    assert not shiboken6.isValid(commands) or not commands.isVisible()


def test_the_picked_row_grows_and_the_arrows_move(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    first, second = commands.rows[0], commands.rows[1]
    assert commands.picked() is first.command and first.run.isVisibleTo(commands)
    assert not second.run.isVisibleTo(commands)
    _key(commands.search, Qt.Key.Key_Down)
    assert commands.picked() is second.command
    assert second.run.isDefault() and not first.run.isDefault()  # Enter runs the picked one


def test_typing_searches_by_name_and_description(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    commands.search.setText("spooler")
    shown = [r.command.id for r in commands.rows if not r.isHidden()]
    assert shown == ["spooler"]
    assert commands.picked() is not None and commands.picked().id in shown  # type: ignore[union-attr]
    hidden = [commands.groups.item(i).isHidden() for i in range(commands.groups.count())]
    assert hidden == [True, True, True, True, False, True]  # only Printers


def test_a_command_set_apart_has_a_small_gap_above_it(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    commands.show()
    QApplication.processEvents()
    row = {r.command.id: r for r in commands.rows}

    def gap(above: str, below: str) -> int:
        return row[below].y() - (row[above].y() + row[above].height())

    # Installed programs and Cancel the pending restart: where the menus draw a line.
    assert gap("facts", "programs") == gap("status", "users") + commands_module.APART
    assert gap("shut-down", "cancel-restart") == gap("restart", "shut-down") + commands_module.APART
    commands.close()


def test_run_opens_and_the_answer_stays_on_the_right(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "c-share")
    commands.pick(row)
    row.run.click()
    _settle(window)
    assert calls == [("reach", "192.0.2.12"), ("folder", "\\\\192.0.2.12\\C$")]

    def unreachable(_host: str) -> None:
        raise RemoteError(Reason.NOT_ADMIN)

    monkeypatch.setattr(access, "check_reachable", unreachable)
    startup = next(r for r in commands.rows if r.command.id == "startup")
    commands.pick(startup)
    startup.run.click()
    _settle(window)
    outcome = _shown(commands).outcome
    assert outcome is not None and "access denied" in outcome.text and outcome.retry is not None
    commands.pick(row)  # back to C$: nothing failed there
    assert _shown(commands).outcome is None  # opening shows in the status bar


def _shown(commands: CommandsWindow) -> Shown:
    shown = commands.results._shown  # pyright: ignore[reportPrivateUsage]
    assert shown is not None and isinstance(shown[0], Shown)
    return shown[0]


def test_pc_facts_show_on_the_right(window: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "disk_space", lambda *_a: DiskSpace(10 * 1024**3, 100 * 1024**3))
    monkeypatch.setattr(inventory, "last_restart", lambda *_a: datetime.now(UTC))

    def refused(*_a: Any) -> None:
        raise RemoteError(Reason.NOT_ADMIN)

    monkeypatch.setattr(inventory, "pc_facts", refused)
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "facts")
    commands.pick(row)
    row.run.click()
    _settle(window)
    assert commands.results.shown_value("space") == "10.0 GB of 100 GB"


def test_a_typed_address_can_be_added_to_the_list(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = _open(window, None)
    assert commands.windowTitle() == "Manual connection"
    assert commands.add_button.isHidden()  # nothing typed
    commands.address.setEditText("192.0.2.77")
    assert commands.windowTitle() == "Manual connection · 192.0.2.77"
    assert not commands.add_button.isHidden()

    def accept(dialog: QDialog) -> int:
        assert dialog.address.text() == "192.0.2.77"  # type: ignore[attr-defined]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", accept)
    commands.add_button.click()
    assert window.hosts.where_in_list("192.0.2.77") == [("No group", "192.0.2.77")]
    assert commands.add_button.isHidden()  # in the list now


def test_typing_anywhere_goes_to_the_search(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    commands.list.setFocus()
    _key(commands, Qt.Key.Key_P, "p")
    assert commands.search.text() == "p"


def test_printers_show_as_a_table_with_the_spooler_state(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = [
        HostPrinter("Front", "SAMPLE PCL6", "192.0.2.52", "", 3, ("paper jam",)),
        HostPrinter("PDF", "Microsoft Print To PDF", "PORTPROMPT:", "", 0, ()),
    ]
    monkeypatch.setattr(host_printers, "list_printers", lambda *_a: found)
    monkeypatch.setattr(services, "service_state", lambda *_a: "running")
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "printers")
    commands.pick(row)
    row.run.click()
    _settle(window)
    listed = _shown(commands).listed
    assert listed is not None and not listed.reading and listed.spooler == "running"
    tables = commands.results.findChildren(QTreeWidget)
    assert len(tables) == 1 and tables[0].topLevelItemCount() == 2
    first = tables[0].topLevelItem(0)
    assert first is not None and first.text(1) == "Paper jam"


def test_one_persons_mapped_drives_name_them_in_the_heading_not_on_every_row(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_path = r"\\FS01\Projects\A long folder name\Another one\Ward 3"
    ana = Person("ana", "EXAMPLE", (Drive("H:", r"\\FS01\Home\ana"), Drive("S:", long_path)))
    monkeypatch.setattr(drives, "saved_drives", lambda *_a: [ana])
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "drives")
    commands.pick(row)
    row.run.click()
    _settle(window)
    table = commands.results.findChildren(QTreeWidget)[0]
    assert table.isColumnHidden(0) and not table.isColumnHidden(2)  # no Person column
    headings = [w.text() for w in commands.results.findChildren(QLabel)
                if w.objectName() == "detailsSection"]  # fmt: skip
    assert any(h.startswith("Mapped drives · ana · ") for h in headings)
    second = table.topLevelItem(1)
    assert second is not None and second.toolTip(2) == long_path  # whole, when it's cut
    assert table.textElideMode() == Qt.TextElideMode.ElideMiddle  # the share's end stays
    rui = Person("rui", "EXAMPLE", (Drive("H:", r"\\FS01\Home\rui"),))
    monkeypatch.setattr(drives, "saved_drives", lambda *_a: [ana, rui])
    row.run.click()  # two people: the column says whose each drive is
    _settle(window)
    assert not commands.results.findChildren(QTreeWidget)[0].isColumnHidden(0)


def test_programs_right_click_opens_them_in_their_own_window(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    programs = [Program("7-Zip", "24.08", "Igor Pavlov", None)]
    monkeypatch.setattr(inventory, "installed_programs", lambda *_a: programs)
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "programs")
    commands.pick(row)
    row.run.click()
    _settle(window)
    opened: list[QDialog] = []

    def record(dialog: QDialog) -> int:
        opened.append(dialog)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(commands_module, "run_modal", record)
    picked: list[str] = []

    class Recorded(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            picked.extend(a.text() for a in self.actions() if a.text())
            next(a for a in self.actions() if a.text().startswith("&Open")).trigger()

    monkeypatch.setattr(commands_module, "QMenu", Recorded)
    commands._list_menu("programs", 0, QPoint(0, 0))  # pyright: ignore[reportPrivateUsage]
    assert picked == ["&Copy row", "Copy &list", "&Export CSV…", "&Open in its own window…"]
    assert len(opened) == 1 and isinstance(opened[0], ProgramsDialog)
    assert opened[0].table.topLevelItemCount() == 1  # the list read here, not read again


def test_an_answer_after_the_window_closed_is_dropped(window: CapyWindow, calls: list[Any]) -> None:
    commands = _open(window, "DESK-02")
    row = next(r for r in commands.rows if r.command.id == "c-share")
    commands.pick(row)
    row.run.click()
    commands.close()  # deleted on close, while the command is still on its way
    _settle(window)  # its answer comes back to nothing, quietly
    assert ("folder", "\\\\192.0.2.12\\C$") in calls


def test_the_window_can_be_made_any_size_and_reopens_as_it_was_left(window: CapyWindow) -> None:
    commands = _open(window, "DESK-01")
    QApplication.processEvents()
    least = commands.minimumWidth()  # what its parts need; the test font is a wide one
    opens = (max(commands_module.SIZE[0], least), commands_module.SIZE[1])
    assert (commands.width(), commands.height()) == opens  # the first time
    commands.resize(least, 400)  # as small as it goes: the results keep what they need
    QApplication.processEvents()
    assert (commands.width(), commands.height()) == (least, 400)
    results, listed = commands.results.width(), commands.list.width()
    assert results >= commands_module.RESULTS_WIDTH
    commands.resize(least + 800, 900)  # wider, the commands and the results both gain
    QApplication.processEvents()
    assert commands.results.width() > results and commands.list.width() > listed
    commands.resize(least + 180, 800)
    commands.close()
    QApplication.processEvents()
    assert window.hosts.prefs[commands_module.SIZE_KEY] == [least + 180, 800]
    again = _open(window, "DESK-02")
    assert again is not commands and (again.width(), again.height()) == (least + 180, 800)
    again.resize(least + 200, 700)
    again.reject()  # Esc keeps the size too
    assert window.hosts.prefs[commands_module.SIZE_KEY] == [least + 200, 700]
    QApplication.processEvents()
    window.hosts.prefs[commands_module.SIZE_KEY] = "wide"  # a settings file edited by hand
    typed = _open(window, None)
    QApplication.processEvents()
    assert (typed.width(), typed.height()) == opens
