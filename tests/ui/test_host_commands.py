"""The host commands: menus, the Details panel's buttons, the small windows and the answers in the
result strip. Every call to another PC is replaced: nothing here reaches the network."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from capypanel.core import settings
from capypanel.core.hosts import commands as host_commands
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import access, host_printers, inventory, places, power, sessions
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.host_printers import HostPrinter
from capypanel.core.remote.inventory import DiskSpace, PcFacts, Program
from capypanel.core.remote.sessions import Session
from capypanel.ui.hosts_tool import command_windows, runner
from capypanel.ui.hosts_tool.command_windows import (
    MessageDialog,
    OpenPathDialog,
    PowerDialog,
    PrintersDialog,
    ProgramsDialog,
)
from capypanel.ui.hosts_tool.runner import HostTarget
from capypanel.ui.icons import TABLER_DIR
from capypanel.ui.menus import label

ANA = Session("ana", "CORP", "console", "active", None, session_id=1)
BRUNO = Session("bruno", "CORP", "rdp", "disconnected", None, client="LAB-01", session_id=2)
CAIO = Session("caio", "CORP", "rdp", "active", None, client="LAB-02", session_id=3)


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, office = HostList().add_group("Office")
    for name, address in [("PC-1", "192.0.2.1"), ("PC-2", "192.0.2.2"), ("Desk 4", "")]:
        hl, _host = hl.add_host(name, office.id, address=address)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    """Every call to another PC, recorded; each one works unless a test says otherwise."""
    seen: list[tuple[Any, ...]] = []

    def record(name: str, value: Any = None) -> Callable[..., Any]:
        def call(*args: Any, **_kwargs: Any) -> Any:
            seen.append((name, *args))
            return value

        return call

    monkeypatch.setattr(access, "check_reachable", record("reach"))
    monkeypatch.setattr(places, "open_folder", record("folder"))
    monkeypatch.setattr(places, "require_folder", lambda path: None)  # no file sharing here
    monkeypatch.setattr(places, "open_console", record("console"))
    monkeypatch.setattr(sessions, "read_sessions", record("sessions", [ANA, BRUNO]))
    monkeypatch.setattr(sessions, "log_off", record("log-off"))
    monkeypatch.setattr(sessions, "disconnect", record("disconnect"))
    monkeypatch.setattr(sessions, "send_message", record("message"))
    monkeypatch.setattr(power, "restart", record("restart"))
    monkeypatch.setattr(power, "shut_down", record("shut-down"))
    monkeypatch.setattr(power, "cancel", record("cancel", True))
    return seen


def _select(win: CapyWindow, name: str) -> HostTarget:
    assert win.hosts.document is not None
    host = next(h for h in win.hosts.document.hosts.hosts if h.name == name)
    win.hosts.table.select_ids([host.id])
    target = win.hosts.selected_target()
    assert target is not None
    return target


def _settle(win: CapyWindow) -> None:
    deadline = time.monotonic() + 10  # a deadline, not a count: threads can be slow
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not win.hosts.runner.busy():
            QApplication.processEvents()
            return
    pytest.fail("a host command never finished")


def _answer(monkeypatch: pytest.MonkeyPatch, answer: Callable[[QDialog], int]) -> list[QDialog]:
    """Windows the commands open are answered by `answer` instead of waiting for a click."""
    opened: list[QDialog] = []

    def run(dialog: QDialog) -> int:
        opened.append(dialog)
        return answer(dialog)

    monkeypatch.setattr(runner, "run_modal", run)
    monkeypatch.setattr(command_windows, "run_modal", run)
    return opened


ACCEPT = QDialog.DialogCode.Accepted


def test_every_command_icon_is_bundled() -> None:
    for command in host_commands.COMMANDS:
        assert (TABLER_DIR / f"{command.icon}.svg").is_file(), command.icon


def test_the_host_menu_has_a_submenu_per_group_greyed_for_several_hosts(
    window: CapyWindow,
) -> None:
    _select(window, "PC-1")
    menu = QMenu()
    window.hosts._add_command_menus(menu)
    groups = {a.text(): a.menu() for a in menu.actions()}
    assert list(groups) == [
        "Check", "Folders", "Admin tools", "Users", "Printers", "Power",
    ]  # fmt: skip
    users = groups["Users"]
    assert isinstance(users, QMenu)
    assert [a.text() for a in users.actions()] == [
        "Send a message…", "", "Mapped drives",
    ]  # log off: on the person; the drives set apart  # fmt: skip

    def names(group: str) -> list[str]:
        submenu = groups[group]
        assert isinstance(submenu, QMenu)
        return [label(a) if a.text() else "—" for a in submenu.actions()]

    # Installed programs is apart: a long table, not part of Refresh host; Power comes last.
    assert names("Check") == [
        "Refresh host", "Status", "Logged-on users", "PC facts", "—", "Installed programs",
    ]  # fmt: skip
    assert names("Folders") == ["C$ share", "User's folder", "Startup folder", "Open a path…"]
    assert names("Admin tools") == ["Computer Management", "Event Viewer", "Services"]
    assert names("Power") == ["Restart…", "Shut down…", "—", "Cancel the pending restart"]
    window.hosts.table.select_ids([window.hosts.table.selected_ids()[0], *_ids(window, "PC-2")])
    menu = QMenu()
    window.hosts._add_command_menus(menu)
    assert not any(a.isEnabled() for a in menu.actions() if not a.isSeparator())


def _ids(win: CapyWindow, *names: str) -> list[str]:
    assert win.hosts.document is not None
    return [h.id for h in win.hosts.document.hosts.hosts if h.name in names]


def test_details_shows_a_grid_of_worded_buttons(window: CapyWindow) -> None:
    _select(window, "PC-1")
    buttons = window.hosts.details.buttons
    assert list(buttons) == [  # the fixed row, then this admin's quick commands
        "refresh", "commands", "users", "power",
        "quick:c-share", "quick:user-folder", "quick:computer-management", "quick:message",
    ]  # fmt: skip
    words = [b.text() for b in buttons.values()]
    assert words == ["Refresh", "Commands", "Users ▾", "Power ▾", "C$", "Folder", "Manage",
                     "Message"]  # fmt: skip
    assert len({b.size().toTuple() for b in buttons.values()}) == 1  # every button the same size
    assert buttons["quick:computer-management"].toolTip() == "Computer Management"  # the full name
    assert not buttons["users"].isEnabled()  # nobody checked yet
    target = window.hosts.selected_target()
    assert target is not None
    window.hosts.keep_users(target.key, (ANA,), None)
    buttons = window.hosts.details.buttons
    assert buttons["users"].isEnabled()
    assert buttons["quick:user-folder"].toolTip() == "User's folder (ana)"
    window.hosts.keep_users(target.key, (), None)  # a check just found nobody
    folder = window.hosts.details.buttons["quick:user-folder"]
    assert not folder.isEnabled() and folder.toolTip() == "User's folder (nobody signed in)"


def test_details_buttons_follow_the_admin_s_quick_commands(window: CapyWindow) -> None:
    _select(window, "PC-1")
    window.hosts.prefs["quick_commands"] = ["spooler", "status"]
    window.hosts._selection_changed()
    buttons = window.hosts.details.buttons
    assert list(buttons)[4:] == ["quick:spooler", "quick:status"]
    assert buttons["quick:spooler"].property("risky") is True  # amber there too
    window.hosts.prefs["quick_commands"] = []  # none picked: only the fixed row
    window.hosts._selection_changed()
    assert list(window.hosts.details.buttons) == ["refresh", "commands", "users", "power"]
    assert window.hosts.details.minimumWidth() >= window.hosts.details.minimum_width() > 300


def test_details_commands_button_opens_the_commands_window(window: CapyWindow) -> None:
    target = _select(window, "PC-1")
    window.hosts.details.buttons["commands"].click()
    commands = window.hosts._commands_window
    assert commands is not None and commands.target() == target  # type: ignore[attr-defined]
    commands.close()


def test_c_share_opens_once_the_pc_answers(window: CapyWindow, calls: list[Any]) -> None:
    _select(window, "PC-1")
    window.hosts.details.buttons["quick:c-share"].click()
    _settle(window)
    assert calls == [("reach", "192.0.2.1"), ("folder", "\\\\192.0.2.1\\C$")]


def test_a_pc_that_doesnt_answer_says_so_in_red(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unreachable(_host: str) -> None:
        raise RemoteError(Reason.UNREACHABLE)

    monkeypatch.setattr(access, "check_reachable", unreachable)
    _select(window, "PC-1")
    window.hosts.host_actions["startup"].trigger()
    _settle(window)
    strip = window.hosts.result_strip
    assert strip.isVisibleTo(window.hosts) and strip.property("failed") is True
    assert "Couldn't open Startup folder on PC-1: it didn't answer." in strip.text()
    assert not strip.retry_button.isVisibleTo(window.hosts)  # another account won't help
    assert ("folder",) not in [c[:1] for c in calls]


def test_log_off_asks_then_says_it_worked(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answer(monkeypatch, lambda _dialog: ACCEPT)
    target = _select(window, "PC-1")
    window.hosts.runner.run("log-off", target, window.hosts.show_outcome, session=BRUNO)
    _settle(window)
    assert "Log off bruno on PC-1?" in asked[0].heading.text()  # type: ignore[attr-defined]
    assert ("log-off", "192.0.2.1", 2, None) in calls
    strip = window.hosts.result_strip
    assert strip.property("failed") is False
    assert strip.text() == "Logged off <b>bruno</b> on PC-1."


def test_cancel_on_the_question_does_nothing(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer(monkeypatch, lambda _dialog: QDialog.DialogCode.Rejected)
    target = _select(window, "PC-1")
    window.hosts.runner.run("disconnect", target, window.hosts.show_outcome, session=BRUNO)
    _settle(window)
    assert not any(c[0] == "disconnect" for c in calls)


def test_access_denied_offers_another_account_and_runs_again(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    tries: list[Any] = []

    def log_off(host: str, session_id: int, account: Any) -> None:
        tries.append(account)
        if account is None:
            raise RemoteError(Reason.NOT_ADMIN, 5)

    monkeypatch.setattr(sessions, "log_off", log_off)

    def answer(dialog: QDialog) -> int:
        if hasattr(dialog, "user"):  # the account window
            dialog.user.setText("CORP\\admin")  # type: ignore[attr-defined]
            dialog.password.setText("secret")  # type: ignore[attr-defined]
        return ACCEPT

    _answer(monkeypatch, answer)
    target = _select(window, "PC-1")
    window.hosts.runner.run("log-off", target, window.hosts.show_outcome, session=ANA)
    _settle(window)
    strip = window.hosts.result_strip
    assert "access denied" in strip.text() and strip.retry_button.isVisibleTo(window.hosts)
    strip.retry_button.click()
    _settle(window)
    assert [a.user if a else None for a in tries] == [None, "CORP\\admin"]
    assert strip.text() == "Logged off <b>ana</b> on PC-1."


def test_send_a_message_goes_to_everyone_active_but_the_sender(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner.getpass, "getuser", lambda: "caio")
    monkeypatch.setattr(sessions, "read_sessions", lambda *_a: [ANA, BRUNO, CAIO])

    def answer(dialog: QDialog) -> int:
        assert isinstance(dialog, MessageDialog)
        dialog.message.setPlainText("Restarting at noon")
        return ACCEPT

    _answer(monkeypatch, answer)
    _select(window, "PC-1")
    window.hosts.host_actions["message"].trigger()
    _settle(window)
    sent = [c for c in calls if c[0] == "message"]
    assert [c[2] for c in sent] == [1]  # ana only: bruno is disconnected, caio is the sender
    assert sent[0][4] == "Restarting at noon"
    assert window.hosts.result_strip.text() == "Message sent to <b>ana</b> on PC-1."


def test_restart_waits_shows_in_status_and_details_and_cancels(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def answer(dialog: QDialog) -> int:
        assert isinstance(dialog, PowerDialog)
        assert dialog.delay() == 0  # Restart's default: now
        dialog.when.setCurrentIndex(dialog.when.findData(5 * 60))
        return ACCEPT

    _answer(monkeypatch, answer)
    target = _select(window, "PC-1")
    window.hosts.host_actions["restart"].trigger()
    _settle(window)
    restart = next(c for c in calls if c[0] == "restart")
    assert restart[1:3] == ("192.0.2.1", 300) and "5 minutes" in restart[3]
    row = window.hosts.table._rows[target.key]
    assert row.text(window.hosts.table.STATUS).startswith("Restart at ")
    assert window.hosts.pending_power(target.key) is not None
    assert window.hosts.host_actions["cancel-restart"].isEnabled()
    window.hosts.details.cancel_pending.emit()
    _settle(window)
    assert ("cancel", "192.0.2.1", None) in calls
    assert window.hosts.pending_power(target.key) is None
    assert "is cancelled" in window.hosts.result_strip.text()


def test_restart_now_has_no_message(qapp: QApplication) -> None:
    dialog = PowerDialog(None, "PC-1", [ANA], restart=True)
    assert dialog.delay() == 0 and dialog.message() == ""  # Now, without picking it
    assert PowerDialog(None, "PC-1", [ANA], restart=False).delay() == 0  # Shut down too
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.show()
    assert dialog.focusWidget() is dialog.when  # arrows pick at once
    assert dialog.cancel.isDefault()  # Enter in When cancels
    QTest.keyClick(dialog.when, Qt.Key.Key_Return)  # Enter in When: Cancel
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.show()
    dialog.when.setFocus()
    dialog.focusNextChild()  # Tab: no message to type for Now, so straight to the action
    assert dialog.focusWidget() is dialog.action
    QTest.keyClick(dialog.action, Qt.Key.Key_Return)  # Enter there runs it
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not dialog.box.isEnabled()
    assert dialog.action.text() == "&Restart now"
    assert "<b>ana</b>" in dialog.text.text()
    dialog.when.setCurrentIndex(1)
    assert dialog.message() == "This PC restarts in 1 minute. Please save your work."


def test_a_restarted_pc_that_answers_again_is_announced(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _select(window, "PC-1")
    now = datetime.now(UTC)
    window.hosts.power_started(target, restart=True, at=now - timedelta(seconds=1), asked=now,
                               told=[])  # fmt: skip
    answers = [RemoteError(Reason.UNREACHABLE), None]

    def reach(_host: str) -> None:
        if (error := answers.pop(0)) is not None:
            raise error

    monkeypatch.setattr(access, "check_reachable", reach)
    notes: list[tuple[str, str]] = []
    window.hosts.notify_requested.connect(lambda title, text: notes.append((title, text)))
    window.hosts._watch_power()
    _settle(window)
    assert not notes  # it went away
    window.hosts._watch_power()
    _settle(window)
    assert notes and notes[0][0] == "PC-1 is back online"
    assert window.hosts.pending_power(target.key) is None


def test_pc_facts_read_quick_ones_first_then_the_rest(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    gb = 1024**3
    monkeypatch.setattr(inventory, "disk_space", lambda *_a: DiskSpace(int(21.3 * gb), 222 * gb))
    monkeypatch.setattr(inventory, "last_restart", lambda *_a: datetime.now(UTC))
    monkeypatch.setattr(
        inventory,
        "pc_facts",
        lambda *_a: PcFacts(
            "Windows 11 Pro",
            "25H2",
            "26200.9168",
            "SAMPLE Inc.",
            "Desk 3000",
            "SAMPLE7Q2X",
            "1.2.3",
            16 * gb,
        ),  # fmt: skip
    )
    target = _select(window, "PC-1")
    window.hosts.runner.read_facts(target)
    _settle(window)
    details = window.hosts.details
    assert details.shown_value("space") == "21.3 GB of 222 GB"
    assert details.shown_value("windows") == "Windows 11 Pro 25H2 · 26200.9168"
    assert details.shown_value("model") == "SAMPLE Desk 3000"
    assert details.shown_value("memory") == "16 GB"
    assert details.shown_value("restarted").startswith("Today ")


def test_pc_facts_say_which_part_needs_an_admin(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inventory, "disk_space", lambda *_a: DiskSpace(1, 2))
    monkeypatch.setattr(inventory, "last_restart", lambda *_a: datetime.now(UTC))

    def refused(*_a: Any) -> None:
        raise RemoteError(Reason.NOT_ADMIN)

    monkeypatch.setattr(inventory, "pc_facts", refused)
    target = _select(window, "PC-1")
    window.hosts.runner.read_facts(target)
    _settle(window)
    facts = window.hosts.facts_of(target.key)
    assert facts is not None and not facts.reading and facts.space == DiskSpace(1, 2)
    assert isinstance(facts.pc_error, RemoteError)
    details = window.hosts.details
    assert details.shown_value("windows") == ""  # a warning instead of a value
    # The warning copies on a click, as a value does, so it can go in a report.
    assert details.shown_value("windows_error") == "No access: needs an admin account on this PC"


def test_pc_facts_show_the_rows_read_when_one_part_of_wmi_is_missing(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_found = RemoteError(Reason.OTHER, 0x80041002)
    monkeypatch.setattr(inventory, "disk_space", lambda *_a: DiskSpace(1, 2))
    monkeypatch.setattr(inventory, "last_restart", lambda *_a: datetime.now(UTC))
    monkeypatch.setattr(
        inventory,
        "pc_facts",
        lambda *_a: PcFacts("Windows 11 Pro", "25H2", "26200.9168", "SAMPLE", "Desk 3000", "", "",
                            8 * 1024**3, unread={"serial": not_found, "bios": not_found}),
    )  # fmt: skip
    target = _select(window, "PC-1")
    window.hosts.runner.read_facts(target)
    _settle(window)
    details = window.hosts.details
    assert details.shown_value("windows") == "Windows 11 Pro 25H2 · 26200.9168"
    assert details.shown_value("model") == "SAMPLE Desk 3000"
    assert details.shown_value("serial") == details.shown_value("bios") == ""
    assert details.shown_value("serial_error") == "Couldn't read: Windows error 0x80041002"


def test_open_a_path_shows_where_it_goes_and_keeps_it(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def answer(dialog: QDialog) -> int:
        assert isinstance(dialog, OpenPathDialog)
        dialog.path.setEditText('"D:\\Logs\\App"')
        assert dialog.opens.text() == "Opens \\\\192.0.2.1\\D$\\Logs\\App".replace(
            "192.0.2.1", "PC-1"
        )
        return ACCEPT

    _answer(monkeypatch, answer)
    _select(window, "PC-1")
    window.hosts.host_actions["path"].trigger()
    _settle(window)
    assert ("folder", "\\\\192.0.2.1\\D$\\Logs\\App") in calls
    assert window.hosts.recent_paths() == ['"D:\\Logs\\App"']


def test_printers_on_this_pc_lists_them_and_clears_a_queue(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = [
        HostPrinter("Front", "SAMPLE PCL6", "192.0.2.52", "", 3, ("paper jam",)),
        HostPrinter("PDF", "Microsoft Print To PDF", "PORTPROMPT:", "", 0, ()),
    ]
    monkeypatch.setattr(host_printers, "list_printers", lambda *_a: found)
    monkeypatch.setattr(host_printers, "clear_queue", lambda *a: calls.append(("clear", *a)))
    _answer(monkeypatch, lambda _dialog: ACCEPT)
    target = _select(window, "PC-1")
    dialog = PrintersDialog(None, window.hosts.runner, target, window.hosts.show_outcome)
    _settle(window)
    assert dialog.table.topLevelItemCount() == 2
    first = dialog.table.topLevelItem(0)
    assert first is not None and first.text(3) == "Paper jam"
    assert not dialog.clear_button.isEnabled()
    dialog.table.setCurrentItem(first)
    assert dialog.clear_button.isEnabled()
    dialog.clear_button.click()
    _settle(window)
    assert ("clear", "192.0.2.1", "Front", None) in calls
    assert "Cleared the queue of <b>Front</b>" in window.hosts.result_strip.text()


def test_installed_programs_search_and_count(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    programs = [
        Program("7-Zip", "24.08", "Igor Pavlov", date(2026, 8, 20)),
        Program("SAMPLE Viewer", "1.0", "SAMPLE Ltd", None),
    ]
    monkeypatch.setattr(inventory, "installed_programs", lambda *_a: programs)
    target = _select(window, "PC-1")
    dialog = ProgramsDialog(None, window.hosts.runner, target, window.hosts.csv_folder)
    _settle(window)
    assert dialog.summary.text().startswith("2 programs on PC-1 · read at ")
    dialog.search.setText("sample")
    assert [r.text(0) for r in dialog._rows()] == ["SAMPLE Viewer"]
    assert dialog.summary.text().startswith("1 of 2 programs on PC-1")


def test_a_list_that_cant_be_read_says_why_and_logs_it(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refused(*_a: object) -> None:
        raise RemoteError(Reason.REJECTED, 5)

    monkeypatch.setattr(inventory, "installed_programs", refused)
    target = _select(window, "PC-1")
    dialog = ProgramsDialog(None, window.hosts.runner, target, window.hosts.csv_folder)
    _settle(window)
    assert dialog.summary.text().startswith("Couldn't read PC-1: ")
    assert "Installed programs on PC-1 failed: RemoteError" in caplog.text


def test_commands_menu_on_the_toolbar_lists_the_groups(window: CapyWindow) -> None:
    _select(window, "PC-1")
    menu = window.hosts.toolbar.commands_menu
    menu.aboutToShow.emit()
    assert [a.text() for a in menu.actions()] == [
        "Check", "Folders", "Admin tools", "Users", "Printers", "Power", "", "&All commands…",
    ]  # fmt: skip


def test_a_click_on_commands_opens_the_window_for_the_selected_host(window: CapyWindow) -> None:
    from capypanel.ui.hosts_tool.commands_window import CommandsWindow

    target = _select(window, "PC-1")
    window.hosts.toolbar.commands_button.click()
    commands = window.hosts._commands_window  # pyright: ignore[reportPrivateUsage]
    assert isinstance(commands, CommandsWindow) and commands.target() == target
    window.hosts.table.clearSelection()
    window.hosts.toolbar.commands_button.click()  # no host: an address typed in it
    commands = window.hosts._commands_window  # pyright: ignore[reportPrivateUsage]
    assert isinstance(commands, CommandsWindow) and commands.target() is None
    commands.close()


def test_a_path_to_a_file_is_never_opened(
    window: CapyWindow, calls: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def not_a_folder(path: str) -> None:
        raise NotADirectoryError(path)

    monkeypatch.setattr(places, "require_folder", not_a_folder)
    _answer(
        monkeypatch,
        lambda dialog: (
            dialog.path.setEditText("C:\\Tools\\run.bat"),  # type: ignore[attr-defined]
            ACCEPT,
        )[1],
    )
    _select(window, "PC-1")
    window.hosts.host_actions["path"].trigger()
    _settle(window)
    assert not any(c[0] == "folder" for c in calls)  # a file would have run on this PC
    assert "there's no folder there." in window.hosts.result_strip.text()


def _host_menu(window: CapyWindow) -> list[str]:
    menu = QMenu()
    window.hosts.fill_item_menu(menu, window.hosts.selected_items())
    return [label(a) for a in menu.actions() if a.text()]


def test_the_host_menu_shows_the_first_four_quick_commands(window: CapyWindow) -> None:
    _select(window, "PC-1")
    window.hosts.prefs["quick_commands"] = [
        "services", "status", "c-share", "path", "event-viewer", "restart",
    ]  # fmt: skip
    assert window.hosts.quick_commands() == (
        "services", "status", "c-share", "path", "event-viewer",
    )  # fmt: skip
    texts = _host_menu(window)
    assert texts[2:7] == ["Services", "Status", "C$ share", "Open a path…", "&All commands…"]
    window.hosts.prefs["quick_commands"] = []  # none picked: the block isn't there
    assert _host_menu(window)[:3] == ["&Connect", "&Refresh host", "&All commands…"]


def test_commands_for_a_person_say_who_or_that_nobody_is_signed_in(window: CapyWindow) -> None:
    _select(window, "PC-1")
    target = window.hosts.selected_target()
    assert target is not None
    folder, message = window.hosts.host_actions["user-folder"], window.hosts.host_actions["message"]
    window.hosts._update_host_actions()  # before any check: plain, and usable
    assert (folder.text(), folder.isEnabled()) == ("User's folder", True)
    window.hosts.keep_users(target.key, (ANA,), None)
    window.hosts._update_host_actions()
    assert folder.text() == "User's folder (ana)" and message.text() == "Send a message…"
    window.hosts.keep_users(target.key, (), None)  # a check just found nobody
    window.hosts._update_host_actions()
    assert (folder.text(), folder.isEnabled()) == ("User's folder (nobody signed in)", False)
    assert (message.text(), message.isEnabled()) == ("Send a message (nobody signed in)", False)
    old = datetime.now(UTC) - timedelta(minutes=11)  # an old check says nothing about now
    window.hosts._users_found[target.key] = ((), None, old)
    window.hosts._update_host_actions()
    assert (folder.text(), folder.isEnabled()) == ("User's folder", True)


def test_a_group_s_menu_has_one_refresh(window: CapyWindow) -> None:
    doc = window.hosts.document
    assert doc is not None
    menu = QMenu()
    window.hosts.fill_group_menu(menu, doc.hosts.groups[0])
    texts = [label(a) for a in menu.actions() if a.text()]
    assert texts[-1] == "&Refresh group" and sum("Refresh" in t for t in texts) == 1
