"""The User profiles tool: the Hosts tab with the hosts of Hosts' open list, a tab per host opened,
the profiles table with its filters and order, a profile's details, sizes, deletes, what a failed
scan says, and the limit on reads and counts shared by every tab. Nothing here reaches a PC: the
scan, the sizes and the deletes are answered by hand."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QShowEvent
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.remote import user_profiles
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.status import Status
from capypanel.core.remote.user_profiles import (
    Deleted,
    Kind,
    Outcome,
    Profile,
    Scan,
    State,
    Why,
)
from capypanel.ui.profiles_tool import host_page, hosts_page, panels, rows, work
from capypanel.ui.profiles_tool import tool as tool_ui
from capypanel.ui.profiles_tool.host_page import HostPage, Stage
from capypanel.ui.profiles_tool.panels import DeleteDialog
from capypanel.ui.profiles_tool.rows import Filters
from capypanel.ui.profiles_tool.tabs import HOSTS
from capypanel.ui.profiles_tool.tool import ProfilesTool

SID = "S-1-5-21-1004336348-1177238915-682003330-"
GB = 1024**3


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, tzinfo=UTC)


def _row(name: str, number: int, used: datetime | None, **more: Any) -> Profile:
    sid = f"{SID}{number}"
    fields: dict[str, Any] = {
        "sid": sid, "key": sid, "user": f"EXAMPLE\\{name}", "known": True,
        "path": f"C:\\Users\\{name}", "kind": Kind.PROFILE, "state": State.READY,
        "last_used": used, "modified": used,
    }  # fmt: skip
    return Profile(**{**fields, **more})


ANA = _row("ana", 1104, _day(2026, 11, 10), state=State.IN_USE)
RUI = _row("rui", 1107, _day(2026, 11, 3))
BIA = _row("bia", 1112, _day(2026, 8, 14))
MARTA = _row("marta.old", 1147, _day(2025, 3, 11), user="marta.old", known=False)
OLD = Profile(
    "", "", "temp.joao", False, "C:\\Users\\temp.joao", Kind.FOLDER, State.READY,
    modified=_day(2025, 1, 7),
)  # fmt: skip
GONE = _row("pedro", 1098, None, user="pedro", known=False, kind=Kind.ENTRY, modified=None)
PUBLIC = Profile("", "", "Public", False, "C:\\Users\\Public", Kind.FOLDER, State.PROTECTED)
ROWS = (ANA, RUI, BIA, MARTA, OLD, GONE, PUBLIC)
SIZES = {RUI.ident: 3 * GB, BIA.ident: 6 * GB, MARTA.ident: GB // 2, OLD.ident: 40 * 1024**2}


class Pc:
    """The PCs the tool talks to: what a scan and a size answer, and what was asked."""

    def __init__(self) -> None:
        self.answers: dict[str, Scan | BaseException] = {}
        self.scanned: list[tuple[str, Account | None]] = []
        self.sized: list[str] = []

    def scan(self, host: str, account: Account | None = None, **_more: object) -> Scan:
        self.scanned.append((host, account))
        answer = self.answers.get(host, Scan(host, "C:\\Users", ROWS))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def size(self, scanned: Scan, profile: Profile, account: Account | None = None,
             **_more: object) -> int | None:  # fmt: skip
        self.sized.append(profile.user)
        return SIZES.get(profile.ident, 0)


class Worker:
    """The tool's background work: done on the spot, or held until a test lets it end."""

    def __init__(self) -> None:
        self.holding = False
        self.held: list[Callable[[], None]] = []

    def start(self, job: Callable[[], Any], done: Callable[[Any], None],
              failed: Callable[[BaseException], None], jobs: Any) -> None:  # fmt: skip
        def run() -> None:
            try:
                value = job()
            except Exception as e:  # noqa: BLE001 - as the tool's own worker does
                failed(e)
            else:
                done(value)

        if self.holding:
            self.held.append(run)
        else:
            run()

    def end(self, n: int = 1) -> None:
        for _turn in range(n):
            self.held.pop(0)()


@pytest.fixture
def pc(monkeypatch: pytest.MonkeyPatch) -> Pc:
    pc = Pc()
    monkeypatch.setattr(user_profiles, "scan", pc.scan)
    monkeypatch.setattr(user_profiles, "profile_size", pc.size)
    monkeypatch.setattr(tool_ui, "windows_account", lambda: "EXAMPLE\\support")
    return pc


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> Worker:
    worker = Worker()
    monkeypatch.setattr(work, "start", worker.start)
    return worker


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, pc: Pc, worker: Worker) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, clinic = HostList().add_group("Clinic")
    for name, address in (("DESK-10", "192.0.2.20"), ("DESK-03", "192.0.2.13"), ("LAB-02", "")):
        hl, _host = hl.add_host(name, clinic.id, address=address)
    hl, _host = hl.add_host("Front desk printer room", clinic.id)  # no address, not a PC name
    path = tmp_path / "clinic.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    win.show_tool("profiles")
    yield win
    win.close()


def _tool(win: CapyWindow) -> ProfilesTool:
    tool = win.tools["profiles"]
    assert isinstance(tool, ProfilesTool)
    return tool


def _id(win: CapyWindow, name: str) -> str:
    doc = win.hosts.document
    assert doc is not None
    return next(h.id for h in doc.hosts.hosts if h.name == name)


def _hosts(tool: ProfilesTool) -> list[str]:
    return [row[hosts_page.NAME] for row in tool.hosts_page.table.texts()]


def _host_row(tool: ProfilesTool, name: str) -> list[str]:
    return next(r for r in tool.hosts_page.table.texts() if r[hosts_page.NAME] == name)


def _open(win: CapyWindow, name: str = "DESK-03", focus: bool = True) -> HostPage:
    tool = _tool(win)
    tool.open_hosts([_id(win, name)], focus)
    page = tool.page(_id(win, name))
    assert page is not None
    return page


def _pick_row(page: HostPage, user: str) -> None:
    tree = page.table.tree
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item is not None and item.text(panels.USER) == user:
            tree.setCurrentItem(item)
            return
    raise AssertionError(user)


def _users(page: HostPage) -> list[str]:
    return [row[panels.USER] for row in page.table.texts()]


def _states(page: HostPage) -> dict[str, str]:
    return {row[panels.USER]: row[panels.STATE] for row in page.table.texts()}


def _tab_tip(tool: ProfilesTool, page: HostPage) -> str:
    return tool.tabs.bar.tabToolTip(tool.tabs.index_of(page.target.key))


# ---- the Hosts tab ----


def test_it_is_the_third_tool_and_its_hosts_tab_lists_hosts_open_list(
    window: CapyWindow, tmp_path: Path
) -> None:
    tool = _tool(window)
    assert list(window.tools) == ["hosts", "printers", "profiles"]
    assert (tool.tool_name(), tool.ICON) == ("User profiles", "profile-card")
    assert tool.list_picker.text() == "clinic"
    assert _hosts(tool) == ["DESK-03", "DESK-10", "LAB-02"]  # natural order; reachable ones
    assert tool.tabs.current() == HOSTS and tool.tabs.pinned.tabText(0) == "Hosts (3)"
    assert tool.hosts_page.box.name.text() == "All hosts"
    assert tool.hosts_page.box.about.text() == "3 hosts"
    assert tool.status_label.text() == "3 hosts"
    assert _host_row(tool, "DESK-03") == ["DESK-03", "192.0.2.13", "Not checked", "", "", ""]
    bar = tool.bar
    assert (bar.scan_button.text().strip(), bar.scan_button.isEnabled()) == ("Scan", False)
    assert not bar.sizes_button.isEnabled() and not bar.delete_button.isEnabled()
    assert tool.nav.add_group_button.isHidden()  # read only: groups are made in Hosts

    hl, group = HostList().add_group("Lab")
    hl, _host = hl.add_host("LAB-07", group.id, address="198.51.100.7")
    other = tmp_path / "lab.json"
    listfile.save(other, hl, expected=None)
    window.hosts.open_list(other)  # Hosts opens another list: this tool follows
    assert tool.list_picker.text() == "lab" and _hosts(tool) == ["LAB-07"]
    tool._pick_list(tmp_path / "clinic.json")  # and its dropdown opens one in Hosts
    assert window.hosts.document is not None and window.hosts.document.path.name == "clinic.json"
    assert _hosts(tool) == ["DESK-03", "DESK-10", "LAB-02"]


def test_the_status_column_is_hosts_own_last_check(window: CapyWindow) -> None:
    tool = _tool(window)
    key = _id(window, "DESK-03")
    window.hosts._status_found[key] = (Status.OFFLINE, datetime.now(UTC), None)
    window.hosts.host_changed.emit(key)
    assert _host_row(tool, "DESK-03")[hosts_page.STATUS] == "Offline"
    tool.hosts_page.table.select(key)
    card = tool.hosts_page.host_card
    assert card.isVisibleTo(tool.hosts_page.side) and card.name.text() == "DESK-03"
    assert card.status.text().startswith("Offline · checked by Hosts at ")


def test_the_search_looks_through_every_host_and_a_group_narrows_them(
    window: CapyWindow, tmp_path: Path
) -> None:
    tool = _tool(window)
    hl, clinic = HostList().add_group("Clinic")
    hl, lab = hl.add_group("Lab", parent=clinic.id)
    hl, er = hl.add_group("ER")
    for name, group, address, tags in (
        ("DESK-01", clinic.id, "192.0.2.11", ()), ("LAB-01", lab.id, "192.0.2.31", ("lab",)),
        ("ER-01", er.id, "192.0.2.41", ()), ("SPARE", NO_GROUP, "192.0.2.90", ()),
    ):  # fmt: skip
        hl, _host = hl.add_host(name, group, address=address, tags=tags)
    path = tmp_path / "wards.json"
    listfile.save(path, hl, expected=None)
    window.hosts.open_list(path)
    assert _hosts(tool) == ["DESK-01", "ER-01", "LAB-01", "SPARE"]
    tool.nav.select_group(clinic.id)
    tool.nav.filter_changed.emit()
    assert _hosts(tool) == ["DESK-01", "LAB-01"]  # the groups inside it too
    assert tool.hosts_page.box.name.text() == "Clinic"
    tool.hosts_page.search.setText("0.2.4")  # a search: every group
    assert _hosts(tool) == ["ER-01"] and tool.hosts_page.box.about.text() == "1 of 4 shown"
    tool.hosts_page.search.clear()
    tool.nav.select_group(NO_GROUP)
    tool.nav.filter_changed.emit()
    assert _hosts(tool) == ["SPARE"]

    # Each list comes back on the group it was left on.
    tool.nav.select_group(er.id)
    tool.nav.filter_changed.emit()
    assert tool.prefs[tool_ui.VIEWS_KEY][str(path)] == ["group", er.id]
    window.hosts.open_list(tmp_path / "clinic.json")
    assert _hosts(tool) == ["DESK-03", "DESK-10", "LAB-02"]
    window.hosts.open_list(path)
    assert _hosts(tool) == ["ER-01"]


def _record_checks(window: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Hosts' status check, recorded instead of run: the host names of each call."""
    calls: list[list[str]] = []

    def check(hosts: Any, *, status: bool, users: bool) -> None:
        assert status and not users  # status only: never who's logged on
        calls.append([h.name for h in hosts])

    monkeypatch.setattr(window.hosts, "check_hosts", check)
    return calls


def test_refresh_checks_the_hosts_shown_or_the_tabs_host_as_hosts_does(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    calls = _record_checks(window, monkeypatch)
    bar = tool.bar
    assert bar.refresh_button.text().strip() == "Refresh all" and bar.refresh_button.isEnabled()
    bar.refresh_button.click()
    assert calls == [["DESK-03", "DESK-10", "LAB-02"]]
    _open(window)
    assert bar.refresh_button.text().strip() == "Refresh host"
    bar.refresh_button.click()
    assert calls[-1] == ["DESK-03"]
    monkeypatch.setattr(window.hosts, "checking", lambda: True)  # a Refresh is running
    window.hosts.checks_changed.emit()
    assert not bar.refresh_button.isEnabled()


def test_picking_a_group_checks_the_hosts_not_checked_lately(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    calls = _record_checks(window, monkeypatch)
    now = datetime.now(UTC)
    window.hosts._status_found[_id(window, "DESK-03")] = (Status.ONLINE, now, None)
    window.hosts._status_found[_id(window, "DESK-10")] = (
        Status.OFFLINE, now - timedelta(minutes=30), None,
    )  # fmt: skip
    tool.nav.filter_changed.emit()
    assert calls == [["DESK-10", "LAB-02"]]  # DESK-03 was checked a moment ago
    tool.hosts_page.search.setText("desk")  # a search alone checks nothing
    assert len(calls) == 1
    tool.showEvent(QShowEvent())  # opening the tool checks once more what's stale
    assert len(calls) == 2


def test_the_panels_open_wide_enough_for_long_names(window: CapyWindow) -> None:
    tool = _tool(window)
    assert tool.prefs.get(tool_ui.PANES_KEY) is None  # nothing saved: the first widths
    assert tool.side.minimumWidth() >= panels.RIGHT
    assert tool.inner.sizes()[1] >= panels.DETAILS or tool.inner.sizes()[1] == 0
    progress = tool.hosts_page.progress
    long_name = "UTI A - Corredor · 000000 - a very long host name indeed"
    line = hosts_page._Line("@x", None, long_name, "12:57", "")
    line.resize(220, 24)
    line.show()
    QApplication.processEvents()
    assert line.where.isVisible() and line.where.width() >= line.where.sizeHint().width()
    assert line.name.shown_text().endswith("…") and line.name.toolTip() == long_name
    line.close()
    assert progress is not None


def test_a_group_picked_while_a_hosts_tab_is_in_front_brings_the_hosts_tab_back(
    window: CapyWindow,
) -> None:
    tool = _tool(window)
    _open(window)
    assert tool.tabs.current() == _id(window, "DESK-03")
    tool.nav.filter_changed.emit()
    assert tool.tabs.current() == HOSTS


# ---- opening hosts ----


def test_a_double_click_or_enter_opens_a_hosts_tab_and_goes_to_it(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    table = tool.hosts_page.table
    key = _id(window, "DESK-03")
    table.select(key)
    assert tool.bar.scan_button.text().strip() == "Scan DESK-03"
    item = table.tree.currentItem()
    assert item is not None
    table.tree.itemDoubleClicked.emit(item, 0)
    assert pc.scanned == [("192.0.2.13", None)] and tool.tabs.current() == key
    assert tool.tabs.host_keys() == [key]
    tool.switch(HOSTS)
    table.select(key)
    QApplication.sendEvent(table.tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                 Qt.KeyboardModifier.NoModifier))  # fmt: skip
    assert tool.tabs.current() == key and len(pc.scanned) == 1  # its tab: never a second read


def test_a_middle_click_or_ctrl_enter_opens_it_behind(window: CapyWindow, pc: Pc) -> None:
    tool = _tool(window)
    table = tool.hosts_page.table
    table.select(_id(window, "DESK-10"))
    QApplication.sendEvent(table.tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                                 Qt.KeyboardModifier.ControlModifier))  # fmt: skip
    assert tool.tabs.current() == HOSTS and tool.tabs.host_keys() == [_id(window, "DESK-10")]
    item = table.tree.topLevelItem(0)  # DESK-03
    assert item is not None
    where = QPointF(table.tree.visualItemRect(item).center())
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, where, where,
                          Qt.MouseButton.MiddleButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)  # fmt: skip
    QApplication.sendEvent(table.tree.viewport(), release)
    assert tool.tabs.current() == HOSTS and len(tool.tabs.host_keys()) == 2
    assert [a for a, _b in pc.scanned] == ["192.0.2.20", "192.0.2.13"]


def test_scan_with_several_hosts_picked_opens_each_behind(window: CapyWindow) -> None:
    tool = _tool(window)
    table = tool.hosts_page.table
    for index in range(table.tree.topLevelItemCount()):
        item = table.tree.topLevelItem(index)
        assert item is not None
        item.setSelected(True)
    assert tool.bar.scan_button.text().strip() == "Scan 3 hosts"
    tool.bar.scan_button.click()
    assert tool.tabs.current() == HOSTS and len(tool.tabs.host_keys()) == 3
    assert _host_row(tool, "DESK-03")[3:] == ["7", "5", _host_row(tool, "DESK-03")[5]]


def test_typing_never_scans_and_the_empty_table_offers_the_typed_host(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    page = tool.hosts_page
    page.search.setText("192.0.2.50")
    page.search.returnPressed.emit()
    assert pc.scanned == [] and _hosts(tool) == []
    table = page.table
    assert table.scan_button.text() == "Scan 192.0.2.50" and table._empty.isVisibleTo(table)
    table.scan_button.click()
    assert pc.scanned == [("192.0.2.50", None)] and tool.tabs.current() == "@192.0.2.50"
    typed = tool.page("@192.0.2.50")
    assert typed is not None and typed.box.name.text() == "User profiles on 192.0.2.50"


# ---- a host's tab ----


def test_a_scan_shows_the_host_its_profiles_and_fills_the_hosts_tab(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    page = _open(window)
    assert page.box.name.text() == "User profiles on DESK-03"
    about = page.box.about.text()
    assert about.startswith("192.0.2.13 · scanned at ") and about.endswith(" · as EXAMPLE\\support")
    assert page.filters.shown.text() == "6 of 7 shown"  # Windows' own is hidden at first
    assert page.table.texts() == [  # the newest use first; rows with no date last
        ["", "EXAMPLE\\ana", "11/10/2026", "", "Profile", "In use"],
        ["", "EXAMPLE\\rui", "11/03/2026", "", "Profile", "Can be deleted"],
        ["", "EXAMPLE\\bia", "08/14/2026", "", "Profile", "Can be deleted"],
        ["", "marta.old  (unknown)", "03/11/2025", "", "Profile", "Can be deleted"],
        ["", "pedro  (unknown)", "—", "", "Registry entry, no folder", "Can be deleted"],
        ["", "temp.joao  (unknown)", "—", "", "Folder, no registry entry", "Can be deleted"],
    ]
    assert tool.status_label.text() == "DESK-03 · 7 profiles · 5 can be deleted"
    bar = tool.bar
    assert bar.scan_button.text().strip() == "Scan again" and bar.scan_button.isEnabled()
    assert "DESK-03" in bar.scan_button.toolTip() and bar.sizes_button.isEnabled()
    assert bar.delete_button.text().strip() == "Delete profiles…"
    assert page.details.shown_value("path") == ""  # nothing picked yet
    row = _host_row(tool, "DESK-03")
    assert row[hosts_page.PROFILES : hosts_page.DELETABLE + 1] == ["7", "5"]
    assert row[hosts_page.SCAN] != "" and _tab_tip(tool, page).startswith("Scanned at ")


def test_the_filters_narrow_the_rows(window: CapyWindow) -> None:
    page = _open(window)
    page.filters.hide_own.setChecked(False)
    assert "Public" in "".join(_users(page)) and page.filters.shown.text() == "7 of 7 shown"
    page.filters.leftovers.setChecked(True)
    assert _users(page) == ["pedro  (unknown)", "Public  (unknown)", "temp.joao  (unknown)"]
    page.filters.hide_own.setChecked(True)
    assert page.filters.shown.text() == "2 of 7 shown"
    since = page.filters.since
    choices = [since.itemText(i) for i in range(since.count())]
    assert choices == ["Any time", "1 month", "3 months", "6 months", "1 year"]


def test_unused_for_goes_by_the_last_use_or_else_the_folders_date() -> None:
    now = _day(2026, 11, 10)
    shown = rows.visible(ROWS, Filters(hide_own=False, months=6), now)
    assert shown == [MARTA, OLD]  # the folder with no entry counts by its own date
    assert rows.visible(ROWS, Filters(hide_own=False, months=1), now) == [BIA, MARTA, OLD]
    assert GONE not in rows.visible(ROWS, Filters(months=12), now)  # no date: never "older"
    assert rows.visible(ROWS, Filters(hide_own=False)) == list(ROWS)
    assert rows.visible(ROWS, Filters(leftovers=True)) == [OLD, GONE]


def test_a_click_on_a_column_title_sorts_by_what_the_cells_mean(window: CapyWindow) -> None:
    page = _open(window)
    page.count_sizes()
    tree = page.table.tree
    tree.sortByColumn(panels.SIZE, Qt.SortOrder.DescendingOrder)
    assert _users(page)[:3] == ["EXAMPLE\\bia", "EXAMPLE\\rui", "marta.old  (unknown)"]
    tree.sortByColumn(panels.USED, Qt.SortOrder.AscendingOrder)  # the oldest on top
    assert _users(page)[2:4] == ["marta.old  (unknown)", "EXAMPLE\\bia"]
    tree.sortByColumn(panels.USER, Qt.SortOrder.AscendingOrder)
    assert _users(page)[:2] == ["EXAMPLE\\ana", "EXAMPLE\\bia"]


def test_details_say_why_a_row_is_in_its_state(window: CapyWindow) -> None:
    page = _open(window)
    _pick_row(page, "marta.old  (unknown)")
    details = page.details
    assert details.shown_value("name") == "marta.old"
    assert details.shown_value("sid") == f"{SID}1147"
    assert details.shown_value("path") == "C:\\Users\\marta.old"
    assert details.shown_value("account") == ""  # Windows no longer knows it: "Unknown", muted
    assert details.shown_value("used") == "03/11/2025"
    _pick_row(page, "EXAMPLE\\ana")
    assert details.shown_value("account") == "EXAMPLE\\ana"
    assert rows.state_why(ANA, "C:\\Users").startswith("This person is signed in now.")
    outside = _row("svc", 1150, None, state=State.OUTSIDE, path="D:\\Perfis\\svc")
    assert rows.state_why(outside, "C:\\Users").endswith("profiles inside C:\\Users.")
    tree = page.table.tree
    item = tree.topLevelItem(0)
    assert item is not None and item.toolTip(panels.STATE).startswith("This person is signed")


# ---- sizes, and the limit every tab shares ----


def test_sizes_are_counted_on_demand_for_the_rows_shown_that_have_a_folder(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    page = _open(window)
    assert pc.sized == [] and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    tool.bar.sizes_button.click()
    assert "pedro" not in pc.sized and "Public" not in pc.sized  # no folder; hidden
    assert len(pc.sized) == 5
    sizes = {row[panels.USER]: row[panels.SIZE] for row in page.table.texts()}
    assert sizes["EXAMPLE\\rui"] == "3.0 GB" and sizes["marta.old  (unknown)"] == "0.5 GB"
    assert sizes["temp.joao  (unknown)"] == "40 MB" and sizes["pedro  (unknown)"] == ""
    assert not page.counting() and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    page.count_sizes()  # nothing left to count
    assert len(pc.sized) == 5


def test_counting_can_be_stopped_and_what_was_counted_stays(
    window: CapyWindow, worker: Worker
) -> None:
    tool = _tool(window)
    page = _open(window)
    worker.holding = True
    page.count_sizes()
    assert len(worker.held) == work.AT_ONCE and page.counting()
    assert tool.bar.sizes_button.text().strip() == "Stop the count"
    assert _tab_tip(tool, page) == "Calculating sizes: 0 of 5"
    assert [row[panels.SIZE] for row in page.table.texts()].count("counting…") == 5
    worker.end()  # one ends; the next one starts
    assert len(worker.held) == 4 and _tab_tip(tool, page) == "Calculating sizes: 1 of 5"
    tool.bar.sizes_button.click()  # Stop
    assert not page.counting() and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    assert "counting…" not in [row[panels.SIZE] for row in page.table.texts()]
    while worker.held:  # the ones under way end later: dropped
        worker.end()
    assert sum(size is not None for size in page._sizes.values()) == 1


def test_reads_and_counts_share_one_limit_across_every_tab_and_reads_go_first(
    window: CapyWindow, worker: Worker, tmp_path: Path, pc: Pc
) -> None:
    tool = _tool(window)
    hl, ward = HostList().add_group("Ward")
    for n in range(6):
        hl, _host = hl.add_host(f"PC-{n}", ward.id, address=f"192.0.2.{50 + n}")
    path = tmp_path / "ward.json"
    listfile.save(path, hl, expected=None)
    window.hosts.open_list(path)
    first = _open(window, "PC-0")
    worker.holding = True
    first.count_sizes()
    assert len(worker.held) == 4  # four folders under way, one waits
    tool.open_hosts([_id(window, f"PC-{n}") for n in range(1, 6)], False)
    pages = [tool.page(_id(window, f"PC-{n}")) for n in range(1, 6)]
    assert all(p is not None and p.stage is Stage.QUEUED for p in pages)
    assert _tab_tip(tool, pages[0]) == "Waiting to scan"  # type: ignore[arg-type]
    assert _host_row(tool, "PC-1")[hosts_page.SCAN] == "queued"
    worker.end()  # a count ends: the first read takes its place, ahead of the last folder
    assert pages[0] is not None and pages[0].stage is Stage.SCANNING
    assert _host_row(tool, "PC-1")[hosts_page.SCAN] == "scanning…"
    assert pc.scanned[-1] == ("192.0.2.50", None) and len(worker.held) == 4
    while worker.held:
        worker.end()
    assert all(p is not None and p.stage is Stage.SCANNED for p in pages)
    assert len(pc.sized) == 5  # the waiting folder was counted after the reads
    progress = tool.hosts_page.progress
    assert progress.summary.text() == "6 hosts in tabs · 6 done"


def test_scanning_the_same_host_again_keeps_the_sizes_of_rows_still_there(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    page = _open(window)
    page.count_sizes()
    pc.answers["192.0.2.13"] = Scan("192.0.2.13", "C:\\Users", (ANA, RUI, MARTA))
    tool.bar.scan_button.click()  # Scan again
    assert len(pc.scanned) == 2
    sizes = {row[panels.USER]: row[panels.SIZE] for row in page.table.texts()}
    assert sizes == {"EXAMPLE\\ana": "0 MB", "EXAMPLE\\rui": "3.0 GB",
                     "marta.old  (unknown)": "0.5 GB"}  # fmt: skip
    other = _open(window, "DESK-10")  # another host: its own tab, nothing carried over
    assert other.table.texts()[0][panels.SIZE] == ""


# ---- a scan that fails ----


def test_a_host_that_doesnt_answer_says_so_and_offers_to_try_again(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    pc.answers["192.0.2.13"] = RemoteError(Reason.UNREACHABLE)
    page = _open(window)
    card = page.card
    assert card is not None and card.heading.text() == "DESK-03 didn't answer"
    assert card.body.text().endswith("Nothing was read.")
    assert [b.text() for b in card.buttons] == ["Try again"]
    assert tool.status_label.text() == "DESK-03 · didn't answer"
    assert " · tried at " in page.box.about.text() and not page.filters.isEnabled()
    assert tool.bar.scan_button.isEnabled() and not tool.bar.sizes_button.isEnabled()
    assert _tab_tip(tool, page) == "DESK-03 didn't answer"
    assert _host_row(tool, "DESK-03")[hosts_page.SCAN] == "didn't answer"
    del pc.answers["192.0.2.13"]
    card.buttons[0].click()
    assert len(pc.scanned) == 2 and len(page.table.texts()) == 6


def test_a_host_that_refuses_the_account_offers_another_one(
    window: CapyWindow, pc: Pc, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    pc.answers["192.0.2.13"] = error = RemoteError(Reason.REJECTED, 5)
    asked: list[tuple[str, BaseException | None]] = []
    monkeypatch.setattr(
        window.hosts.runner, "another_account",
        lambda target, error, again: asked.append((target.name, error)),
    )  # fmt: skip
    page = _open(window)
    card = page.card
    assert card is not None
    assert card.heading.text() == "DESK-03 refused the account EXAMPLE\\support"
    assert [b.text() for b in card.buttons] == ["Try another account…", "Try again"]
    assert tool.status_label.text() == "DESK-03 · account refused"
    assert _tab_tip(tool, page).startswith("Refused the account EXAMPLE\\support: The PC")
    assert _host_row(tool, "DESK-03")[hosts_page.SCAN] == "account refused"
    card.buttons[0].click()
    assert asked == [("DESK-03", error)]


def test_any_other_failure_names_windows_error(window: CapyWindow, pc: Pc) -> None:
    pc.answers["192.0.2.13"] = RemoteError(Reason.OTHER, 1722)
    page = _open(window)
    card = page.card
    assert card is not None and card.heading.text() == "Couldn't read DESK-03's profiles"
    assert card.body.text().startswith("Windows error 1722.")
    said = rows.failure(TimeoutError("slow"), "DESK-03", "192.0.2.13", "EXAMPLE\\support")
    assert "took too long" in said.lines[0] and not said.another_account


# ---- how values read, and what's kept ----


def test_sizes_read_in_gigabytes_from_a_tenth_up_and_megabytes_under() -> None:
    assert rows.size_text(int(3.44 * GB)) == "3.4 GB"
    assert rows.size_text(250 * GB) == "250 GB"
    assert rows.size_text(GB // 10) == "0.1 GB"
    assert rows.size_text(40 * 1024**2) == "40 MB"
    assert rows.size_text(1) == "1 MB" and rows.size_text(0) == "0 MB"


def test_the_panels_widths_and_view_choices_are_kept(window: CapyWindow) -> None:
    tool = _tool(window)
    tool.save_state()
    left, right = tool.prefs[tool_ui.PANES_KEY]
    assert left > 0 and right > 0
    assert tool_ui._two_widths([230, 300]) == (230, 300)
    assert tool_ui._two_widths([0, 300]) is None and tool_ui._two_widths("wide") is None
    assert tool.view_actions() == [[tool.show_groups, tool.show_details]]
    tool.show_details.setChecked(False)
    assert tool.side.isHidden() and tool.prefs[tool_ui.SHOWN_KEY]["details"] is False
    tool.show_groups.setChecked(False)
    assert tool.nav.isHidden()


# ---- the tabs ----


def test_tabs_open_at_the_right_end_and_close_in_every_way(window: CapyWindow) -> None:
    tool = _tool(window)
    desk, other = _open(window), _open(window, "DESK-10", focus=False)
    keys = [desk.target.key, other.target.key]
    assert tool.tabs.host_keys() == keys and tool.tabs.current() == keys[0]
    tool._step(1)
    assert tool.tabs.current() == keys[1]
    tool._step(1)  # round to the Hosts tab
    assert tool.tabs.current() == HOSTS
    tool._step(-1)
    assert tool.tabs.current() == keys[1]
    assert tool.close_tab(keys[1]) and tool.tabs.current() == keys[0]  # the one on its left
    assert not tool.close_tab(HOSTS)  # pinned
    _open(window, "DESK-10", focus=False)
    tool.close_others(keys[0])
    assert tool.tabs.host_keys() == [keys[0]]
    tool.close_finished()
    assert tool.tabs.host_keys() == [] and tool.tabs.current() == HOSTS
    # A closed tab's counts stay on the Hosts tab.
    assert _host_row(tool, "DESK-03")[hosts_page.PROFILES : hosts_page.DELETABLE + 1] == ["7", "5"]


def test_progress_lists_the_hosts_in_tabs_by_where_they_are(
    window: CapyWindow, worker: Worker, pc: Pc
) -> None:
    tool = _tool(window)
    progress = tool.hosts_page.progress
    assert not progress.bar.isVisibleTo(progress)  # nothing open yet
    pc.answers["192.0.2.20"] = RemoteError(Reason.UNREACHABLE)
    _open(window, "DESK-10", focus=False)
    worker.holding = True
    _open(window, focus=False)
    assert progress.summary.text() == "2 hosts in tabs · 1 done"
    texts = [w.text() for w in progress.findChildren(hosts_page.QLabel) if w.isVisibleTo(progress)]
    assert "In progress (1)" in texts and "Done (1)" in texts and "didn't answer" in texts
    lines = progress.findChildren(hosts_page._Line)
    target = next(line for line in lines if line.name.text() == "DESK-10" and not line.isHidden())
    target.clicked.emit(target._key)
    assert tool.tabs.current() == _id(window, "DESK-10")


# ---- deleting ----


class Deletes:
    """What a host answers to each delete, by user; and what was asked, in order."""

    def __init__(self) -> None:
        self.answers: dict[str, tuple[Outcome, Why | None, str]] = {}
        self.asked: list[str] = []
        self.log_files: set[Path | None] = set()

    def delete(self, scanned: Scan, profile: Profile, account: Account | None = None,
               **more: Any) -> Deleted:  # fmt: skip
        self.asked.append(profile.user)
        self.log_files.add(more.get("log_file"))
        outcome, why, detail = self.answers.get(profile.user, (Outcome.DELETED, None, ""))
        return Deleted(profile, outcome, why, detail)


@pytest.fixture
def deletes(monkeypatch: pytest.MonkeyPatch) -> Deletes:
    deletes = Deletes()
    monkeypatch.setattr(user_profiles, "delete", deletes.delete)
    return deletes


def _answer(monkeypatch: pytest.MonkeyPatch, fill: Callable[[Any], bool]) -> list[Any]:
    """The Delete window (and the quit question) answered by `fill` (True: its action is
    pressed; False: Cancel); the windows opened are kept."""
    opened: list[Any] = []

    def run(dialog: Any) -> int:
        opened.append(dialog)
        if fill(dialog) and dialog.action.isEnabled():
            dialog.accept()
            return int(QDialog.DialogCode.Accepted)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(host_page, "run_modal", run)
    monkeypatch.setattr(tool_ui, "run_modal", run)
    return opened


def _typed(word: str) -> Callable[[Any], bool]:
    def fill(dialog: Any) -> bool:
        if isinstance(dialog, DeleteDialog):
            dialog.word.setText(word)
        return True

    return fill


def test_only_a_row_that_can_be_deleted_has_a_tick_box(window: CapyWindow) -> None:
    tool = _tool(window)
    page = _open(window)
    page.filters.hide_own.setChecked(False)
    tree = page.table.tree
    boxes = {}
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        boxes[item.text(panels.USER)] = item.data(panels.TICK, Qt.ItemDataRole.CheckStateRole)
    assert boxes["EXAMPLE\\ana"] is None and boxes["Public  (unknown)"] is None  # in use; Windows'
    assert all(boxes[user] is not None for user in ("EXAMPLE\\rui", "pedro  (unknown)"))
    assert not tool.bar.delete_button.isEnabled()
    page.table.tick(ANA.ident)  # as a click where there's no box: nothing
    assert page.ticked() == []
    page.table.tick(RUI.ident)
    page.table.tick(BIA.ident)
    assert page.ticked() == [RUI, BIA] and tool.bar.delete_button.isEnabled()
    assert tool.bar.delete_button.text().strip() == "Delete 2 profiles…"
    assert tool.status_label.text() == "DESK-03 · 7 profiles · 5 can be deleted · 2 ticked"
    page.count_sizes()
    assert tool.status_label.text().endswith(" · 2 ticked · 9.0 GB")
    page.filters.leftovers.setChecked(True)  # a tick on a row no longer shown is dropped
    assert page.ticked() == [] and not tool.bar.delete_button.isEnabled()


def test_a_ticked_row_looks_like_something_to_be_careful_with(window: CapyWindow) -> None:
    tool = _tool(window)
    page = _open(window)
    tree = page.table.tree
    assert page.box.name.text() == "User profiles on DESK-03"
    rui = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
               if tree.topLevelItem(i).text(panels.USER) == "EXAMPLE\\rui")  # type: ignore[union-attr]  # fmt: skip
    assert rui is not None
    assert rui.text(panels.STATE) == "Can be deleted" and rui.icon(panels.STATE).isNull()  # no dot
    assert not rui.data(panels.USER, panels.CAREFUL_ROLE)
    header = tree.headerItem()
    assert header.toolTip(panels.TICK) == "Tick to delete" and not header.icon(panels.TICK).isNull()
    page.count_sizes()
    page.table.tick(RUI.ident)
    assert rui.text(panels.STATE) == "Will be deleted" and rui.data(
        panels.USER, panels.CAREFUL_ROLE
    )
    amber = panels.AMBER.lower()
    assert rui.foreground(panels.STATE).color().name() == amber
    dark = not page.table._light()
    assert (rui.foreground(panels.USER).color().name() == amber) == dark  # light: normal text
    assert page.filters.shown.text() == "1 ticked · 3.0 GB" and page.filters.shown.has_bin()
    tree.sortByColumn(panels.TICK, Qt.SortOrder.AscendingOrder)  # a click on its title: nothing
    assert tree.header().sortIndicatorSection() == panels.USED
    page.table.tick(RUI.ident, on=False)
    assert (
        rui.text(panels.STATE) == "Can be deleted" and page.filters.shown.text() == "6 of 7 shown"
    )
    assert not page.filters.shown.has_bin() and tool.tabs.current() != HOSTS


def test_the_count_of_ticks_ends_in_an_ellipsis_rather_than_lose_its_start(
    qapp: QApplication,
) -> None:
    row = panels.FilterRow()
    row.resize(3000, 40)  # room to spare, whatever font an earlier test left
    row.show()
    row.show_count("12 of 15 shown", "3 ticked · 12.4 GB")
    for _turn in range(6):  # the bold font, then the layout's second pass
        qapp.processEvents()
    assert row.shown.shown_text() == "3 ticked · 12.4 GB" and row.shown.toolTip() == ""
    filters = (row.hide_own, row.leftovers, row.since_label, row.since)
    row.resize(sum(w.sizeHint().width() for w in filters) + 160, 40)  # short of room
    for _turn in range(6):  # the bold font, then the layout's second pass
        qapp.processEvents()
    shown = row.shown.shown_text()
    assert shown.endswith("…") and "3 ticked · 12.4 GB".startswith(shown[:-1])
    assert row.shown.toolTip() == "3 ticked · 12.4 GB"
    row.close()


def test_the_delete_window_lists_the_ticked_rows_and_wants_the_word_typed(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes
) -> None:
    tool = _tool(window)
    page = _open(window)
    page.count_sizes()
    page.table.tick(RUI.ident)
    page.table.tick(MARTA.ident)
    seen: list[tuple[Any, ...]] = []

    def look(dialog: DeleteDialog) -> bool:
        table = dialog.table
        listed = [[table.topLevelItem(r).text(c) for c in range(3)]  # type: ignore[union-attr]
                  for r in range(table.topLevelItemCount())]  # fmt: skip
        seen.append((dialog.windowTitle(), dialog.heading.text(), listed, dialog.total.text(),
                     dialog.action.text(), dialog.action.isEnabled(),
                     dialog.cancel.isDefault()))  # fmt: skip
        states = []
        for word in ("delet", "DELETE ME", " delete ", "DELETE"):
            dialog.word.setText(word)
            states.append(dialog.action.isEnabled())
        seen.append(tuple(states))
        dialog.word.clear()
        dialog.accept()  # Enter with the word missing: nothing
        seen.append((dialog.result(),))
        return False  # then Cancel

    _answer(monkeypatch, look)
    tool.bar.delete_button.click()
    assert seen[0] == (
        "Delete profiles from DESK-03",
        "<b>Delete 2 profiles from DESK-03?</b>",
        [
            ["EXAMPLE\\rui", "11/03/2026", "3.0 GB"],
            ["marta.old  (unknown)", "03/11/2025", "0.5 GB"],
        ],
        "2 profiles · 3.5 GB",
        "Delete 2 profiles",
        False,
        True,
    )
    assert seen[1] == (False, False, True, True)  # any case, spaces around it ignored
    assert seen[2] == (0,)
    assert deletes.asked == [] and page.ticked() == [RUI, MARTA]  # cancelled: as before
    assert rows.confirm_word() == "DELETE" and rows.confirms("Delete") and not rows.confirms("")


def test_ticked_rows_are_deleted_one_at_a_time_and_each_says_how_it_ended(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes
) -> None:
    tool = _tool(window)
    page = _open(window)
    page.count_sizes()
    for profile in (RUI, BIA, MARTA):
        page.table.tick(profile.ident)
    deletes.answers = {
        BIA.user: (Outcome.SKIPPED, Why.IN_USE, ""),
        MARTA.user: (Outcome.FAILED, Why.ERROR, "Access is denied."),
    }
    _answer(monkeypatch, _typed("delete"))
    tool.bar.delete_button.click()
    assert deletes.asked == [RUI.user, BIA.user, MARTA.user]
    assert deletes.log_files == {window.paths.user_profiles_log_file}
    states = _states(page)
    assert (states["EXAMPLE\\rui"], states["EXAMPLE\\bia"], states["marta.old  (unknown)"]) == (
        "Deleted", "Skipped", "Failed",
    )  # fmt: skip
    assert states["temp.joao  (unknown)"] == "Can be deleted"  # not ticked: untouched
    assert page.ticked() == [] and not tool.bar.delete_button.isEnabled()
    progress = page.progress
    assert page.side.currentWidget() is progress and progress.over()
    assert progress.title.text() == "Deletion finished"
    assert progress.first.text() == "DESK-03 · 1 deleted, 1 skipped, 1 failed"
    assert progress.second.text().startswith("3.0 GB freed · ")
    assert progress.bar.value() == progress.bar.maximum() == 3
    log = progress.log.toPlainText().splitlines()
    assert len(log) == 6 and log[1].endswith("EXAMPLE\\rui: deleted, 3.0 GB")
    assert log[3].endswith("EXAMPLE\\bia: skipped, signed in to the PC since the scan")
    assert log[5].endswith("marta.old: failed, Access is denied.")
    assert tool.status_label.text() == ("DESK-03 · 1 deleted · 1 skipped · 1 failed · 3.0 GB freed")
    assert _tab_tip(tool, page) == "1 deleted, 1 skipped, 1 failed. See the history."
    assert not progress.cancel_button.isVisibleTo(progress)
    assert tool.bar.scan_button.isEnabled()

    _pick_row(page, "marta.old  (unknown)")  # Details waits behind the panel
    progress.close_button.click()
    assert page.side.currentWidget() is page.details
    assert page.details.shown_value("windows") == "Access is denied."
    assert _states(page)["EXAMPLE\\rui"] == "Deleted"  # results stay until the next scan
    tool.bar.scan_button.click()
    assert _states(page)["EXAMPLE\\rui"] == "Can be deleted"  # the fake PC still has it


def test_while_a_host_deletes_its_tab_wont_close_and_its_rows_always_show(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes, worker: Worker
) -> None:
    tool = _tool(window)
    page = _open(window)
    for profile in (RUI, BIA, MARTA):
        page.table.tick(profile.ident)
    worker.holding = True
    _answer(monkeypatch, _typed("DELETE"))
    tool.bar.delete_button.click()
    progress = page.progress
    assert page.side.currentWidget() is progress and not progress.over()
    assert progress.title.text() == "Deleting profiles"
    assert progress.first.text().startswith("DESK-03 · profile 1 of 3 · since ")
    assert tool.status_label.text() == "DESK-03 · deleting profile 1 of 3"
    assert tool.tabs.bar.tabText(0) == "DESK-03 · 1/3"
    assert _host_row(tool, "DESK-03")[hosts_page.SCAN] == "deleting 1 of 3"
    states = _states(page)
    assert (states["EXAMPLE\\rui"], states["EXAMPLE\\bia"]) == ("Deleting…", "Queued")
    # While it runs: no scan, no tick, no second run, no closing.
    assert not tool.bar.scan_button.isEnabled() and not tool.bar.delete_button.isEnabled()
    assert not tool.bar.sizes_button.isEnabled()
    page.table.tick(BIA.ident, on=False)
    assert BIA in page.ticked()
    assert not tool.close_tab(page.target.key) and tool.tabs.host_keys() == [page.target.key]
    assert window.statusBar().currentMessage().startswith("DESK-03 is deleting profiles")
    tool.close_finished()
    assert tool.tabs.host_keys() == [page.target.key]
    page.filters.leftovers.setChecked(True)  # the run's rows show whatever the filters
    assert {"EXAMPLE\\rui", "EXAMPLE\\bia", "marta.old  (unknown)"} <= set(_users(page))

    progress.cancel_button.click()
    assert not progress.cancel_button.isEnabled() and not progress.over()
    worker.end()  # the current one finishes
    assert deletes.asked == [RUI.user] and worker.held == []  # and no other starts
    assert progress.over() and progress.first.text() == "DESK-03 · 1 deleted"
    assert "cancelled: 2 not started" in progress.log.toPlainText()
    page.filters.leftovers.setChecked(False)
    states = _states(page)
    assert states["EXAMPLE\\bia"] == "Will be deleted" and page.ticked() == [BIA, MARTA]
    assert tool.bar.delete_button.isEnabled()  # the ticks left can be run again
    assert tool.close_tab(page.target.key)


def test_quitting_while_a_host_deletes_asks_and_waits_for_the_profile_under_way(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes, worker: Worker
) -> None:
    tool = _tool(window)
    page = _open(window)
    page.table.tick(RUI.ident)
    page.table.tick(BIA.ident)
    worker.holding = True
    opened = _answer(monkeypatch, _typed("DELETE"))
    tool.bar.delete_button.click()
    assert tool.quit_question(window) is False  # Cancel the rest and quit
    question = opened[-1]
    assert question.heading.text() == "<b>1 host is still deleting profiles</b>"
    assert question.cancel.text() == "Continue"
    assert deletes.asked == [] and page.deleting
    quits: list[bool] = []
    monkeypatch.setattr(window, "quit_app", lambda: quits.append(True))
    worker.end()  # the profile under way ends; the queued one never starts
    assert deletes.asked == [RUI.user] and quits == [True]


def test_how_a_delete_ended_reads_in_the_log_and_in_details() -> None:
    assert rows.ended_text(Deleted(RUI, Outcome.DELETED), None) == "deleted"
    gone = Deleted(RUI, Outcome.SKIPPED, Why.GONE)
    assert rows.ended_text(gone, None) == "skipped, it's no longer there"
    assert rows.result_why(gone) == "Skipped: it was no longer there."
    left = Deleted(OLD, Outcome.FAILED, Why.LEFT, "C:\\Users\\temp.joao\\a.txt: in use")
    assert rows.ended_text(left, 5).endswith("(C:\\Users\\temp.joao\\a.txt: in use)")
    assert rows.result_why(left) == "Failed: some files couldn't be removed."
    assert rows.result_why(Deleted(OLD, Outcome.DELETED)) == "Deleted: the folder."
    assert rows.result_why(Deleted(GONE, Outcome.DELETED)) == (
        "Deleted: the leftover in the registry."
    )
    assert rows.counts_text([]) == ""


def test_open_the_history_says_so_when_there_is_none_yet(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _open(window)
    opened: list[Path] = []
    monkeypatch.setattr(host_page.os, "startfile", opened.append, raising=False)
    page.open_log()
    assert opened == []  # nothing was ever deleted: no file to open
    log_file = window.paths.user_profiles_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("a line\n", encoding="utf-8")
    page.open_log()
    assert opened == [log_file]
