from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QDialog, QWidgetAction

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import checks
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_ui
from capypanel.ui.hosts_tool import tool as hosts_module
from capypanel.ui.list_workspace import workspace as workspace_module
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.menus import label
from capypanel.ui.themes import engine as themes

DESK = Session("ana", "CORP", "console", "active", None)


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, office = HostList().add_group("Office")
    hl, inner = hl.add_group("Desks", parent=office.id)
    for name, group, address in [
        ("PC-1", office.id, "10.0.0.1"), ("PC-2", inner.id, "10.0.0.2"),
        ("PC-3", inner.id, "10.0.0.3"), ("Desk 4", office.id, ""),
    ]:  # fmt: skip
        hl, _host = hl.add_host(name, group, address=address)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


def _ids(win: MainWindow, *names: str) -> list[str]:
    assert win.hosts.document is not None
    return [h.id for h in win.hosts.document.hosts.hosts if h.name in names]


def _wait(win: MainWindow) -> None:
    for _ in range(500):
        QApplication.processEvents()
        if win.hosts._run is None:
            return
    pytest.fail("Refresh never finished")


def _cells(win: MainWindow, name: str) -> tuple[str, str]:
    table = win.hosts.table
    for index in range(table.topLevelItemCount()):
        item = table.topLevelItem(index)
        if item is not None and item.text(0) == name:
            return item.text(table.STATUS), item.text(table.USER)
    raise AssertionError(name)


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What each address answers; records every check and the account it used."""
    plan: dict[str, Any] = {"seen": []}

    def run(address: str, wanted: Checks) -> Found:
        plan["seen"].append((address, wanted.status, wanted.users, wanted.account))
        answer: Any = plan.get(address, Found(Status.ONLINE, (DESK,)))
        return answer if isinstance(answer, Found) else answer(wanted)

    monkeypatch.setattr(checks, "run", run)
    return plan


def test_checking_selected_hosts_fills_the_status_and_user_columns(
    window: MainWindow, answers: dict[str, Any]
) -> None:
    answers["10.0.0.2"] = Found(Status.OFFLINE, users_error=SessionsError(Reason.UNREACHABLE))
    answers["10.0.0.1"] = Found(Status.ONLINE, (DESK,), answered=("10.0.0.1", 445))
    window.hosts.table.select_ids(_ids(window, "PC-1", "PC-2", "Desk 4"))
    window.hosts.commands.check_users.trigger()
    _wait(window)
    assert _cells(window, "PC-1") == ("Online", "CORP\\ana")
    assert _cells(window, "PC-2") == ("Offline", "Unreachable")
    first = window.hosts.table._rows[_ids(window, "PC-1")[0]]
    assert "Answered at 10.0.0.1, port 445." in first.toolTip(window.hosts.table.STATUS)
    assert _cells(window, "PC-3") == ("", "")  # not selected: not checked
    assert {a for a, *_ in answers["seen"]} == {"10.0.0.1", "10.0.0.2"}  # no address: skipped
    window.hosts.table.select_ids(_ids(window, "PC-1"))
    assert window.hosts.details.shown_value("users") == "CORP\\ana"


def test_status_only_doesnt_read_users(window: MainWindow, answers: dict[str, Any]) -> None:
    answers["10.0.0.1"] = Found(Status.ONLINE)
    window.hosts.table.select_ids(_ids(window, "PC-1"))
    window.hosts.commands.check_status.trigger()
    _wait(window)
    assert answers["seen"] == [("10.0.0.1", True, False, None)]
    assert _cells(window, "PC-1") == ("Online", "")


def test_a_removed_host_no_longer_counts_as_online(
    window: MainWindow, answers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.table.select_ids(_ids(window, "PC-1", "PC-2"))
    window.hosts.commands.check_status.trigger()
    _wait(window)
    assert "2 online" in window.hosts.status_label.text()
    monkeypatch.setattr(workspace_module, "confirm", lambda *_args: True)
    assert window.hosts.document is not None
    window.hosts.remove_items([h for h in window.hosts.document.hosts.hosts if h.name == "PC-1"])
    assert "1 online" in window.hosts.status_label.text()


def _pick_group(window: MainWindow, name: str) -> None:
    assert window.hosts.document is not None
    group = next(g for g in window.hosts.document.hosts.groups if g.name == name)
    window.hosts.nav.select_group(group.id)
    window.hosts._show_items()


def test_refresh_checks_every_host_shown_even_with_nothing_selected(
    window: MainWindow, answers: dict[str, Any]
) -> None:
    _pick_group(window, "Desks")
    assert window.hosts.table.selected_ids() == []
    window.hosts.toolbar.refresh_status.trigger()
    _wait(window)
    assert sorted(a for a, *_ in answers["seen"]) == ["10.0.0.2", "10.0.0.3"]


def test_the_panel_runs_several_checks_and_remembers_its_ticks(
    window: MainWindow, answers: dict[str, Any]
) -> None:
    _pick_group(window, "Office")  # the group and the one inside it
    panel = window.hosts.refresh_panel
    panel.users_box.setChecked(False)
    panel.run_button.click()
    _wait(window)
    assert sorted(a for a, *_ in answers["seen"]) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    assert window.prefs["refresh"] == {"status": True, "users": False}


def test_f5_runs_what_the_panel_has_ticked(window: MainWindow, answers: dict[str, Any]) -> None:
    _pick_group(window, "Desks")
    window.hosts.refresh_panel.users_box.setChecked(False)
    f5 = window.hosts.commands.refresh_shown
    assert f5.shortcut().toString() == "F5" and f5 in window.hosts.actions()
    f5.trigger()
    _wait(window)
    assert sorted(a for a, *_ in answers["seen"]) == ["10.0.0.2", "10.0.0.3"]
    assert {users for _a, _s, users, _acc in answers["seen"]} == {False}  # only what's ticked


def test_a_refusal_asks_for_an_account_and_retries_only_those_hosts(
    window: MainWindow, answers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def admins_only(wanted: Checks) -> Found:
        if wanted.account is None:
            return Found(Status.ONLINE, users_error=SessionsError(Reason.NOT_ADMIN, 259))
        return Found(Status.ONLINE, (DESK,))

    answers["10.0.0.3"] = admins_only
    asked: list[str] = []

    def type_account(dialog: check_ui.AccountDialog) -> int:
        asked.append(dialog.windowTitle())
        dialog.user.setText("CORP\\admin")
        dialog.password.setText("pw")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(check_ui.AccountDialog, "exec", type_account)
    window.hosts.table.select_ids(_ids(window, "PC-1", "PC-3"))
    window.hosts.commands.check_users.trigger()
    _wait(window)
    _wait(window)  # the retry with the typed account
    assert asked == ["Account for logged-on users"]
    retried = [(a, acc) for a, _s, _u, acc in answers["seen"] if acc is not None]
    assert retried == [("10.0.0.3", Account("CORP\\admin", "pw"))]
    assert _cells(window, "PC-3")[1] == "CORP\\ana"
    window.hosts.forget_passwords()
    assert window.hosts._account is None


def test_a_rejected_typed_account_is_never_tried_on_the_other_hosts(
    window: MainWindow, answers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts._account = Account("CORP\\admin", "typo")
    rejected = Found(Status.ONLINE, users_error=SessionsError(Reason.REJECTED, 1326))
    for address in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        answers[address] = rejected
    monkeypatch.setattr(check_ui.AccountDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)
    window.hosts.table.select_ids(_ids(window, "PC-1", "PC-2", "PC-3"))
    window.hosts.commands.check_users.trigger()
    _wait(window)
    assert len(answers["seen"]) == 1  # one host refused it; the batch stopped


def test_host_menu_items_read_on_their_own_with_no_headings(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    class Recorded(workspace_module.QMenu):  # type: ignore[misc]
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            seen.extend(label(a) for a in self.actions() if a.text())
            assert not any(isinstance(a, QWidgetAction) for a in self.actions())  # no headings

    monkeypatch.setattr(workspace_module, "QMenu", Recorded)
    window.show()
    QApplication.processEvents()
    window.hosts.table.select_ids(_ids(window, "PC-1"))
    first = window.hosts.table.topLevelItem(0)
    assert first is not None
    row = window.hosts.table.visualItemRect(first)
    window.hosts._item_menu(QPoint(row.left() + 10, row.center().y()))  # on the name
    assert seen == [
        "&Connect", "Refresh &status", "Refresh &logged-on users", "Co&py",
        "&Edit selected…", "&Move to", "&Remove selected",
    ]  # fmt: skip


def test_the_toolbar_lines_up_with_the_panes(window: MainWindow) -> None:
    window.resize(1200, 600)
    window.show()
    for _ in range(5):
        QApplication.processEvents()
    window.hosts._align_toolbar()
    QApplication.processEvents()
    bar = window.hosts.toolbar  # Connect, Refresh | Inventory | Report, from the left
    order = [bar.connect_button, bar.refresh_button, bar.inventory_button, bar.report_button]
    lefts = [b.mapTo(window, QPoint(0, 0)).x() for b in order]
    assert (
        lefts == sorted(lefts)
        and bar.refresh_button.parentWidget() is bar.connect_button.parentWidget()
    )
    search, nav = window.hosts.search, window.hosts.nav  # the search box's top meets the panes'
    assert search.mapTo(window, QPoint(0, 0)).y() == nav.mapTo(window, QPoint(0, 0)).y()
    connect = window.hosts.toolbar.connect_button  # and Connect starts where the panes do
    assert abs(connect.mapTo(window, QPoint(0, 0)).x() - nav.mapTo(window, QPoint(0, 0)).x()) <= 1


def test_the_toolbar_stays_lined_up_after_a_theme_switch(window: MainWindow) -> None:
    # Each theme pads the toolbar differently; the Windows style ignores padding altogether.
    window.resize(1200, 600)
    window.show()
    for theme in ("capypanel-dark", "windows-dark", "paper"):
        window.set_theme(theme)
        for _ in range(10):
            QApplication.processEvents()
        connect, nav = window.hosts.toolbar.connect_button, window.hosts.nav
        assert (
            abs(connect.mapTo(window, QPoint(0, 0)).x() - nav.mapTo(window, QPoint(0, 0)).x()) <= 1
        )
        above = connect.mapTo(window.hosts.toolbar, QPoint(0, 0)).y()  # T1: 6 px above and below
        assert above == 6 and window.hosts.toolbar.height() - above - connect.height() == 6
    window.set_theme(themes.DEFAULT_THEME.id)  # as the other tests expect


def test_a_large_users_check_asks_first(
    window: MainWindow, answers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosts_module, "MANY_USER_CHECKS", 1)
    asked: list[str] = []
    monkeypatch.setattr(
        hosts_module, "confirm", lambda _p, _t, text, _a: asked.append(text) or False
    )
    _pick_group(window, "Office")
    window.hosts.toolbar.refresh_users.trigger()
    _wait(window)
    assert asked == ["Check who is logged on to 3 hosts?"] and answers["seen"] == []
    window.hosts.toolbar.refresh_status.trigger()  # Status never asks
    _wait(window)
    assert len(answers["seen"]) == 3 and len(asked) == 1


def test_automatic_status_is_off_by_default_and_checks_only_status(
    window: MainWindow, answers: dict[str, Any]
) -> None:
    assert not window.hosts._auto_timer.isActive()
    dialog = window.settings_dialog()
    dialog.hosts.pick_every(3)  # Custom…: every 3 minutes
    assert window.hosts._auto_timer.isActive() and window.hosts._auto_timer.interval() == 3 * 60_000
    assert window.prefs["auto_status"] == {"on": True, "minutes": 3}
    window.hosts._auto_status_check()  # what the timer does
    _wait(window)
    assert answers["seen"] and all(s and not u for _a, s, u, _acc in answers["seen"])
