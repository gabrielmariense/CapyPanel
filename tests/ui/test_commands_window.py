"""The Commands window: picking and running commands, the keyboard, search, the results side and
Add to list…. Every call to another PC is replaced: nothing here reaches the network."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QTreeWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import access, host_printers, inventory, places, services
from capypanel.core.remote.access import Reason, RemoteError
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
    for _ in range(500):
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


def test_from_a_selected_host_it_names_the_host_and_greys_add_to_list(window: CapyWindow) -> None:
    commands = _open(window, "DESK-02")
    assert commands.windowTitle() == "Commands · DESK-02"
    assert commands.host_label.text() == "<b>DESK-02</b> · 192.0.2.12"
    assert not commands.add_button.isEnabled()
    assert commands.add_button.toolTip() == ("Already in this list: in Front desks, as DESK-02")


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
    assert hidden == [True, True, True, True, False]


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
    assert not commands.add_button.isEnabled()  # nothing typed
    commands.address.setEditText("192.0.2.77")
    assert commands.windowTitle() == "Manual connection · 192.0.2.77"
    assert commands.add_button.isEnabled()

    def accept(dialog: QDialog) -> int:
        assert dialog.address.text() == "192.0.2.77"  # type: ignore[attr-defined]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(tool_module, "run_modal", accept)
    commands.add_button.click()
    assert window.hosts.where_in_list("192.0.2.77") == [("No group", "192.0.2.77")]
    assert not commands.add_button.isEnabled()
    assert "Already in this list" in commands.add_button.toolTip()


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
