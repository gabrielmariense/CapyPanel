from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import checks
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, er = HostList().add_group("Emergency")
    hl, triage = hl.add_group("Triage", parent=er.id)
    hl, labs = hl.add_group("Labs")
    for name, group, address in [
        ("TRIAGE-01", triage.id, "10.0.4.21"), ("TRIAGE-02", triage.id, "10.0.4.22"),
        ("LAB-01", labs.id, "10.0.9.1"), ("RECEP-04", er.id, "10.0.4.40"),
    ]:  # fmt: skip
        hl, _host = hl.add_host(name, group, address=address)
    path = tmp_path / "hospital.json"
    listfile.save(path, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.open_list(path)
    win.nav.select_group(labs.id)  # searching ignores the group picked
    win._show_hosts()
    yield win
    win.close()


def _search(win: MainWindow, text: str) -> None:
    win.search.setText(text)
    win._show_hosts()  # what the typing pause does


def _rows(win: MainWindow, column: int = 0) -> list[str]:
    items = (win.table.topLevelItem(i) for i in range(win.table.topLevelItemCount()))
    return sorted(item.text(column) for item in items if item is not None)


def _id(win: MainWindow, name: str) -> str:
    assert win.document is not None
    return next(h.id for h in win.document.hosts.hosts if h.name == name)


def test_search_finds_hosts_in_every_group_by_name_or_address(window: MainWindow) -> None:
    assert _rows(window) == ["LAB-01"]
    _search(window, "triage")
    assert _rows(window) == ["TRIAGE-01", "TRIAGE-02"]
    _search(window, " 10.0.4.4 ")
    assert _rows(window) == ["RECEP-04"]
    assert window.nav.current_filter().kind == "group"  # kept for when the search ends
    assert not window.nav.groups.selectedItems()  # but nothing shows as picked meanwhile


def test_search_finds_logged_on_users_from_the_last_check(window: MainWindow) -> None:
    desk = Session("Tricia.N", "CORP", "console", "active", None)
    window._users_found[_id(window, "RECEP-04")] = ((desk,), None, datetime.now())
    _search(window, "tri")
    assert _rows(window) == ["RECEP-04", "TRIAGE-01", "TRIAGE-02"]


def test_the_group_column_shows_only_while_searching(window: MainWindow) -> None:
    table = window.table
    assert table.isColumnHidden(table.GROUP)
    _search(window, "0")
    assert not table.isColumnHidden(table.GROUP)
    assert "Emergency › Triage" in _rows(window, table.GROUP)
    assert table.header().visualIndex(table.GROUP) == 1  # right after Computer
    assert "group" not in table.hidden_columns()  # never saved as a column choice
    _search(window, "")
    assert table.isColumnHidden(table.GROUP)
    assert _rows(window) == ["LAB-01"]


def test_the_status_bar_counts_what_was_found(window: MainWindow) -> None:
    _search(window, "triage")
    assert "2 found" in window._list_label.text()
    _search(window, "")
    assert "found" not in window._list_label.text()


def test_picking_a_group_ends_the_search(window: MainWindow) -> None:
    _search(window, "triage")
    window.nav.everything.setCurrentItem(window.nav._everything_item)
    window.nav._everything_item.setSelected(True)
    assert window.search.text() == ""
    assert len(_rows(window)) == 4


def test_double_click_connects_and_show_in_group_opens_the_group(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    connected: list[bool] = []
    monkeypatch.setattr(window, "connect_selected", lambda: connected.append(True))
    _search(window, "triage-02")
    item = window.table.topLevelItem(0)
    assert item is not None
    window.table.itemDoubleClicked.emit(item, 0)
    assert connected == [True]  # also during a search, like Enter
    assert window.search.text() == "triage-02"
    window.table.select_ids([_id(window, "TRIAGE-02")])
    window.commands.show_in_group.trigger()
    assert window.search.text() == ""
    assert window.nav.groups.selectedItems()[0].text(0).startswith("Triage")
    assert window.table.selected_ids() == [_id(window, "TRIAGE-02")]


def test_clearing_the_search_goes_back_to_the_group_picked_before(window: MainWindow) -> None:
    _search(window, "triage")
    window.table.select_ids([_id(window, "TRIAGE-01")])
    window.search.clear()
    window._show_hosts()  # what the typing pause does
    assert _rows(window) == ["LAB-01"]  # Labs, as before the search; no jump to Triage


def test_down_in_the_search_box_moves_to_the_first_result(window: MainWindow) -> None:
    _search(window, "triage")
    down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    window.search.keyPressEvent(down)
    assert window.table.selected_ids() == [_id(window, "TRIAGE-01")]


def test_the_placeholder_names_what_is_searched(window: MainWindow) -> None:
    table = window.table
    assert window.search.placeholderText() == "Search name, address, user"
    table._show_column(table.USER, False)
    assert window.search.placeholderText() == "Search name, address"
    table._show_column(table.USER, True)


def test_refresh_checks_only_the_search_results(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def run(address: str, wanted: Checks) -> Found:
        seen.append(address)
        return Found(Status.ONLINE)

    monkeypatch.setattr(checks, "run", run)
    _search(window, "triage")
    window._refresh_shown(True, False)
    for _ in range(500):
        QApplication.processEvents()
        if window._run is None:
            break
    assert sorted(seen) == ["10.0.4.21", "10.0.4.22"]


def test_escape_clears_the_search_wherever_the_focus_is(window: MainWindow) -> None:
    window.search.setText("triage")
    escape = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    window.search.keyPressEvent(escape)
    assert window.search.text() == ""
    _search(window, "triage")
    window.table.setFocus()
    window._end_search()  # the window's Esc shortcut
    assert window.search.text() == ""
    assert _rows(window) == ["LAB-01"]


def test_search_covers_only_the_columns_shown(window: MainWindow) -> None:
    table = window.table
    _search(window, "10.0.4.4")
    assert _rows(window) == ["RECEP-04"]
    table._show_column(table.ADDRESS, False)  # what View's column chooser does
    assert _rows(window) == []  # re-run at once: nothing shown matches any more
    _search(window, "recep")
    assert _rows(window) == ["RECEP-04"]  # the name always counts


def test_hiding_domains_changes_the_users_shown_and_searched(window: MainWindow) -> None:
    desk = Session("ana", "CORP", "console", "active", None)
    host = _id(window, "LAB-01")
    window._users_found[host] = ((desk,), None, datetime.now())
    window._show_hosts()
    assert _rows(window, window.table.USER) == ["CORP\\ana"]
    _search(window, "corp")
    assert _rows(window) == ["LAB-01"]
    window.commands.show_domains.setChecked(False)
    try:
        assert _rows(window) == []  # the domain isn't shown, so it isn't searched
        _search(window, "")
        assert _rows(window, window.table.USER) == ["ana"]
    finally:
        window.commands.show_domains.setChecked(True)  # module-wide: leave it as found


def test_tooltips_keep_the_domain_and_active_users_come_first(window: MainWindow) -> None:
    away = Session("bob", "CORP", "rdp", "disconnected", None)
    here = Session("ana", "CORP", "console", "active", None)
    host = _id(window, "LAB-01")
    window._users_found[host] = ((away, here), None, datetime.now())
    window.commands.show_domains.setChecked(False)
    try:
        item = window.table.topLevelItem(0)
        assert item is not None
        assert item.text(window.table.USER) == "ana, bob (disconnected)"
        assert item.toolTip(window.table.USER).startswith("CORP\\ana, CORP\\bob")
    finally:
        window.commands.show_domains.setChecked(True)


def test_online_count_and_summary(window: MainWindow) -> None:
    window._status_found[_id(window, "LAB-01")] = (Status.ONLINE, datetime.now(), None)
    window._show_hosts()
    assert "1 online" in window._list_label.text()
    window.table.clearSelection()
    hint = window.details._hint.text()
    assert hint.startswith("1 host shown\n1 online")
