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
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QIcon, QKeyEvent, QMouseEvent, QShowEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QToolButton

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
from capypanel.ui.profiles_tool import host_page, hosts_page, panels, rows, side, work
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
    assert tool.cards.currentWidget() is card and card.name.text() == "DESK-03"
    assert card.status.text().startswith("Offline · checked by Hosts at ")
    # Every value copies on a click, as in Hosts' Details: the name to tell someone, say.
    assert card.values()["Address"] == "192.0.2.13"
    QTest.mouseClick(card.name, Qt.MouseButton.LeftButton)
    assert QApplication.clipboard().text() == "DESK-03"
    assert window.statusBar().currentMessage() == "Copied: DESK-03"


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
    tool.nav.filter_changed.emit()  # All hosts: the whole list, too many to check unasked
    assert calls == []
    doc = window.hosts.document
    assert doc is not None
    tool.nav.select_group(doc.hosts.groups[0].id)  # Clinic, as a click on it
    assert calls == [["DESK-10", "LAB-02"]]  # DESK-03 was checked a moment ago
    tool.hosts_page.search.setText("desk")  # a search alone checks nothing
    assert len(calls) == 1
    tool.hosts_page.search.clear()
    tool.showEvent(QShowEvent())  # opening the tool checks once more what's stale
    assert len(calls) == 2


def test_a_refresh_result_updates_one_row_without_refilling_the_table(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    refills: list[int] = []
    monkeypatch.setattr(tool, "_fill_hosts", lambda: refills.append(1))
    key = _id(window, "DESK-10")
    window.hosts._status_found[key] = (Status.ONLINE, datetime.now(UTC), None)
    window.hosts.host_changed.emit(key)
    window.hosts.checks_changed.emit()  # Hosts sends it once per host checked
    assert refills == [] and _host_row(tool, "DESK-10")[hosts_page.STATUS] == "Online"


def test_the_panels_open_wide_enough_for_long_names(window: CapyWindow) -> None:
    tool = _tool(window)
    assert tool.prefs.get(tool_ui.PANES_KEY) is None  # nothing saved: the first widths
    assert tool.side.minimumWidth() >= panels.RIGHT
    assert tool.inner.sizes()[1] >= panels.DETAILS or tool.inner.sizes()[1] == 0
    long_name = "Ward A - Corridor · 000000 - a very long host name indeed"
    line = side.Line()
    line.show_entry(side.Entry("@x", long_name, "12:57"))
    line.resize(220, 24)
    line.show()
    QApplication.processEvents()
    assert line.words.isVisible() and line.words.width() >= line.words.sizeHint().width()
    assert line.name.shown_text().endswith("…") and line.name.toolTip() == long_name
    line.close()


def test_a_card_never_scrolls_it_counts_what_doesnt_fit(qapp: QApplication) -> None:
    entries = [side.Entry(str(n), f"PC-{n}") for n in range(7)]
    fixed = side.Lines(4, own_more=False)  # the count takes the last line: no taller
    fixed.show_entries(entries, lambda n: f"and {n} more…")
    assert [name for name, _w in fixed.shown()] == ["PC-0", "PC-1", "PC-2", "and 4 more…"]
    fixed.show_entries(entries[:4], lambda n: f"and {n} more…")
    assert [name for name, _w in fixed.shown()] == ["PC-0", "PC-1", "PC-2", "PC-3"]
    own = side.Lines(2, own_more=True)  # the count has a line of its own under the others
    own.show_entries(entries, lambda n: f"and {n} more")
    assert [name for name, _w in own.shown()] == ["PC-0", "PC-1", "and 5 more"]


def test_a_group_picked_while_a_hosts_tab_is_in_front_brings_the_hosts_tab_back(
    window: CapyWindow,
) -> None:
    tool = _tool(window)
    _open(window)
    assert tool.tabs.current() == _id(window, "DESK-03")
    tool.nav.filter_changed.emit()
    assert tool.tabs.current() == HOSTS
    # A click on the group already picked changes no selection, and still goes back.
    tool.switch(_id(window, "DESK-03"))
    item = tool.nav.everything.topLevelItem(0)
    assert item is not None
    tool.nav.everything.itemClicked.emit(item, 0)
    assert tool.tabs.current() == HOSTS
    tool.hosts_page.search.setText("desk-10")  # and it ends a search, as picking one does
    tool.nav.everything.itemClicked.emit(item, 0)
    assert tool.hosts_page.search.text() == "" and len(_hosts(tool)) == 3


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


def test_scan_with_one_host_picked_stays_on_the_hosts_tab(window: CapyWindow, pc: Pc) -> None:
    tool = _tool(window)
    progress = tool.progress
    assert progress.title.text() == "No host in tabs"
    assert progress.summary.text() == ("Double-click a host to open it, or pick hosts and click "
                                       "Scan to scan them here.")  # fmt: skip
    key = _id(window, "DESK-03")
    tool.hosts_page.table.select(key)
    assert tool.bar.scan_button.toolTip() == (
        "Reads DESK-03's profiles in a tab behind; you stay on this list"
    )
    tool.bar.scan_button.click()
    assert tool.tabs.current() == HOSTS and tool.tabs.host_keys() == [key]
    assert (progress.title.text(), progress.summary.text()) == (
        "1 host in tabs", "0 working · 1 done",
    )  # fmt: skip
    tool.bar.scan_button.click()  # its tab is open and done: read again, still from here
    assert tool.tabs.current() == HOSTS and len(pc.scanned) == 2


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
    assert page.ticked_card.title.text() == "No profile ticked"  # the right panel's card
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


def _windows(monkeypatch: pytest.MonkeyPatch, during: Callable[[Any], None] | None = None,
             ) -> list[Any]:  # fmt: skip
    """A profile's window opens without waiting for Close; `during` runs while it's open."""
    opened: list[Any] = []

    def run(dialog: Any) -> int:
        opened.append(dialog)
        if during is not None:
            during(dialog)
        return 0

    monkeypatch.setattr(host_page, "run_modal", run)
    return opened


def test_details_open_in_a_window_and_say_why_a_row_is_in_its_state(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _open(window)
    opened = _windows(monkeypatch)
    _pick_row(page, "marta.old  (unknown)")
    tree = page.table.tree
    QApplication.sendEvent(tree, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                           Qt.KeyboardModifier.NoModifier))  # fmt: skip
    shown = opened[-1]
    assert shown.windowTitle() == "Profile marta.old on DESK-03"
    details = shown.details
    assert details.shown_value("name") == "marta.old"
    assert details.shown_value("sid") == f"{SID}1147"
    assert details.shown_value("path") == "C:\\Users\\marta.old"
    assert details.shown_value("account") == ""  # Windows no longer knows it: "Unknown", muted
    assert details.shown_value("used") == "03/11/2025"
    assert shown.close_button.isDefault() and shown.tick.isEnabled() and not shown.tick.isChecked()
    # The (i) at the end of the clicked row opens it too; on another row the click only picks.
    tree.resize(1100, 446)  # wide enough for every column, as in a real window
    QApplication.processEvents()
    item = tree.currentItem()
    assert item is not None
    cell = tree.visualItemRect(item)
    state = QRect(tree.columnViewportPosition(panels.STATE), cell.top(),
                  tree.columnWidth(panels.STATE), cell.height())  # fmt: skip
    where = panels.info_rect(state).center()
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=where)
    QApplication.processEvents()  # it opens once the table has had its click
    assert len(opened) == 2 and opened[-1].windowTitle() == "Profile marta.old on DESK-03"
    other = tree.itemBelow(item) or tree.itemAbove(item)
    assert other is not None
    above = QPoint(where.x(), tree.visualItemRect(other).center().y())
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=above)
    QApplication.processEvents()
    picked = page.table.selected()
    assert len(opened) == 2 and picked is not None and picked != MARTA
    # And the row's right-click: Details…
    monkeypatch.setattr(panels, "popup", lambda menu, _where: menu.actions()[0].trigger())
    page.table._menu(tree.visualItemRect(item).center())
    assert len(opened) == 3

    def tick(dialog: Any) -> None:  # its tick is the row's own
        dialog.tick.setChecked(True)
        assert dialog.tick.isChecked() and page.table.is_ticked(MARTA.ident)

    _windows(monkeypatch, tick)
    page.show_details(MARTA.ident)
    assert page.ticked() == [MARTA]
    opened = _windows(monkeypatch)
    page.show_details(ANA.ident)  # signed in: no tick to set
    details = opened[-1].details
    assert details.shown_value("account") == "EXAMPLE\\ana" and not opened[-1].tick.isEnabled()
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
    progress = tool.progress
    assert (progress.title.text(), progress.summary.text()) == (
        "6 hosts in tabs", "0 working · 6 done",
    )  # fmt: skip
    shown = progress.lines.shown()  # more tabs than lines: three, then the rest as a count
    assert len(shown) == 4 and shown[-1] == ("and 3 more…", "")


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
    window: CapyWindow, pc: Pc, caplog: pytest.LogCaptureFixture
) -> None:
    tool = _tool(window)
    pc.answers["192.0.2.13"] = RemoteError(Reason.UNREACHABLE)
    page = _open(window)
    assert "User profiles scan on DESK-03 failed: RemoteError" in caplog.text  # in the log too
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
    assert tool.view_actions() == [[tool.show_groups, tool.show_tags, tool.show_details]]
    tool.show_tags.setChecked(False)  # as in Hosts: the Tags panel can be hidden
    assert tool.nav.tags.isHidden() and tool.prefs[tool_ui.SHOWN_KEY]["tags"] is False
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


def test_a_middle_click_closes_a_tab_without_going_to_it(window: CapyWindow) -> None:
    tool = _tool(window)
    desk, other = _open(window), _open(window, "DESK-10", focus=False)
    bar = tool.tabs.bar
    where = bar.tabRect(tool.tabs.index_of(other.target.key)).center()
    went: list[str] = []
    tool.tabs.picked.connect(went.append)
    QTest.mouseClick(bar, Qt.MouseButton.MiddleButton, pos=where)
    assert tool.tabs.host_keys() == [desk.target.key] and went == []
    assert tool.tabs.current() == desk.target.key


def test_the_arrows_that_scroll_the_tabs_can_be_seen(window: CapyWindow) -> None:
    tool = _tool(window)
    page = _open(window)
    assert page.filters.shown.text() == "6 of 7 shown" and page.filters.shown._short == "6 of 7"
    found = {b.objectName(): b for b in tool.tabs.bar.findChildren(QToolButton)
             if b.objectName().startswith("Scroll")}  # fmt: skip
    assert set(found) == {"ScrollLeftButton", "ScrollRightButton"}
    for button in found.values():  # a chevron on the window's colour, never see-through
        assert not button.icon().isNull() and "padding: 0px" in button.styleSheet()
        assert "background: #" in button.styleSheet()
        # At the end the bar is already at, its arrow is drawn muted, not just left to the style.
        size = QSize(16, 16)
        normal = button.icon().pixmap(size, QIcon.Mode.Normal).toImage()
        assert button.icon().pixmap(size, QIcon.Mode.Disabled).toImage() != normal


def test_a_tab_closed_while_its_scan_runs_ignores_the_answer(
    window: CapyWindow, worker: Worker
) -> None:
    tool = _tool(window)
    worker.holding = True
    page = _open(window)
    assert page.stage is Stage.SCANNING and len(worker.held) == 1
    assert _host_row(tool, "DESK-03")[hosts_page.SCAN] == "scanning…"
    assert tool.close_tab(page.target.key)
    assert _host_row(tool, "DESK-03")[hosts_page.SCAN] == ""  # no "scanning…" left on its row
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # its widgets are gone
    worker.end()  # the read ends after: dropped, not shown in a deleted tab
    assert tool.tabs.host_keys() == [] and tool.pool.waiting(page) == 0


def test_progress_lists_the_hosts_in_tabs_by_where_they_are(
    window: CapyWindow, worker: Worker, pc: Pc
) -> None:
    tool = _tool(window)
    progress = tool.progress
    assert not progress.bar.isVisibleTo(progress)  # nothing open yet
    height = progress.height()
    pc.answers["192.0.2.20"] = RemoteError(Reason.UNREACHABLE)
    _open(window, "DESK-10", focus=False)
    worker.holding = True
    page = _open(window, focus=False)
    assert (progress.caption.text(), progress.title.text()) == ("PROGRESS", "2 hosts in tabs")
    assert progress.summary.text() == "1 working · 1 done"
    # One line per tab, the working ones first, whatever the tabs' order.
    assert progress.lines.shown() == [("DESK-03", "scanning…"), ("DESK-10", "didn't answer")]
    assert progress.height() == height  # one fixed height: nothing under it jumps
    tool.switch(page.target.key)  # the same card on a host's tab
    assert progress.isVisibleTo(tool.side) and tool.cards.currentWidget() is page.side
    target = next(line for line in progress.lines.slots if line.name.text() == "DESK-10")
    target.clicked.emit(target.key())
    assert tool.tabs.current() == _id(window, "DESK-10")


def test_the_right_panel_lists_what_is_ticked_and_deletes_from_its_foot(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: "Deletes"
) -> None:
    tool = _tool(window)
    page = _open(window)
    card, foot = page.ticked_card, page.foot
    assert tool.cards.currentWidget() is page.side and page.cards.currentWidget() is card
    assert (card.caption.text(), card.title.text()) == ("TICKED TO DELETE", "No profile ticked")
    assert card.hint.text() == "Tick in the table: the box, Space or a double-click on the row."
    assert foot.delete_button.text().strip() == "Delete profiles…"
    assert not foot.delete_button.isEnabled() and foot.delete_button.height() == side.FOOT
    assert foot.delete_button.toolTip() == "Tick profiles in the table to delete"
    page.count_sizes()
    page.table.tick(RUI.ident)
    page.table.tick(MARTA.ident)
    assert card.title.text() == "2 profiles · 3.5 GB"
    assert card.lines.shown() == [("EXAMPLE\\rui", "3.0 GB"), ("marta.old  (unknown)", "0.5 GB")]
    line = card.lines.slots[1]
    line.clicked.emit(line.key())  # a click on a line shows the profile in the table
    assert page.table.selected() == MARTA
    assert foot.delete_button.isEnabled()
    assert foot.delete_button.text().strip() == tool.bar.delete_button.text().strip()
    assert foot.delete_button.text().strip() == "Delete 2 profiles…"
    # The Hosts tab's card says which tabs have ticks waiting; a click goes there.
    host_card = tool.hosts_page.host_card
    tool.switch(HOSTS)
    assert host_card.ticked.shown() == [("DESK-03", "2 profiles · 3.5 GB")]
    assert host_card.ticked.isVisibleTo(host_card)
    host_card.ticked.slots[0].clicked.emit(host_card.ticked.slots[0].key())
    assert tool.tabs.current() == page.target.key
    opened = _answer(monkeypatch, _typed("delete"))
    foot.delete_button.click()  # the same question as the toolbar's
    assert isinstance(opened[0], DeleteDialog) and deletes.asked == [RUI.user, MARTA.user]
    assert not host_card.ticked.isVisibleTo(host_card)  # nothing ticked any more


def test_a_right_click_on_hosts_opens_scans_refreshes_and_copies(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, pc: Pc
) -> None:
    tool = _tool(window)
    menus: list[Any] = []
    monkeypatch.setattr(tool_ui, "popup", lambda menu, _where: menus.append(menu))
    key = _id(window, "DESK-03")
    tool.hosts_page.table.select(key)
    tool._hosts_menu(QPoint(0, 0))
    actions = menus[-1].actions()
    assert [a.text() for a in actions] == [
        "&Open", "&Scan", "&Refresh host", "", "Copy &name", "Copy &address",
    ]  # fmt: skip
    actions[4].trigger()
    assert QApplication.clipboard().text() == "DESK-03"
    assert window.statusBar().currentMessage() == "Copied: DESK-03"
    actions[5].trigger()
    assert QApplication.clipboard().text() == "192.0.2.13"
    actions[1].trigger()  # Scan: behind, as the toolbar's
    assert tool.tabs.current() == HOSTS and tool.tabs.host_keys() == [key]
    actions[0].trigger()  # Open: as a double-click
    assert tool.tabs.current() == key and len(pc.scanned) == 1
    tool.switch(HOSTS)
    for index in range(tool.hosts_page.table.tree.topLevelItemCount()):
        item = tool.hosts_page.table.tree.topLevelItem(index)
        assert item is not None
        item.setSelected(True)
    tool._hosts_menu(QPoint(0, 0))
    assert [a.text() for a in menus[-1].actions()][1:3] == ["&Scan 3 hosts", "&Refresh 3 hosts"]
    menus[-1].actions()[4].trigger()
    assert QApplication.clipboard().text().split("\n") == ["DESK-03", "DESK-10", "LAB-02"]


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
    assert (
        header.toolTip(panels.TICK).startswith("Tick to delete")
        and not header.icon(panels.TICK).isNull()
    )
    page.count_sizes()
    page.table.tick(RUI.ident)
    assert rui.text(panels.STATE) == "Will be deleted" and rui.data(
        panels.USER, panels.CAREFUL_ROLE
    )
    amber = panels.amber()  # the theme's: it reads as text in the light themes too
    assert rui.foreground(panels.STATE).color().name() == amber
    assert rui.foreground(panels.USER).color().name() == amber
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
        # Once lit, the amber button has the keyboard and is the default: Enter deletes.
        seen.append((dialog.action.isDefault(), dialog.cancel.isDefault(),
                     dialog.focusWidget() is dialog.action))  # fmt: skip
        dialog.word.clear()
        seen.append((dialog.action.isDefault(), dialog.cancel.isDefault()))
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
    assert seen[2] == (True, False, True)
    assert seen[3] == (False, True)  # the word gone: Cancel is the default again
    assert seen[4] == (0,)
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
    card, foot = page.run_card, page.foot
    assert page.cards.currentWidget() is card and card.over()
    assert card.caption.text() == "DELETION FINISHED"
    assert card.title.text() == "1 deleted, 1 skipped, 1 failed"
    assert card.second.text().startswith("3.0 GB freed · ")
    assert card.bar.value() == card.bar.maximum() == 3
    assert card.lines.shown() == [
        ("EXAMPLE\\rui", "deleted · 3.0 GB"),
        ("EXAMPLE\\bia", "skipped"),
        ("marta.old  (unknown)", "failed"),
    ]  # a line per profile of the run; why it ended so is in its tooltip
    tips = [line.toolTip() for line in card.lines.slots[:3]]
    assert tips[0] == "deleted, 3.0 GB"
    assert tips[1] == "skipped, signed in to the PC since the scan"
    assert tips[2] == "failed, Access is denied."
    assert tool.status_label.text() == ("DESK-03 · 1 deleted · 1 skipped · 1 failed · 3.0 GB freed")
    assert _tab_tip(tool, page) == "1 deleted, 1 skipped, 1 failed. See the history."
    assert foot.cancel_button.isHidden() and not foot.delete_button.isEnabled()
    assert card.log_button.isVisibleTo(card) and not card.note.isVisibleTo(card)
    assert tool.bar.scan_button.isEnabled()

    card.close_button.click()  # what's ticked shows again
    assert page.cards.currentWidget() is page.ticked_card
    opened = _windows(monkeypatch)  # how a row ended is in its window
    page.show_details(MARTA.ident)
    assert opened[-1].details.shown_value("windows") == "Access is denied."
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
    card, foot = page.run_card, page.foot
    assert page.cards.currentWidget() is card and not card.over()
    assert card.caption.text() == "DELETING PROFILES"
    assert card.title.text() == "1 of 3 profiles" and card.second.text().startswith("since ")
    assert card.lines.shown() == [
        ("EXAMPLE\\rui", "deleting…"),
        ("EXAMPLE\\bia", "queued"),
        ("marta.old  (unknown)", "queued"),
    ]
    # The foot button is a plain Cancel the rest while it runs.
    assert foot.delete_button.isHidden() and not foot.cancel_button.isHidden()
    assert foot.cancel_button.text().strip() == "Cancel the rest"
    assert tool.hosts_page.host_card.ticked.shown() == [("DESK-03", "deleting 1 of 3")]
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

    foot.cancel_button.click()
    assert not foot.cancel_button.isEnabled() and not card.over()
    assert card.lines.shown() == [("EXAMPLE\\rui", "deleting…")]  # the queued ones left the run
    worker.end()  # the current one finishes
    assert deletes.asked == [RUI.user] and worker.held == []  # and no other starts
    assert card.over() and card.title.text() == "1 deleted"
    assert foot.cancel_button.isHidden() and foot.delete_button.isEnabled()
    assert foot.delete_button.text().strip() == "Delete 2 profiles…"
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


# ---- narrow windows, and the box of the hosts on show ----


def test_at_a_narrow_width_the_tables_fit_their_box_and_the_last_column_stays(
    window: CapyWindow,
) -> None:
    tool = _tool(window)
    table = tool.hosts_page.table
    tree = table.tree
    table.squeeze.apply(1200)
    full = tree.columnWidth(hosts_page.NAME)
    assert tree.headerItem().text(hosts_page.DELETABLE) == "Can be deleted"
    least = table._scan_least()
    room = least + sum(tree.columnWidth(c) for c in range(hosts_page.SCAN)) - 40
    table.squeeze.apply(room)
    assert tree.headerItem().text(hosts_page.DELETABLE) == "Deletable"  # one short word
    assert tree.headerItem().toolTip(hosts_page.DELETABLE).endswith("can be deleted")
    assert tree.columnWidth(hosts_page.NAME) <= full  # Name gives up room first
    assert tree.columnWidth(hosts_page.SCAN) >= least  # where a host stands is never cut
    widths = sum(tree.columnWidth(c) for c in range(hosts_page.SCAN + 1))
    assert widths <= room  # nothing to scroll sideways
    item = tree.topLevelItem(0)
    assert item is not None and item.toolTip(hosts_page.NAME) == item.text(hosts_page.NAME)

    page = _open(window)
    page.table.squeeze.apply(1200)
    ptree = page.table.tree
    user, kind = ptree.columnWidth(panels.USER), ptree.columnWidth(panels.KIND)
    page.table.squeeze.apply(430)
    assert ptree.columnWidth(panels.USER) == 110 and ptree.columnWidth(panels.KIND) <= kind
    assert ptree.columnWidth(panels.USER) < user
    assert ptree.columnWidth(panels.TICK) == 34  # the ticks never shrink
    assert ptree.columnWidth(panels.STATE) >= page.table._state_least()


def test_the_count_drops_the_size_before_it_ends_in_an_ellipsis(qapp: QApplication) -> None:
    count = panels.Count()
    count.show_count("3 ticked · 12.4 GB", True, "3 ticked", "3")
    count.show()
    for _turn in range(4):
        qapp.processEvents()
    metrics = count.fontMetrics()
    bin_room = count.BIN + count.GAP
    count.resize(metrics.horizontalAdvance("3 ticked · 12.4 GB") + bin_room + 4, 20)
    assert count.shown_text() == "3 ticked · 12.4 GB"
    count.resize(metrics.horizontalAdvance("3 ticked") + bin_room + 4, 20)
    assert count.shown_text() == "3 ticked" and count.toolTip() == "3 ticked · 12.4 GB"
    count.resize(bin_room + 20, 20)  # no room for the word: the bin and the number
    assert count.shown_text() == "3" and count.toolTip() == "3 ticked · 12.4 GB"
    # The plain count loses "shown" before any word is cut; the whole text in its tooltip.
    count.show_count("12 of 15 shown", False, "12 of 15")
    count.resize(metrics.horizontalAdvance("12 of 15 shown") - 4, 20)
    assert count.shown_text() == "12 of 15" and count.toolTip() == "12 of 15 shown"
    count.show_count("12 of 15 shown", False)  # nothing shorter to fall back on: "…"
    count.resize(40, 20)
    assert count.shown_text().endswith("…")
    count.close()


def test_with_no_single_host_picked_the_box_describes_the_hosts_on_show(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    card = tool.hosts_page.host_card
    assert card.heading.text() == "HOSTS SHOWN" and card.name.text() == "All hosts"
    assert card.status.text() == "Status not checked yet: use Refresh all"
    values = [v.text() for v in card._values]
    assert values == ["—", "3", "0 of 3", "—"]
    now = datetime.now(UTC)
    window.hosts._status_found[_id(window, "DESK-03")] = (Status.ONLINE, now, None)
    window.hosts._status_found[_id(window, "DESK-10")] = (Status.OFFLINE, now, None)
    monkeypatch.setattr(window.hosts, "check_progress", lambda: (2, 3))
    window.hosts.checks_changed.emit()  # a Refresh under way
    assert card.status.text() == "Refreshing status: 2 of 3…"
    assert [v.text() for v in card._values][:2] == ["1 online · 1 offline", "1"]
    monkeypatch.setattr(window.hosts, "check_progress", lambda: None)
    window.hosts.checks_changed.emit()
    assert card.status.text().startswith("Status checked by Hosts at ")
    _open(window, focus=False)  # a scan fills the rest
    assert [v.text() for v in card._values][2:] == ["1 of 3", "5"]
    tool.hosts_page.table.select(_id(window, "DESK-03"))  # one host picked: its own box
    assert card.heading.text() == "SELECTED HOST"
    tool.hosts_page.search.setText("no such host")  # nothing on show: it says so, no rows
    assert card.heading.text() == "HOSTS SHOWN" and card.status.text() == "No host shown"
    assert all(v.isHidden() for v in card._values)
    tool.hosts_page.search.clear()
    assert not any(v.isHidden() for v in card._values)


def test_a_size_being_counted_shows_its_bytes_so_far(
    window: CapyWindow, worker: Worker, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    page = _open(window)
    heard: dict[str, Callable[[int], None]] = {}

    def size(scanned: Scan, profile: Profile, account: Any = None, **more: Any) -> int:
        heard[profile.user] = more["progress"]
        return SIZES.get(profile.ident, 0)

    monkeypatch.setattr(user_profiles, "profile_size", size)
    worker.holding = True
    page.count_sizes()
    assert tool.status_label.text() == "DESK-03 · calculating sizes: 0 of 5"
    worker.held.pop(0)()  # rui's count ran to its end: 3 GB
    worker.held[0]()  # the next one is under way; run it again below to hear from it
    name = next(user for user in heard if user != RUI.user)
    heard[name](2 * GB)  # its count reports from its own thread: 2 GB so far
    page._show_so_far()  # what the ticker does every moment
    sizes = [row[panels.SIZE] for row in page.table.texts()]
    assert "2.0 GB…" in sizes and "3.0 GB" in sizes
    assert tool.status_label.text().startswith("DESK-03 · calculating sizes: ")
    assert tool.status_label.text().endswith(" so far")
    page.stop_sizes()
    assert not page._ticker.isActive()


def test_space_and_a_double_click_tick_the_row_the_keyboard_is_on(window: CapyWindow) -> None:
    page = _open(window)
    tree = page.table.tree
    _pick_row(page, "EXAMPLE\\rui")
    space = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(tree, space)
    assert page.ticked() == [RUI]
    QApplication.sendEvent(tree, space)  # again: unticked
    assert page.ticked() == []
    item = tree.currentItem()
    assert item is not None
    tree.itemDoubleClicked.emit(item, panels.USER)
    assert page.ticked() == [RUI]
    tree.itemDoubleClicked.emit(item, panels.TICK)  # on the box: its own clicks did it
    assert page.ticked() == [RUI]
    _pick_row(page, "EXAMPLE\\ana")  # in use: no box, so nothing to tick
    QApplication.sendEvent(tree, space)
    assert page.ticked() == [RUI]


def test_a_powershell_blocked_on_this_pc_is_named_as_such(window: CapyWindow, pc: Pc) -> None:
    from capypanel.core.remote.inventory import PowerShellBlocked
    from capypanel.ui.hosts_tool.details import facts_error_text
    from capypanel.ui.hosts_tool.runner import reason_text

    blocked = PowerShellBlocked(PermissionError(13, "Access is denied"))
    pc.answers["192.0.2.13"] = blocked
    page = _open(window)
    card = page.card
    assert card is not None and card.heading.text() == "PowerShell couldn't start on your PC"
    assert "An antivirus may block it." in card.body.text()
    assert _tool(window).status_label.text() == "DESK-03 · PowerShell blocked on your PC"
    assert [b.text() for b in card.buttons] == ["Try again"]  # another account won't help
    assert "antivirus" in facts_error_text(blocked) and "antivirus" in reason_text(blocked)
    assert (
        "on DESK-03 to read" not in card.body.text()
        and "on your PC to read DESK-03" in card.body.text()
    )


def test_a_date_windows_cant_show_in_local_time_never_breaks_a_view() -> None:
    from capypanel.ui import checks

    ancient = datetime(1601, 1, 1, tzinfo=UTC)  # what a zeroed registry time reads as
    assert checks.local(ancient) == ancient  # left as it is, no crash
    assert rows.date_text(ancient) in ("01/01/1601",)
    assert rows.date_text(datetime(2025, 3, 11, 12, tzinfo=UTC)) == "03/11/2025"


def test_every_icon_the_code_names_has_its_file() -> None:
    """An icon drawn only while painting (the row's (i)) has no other test that would miss it."""
    import re

    from capypanel.ui.icons import TABLER_DIR

    source = Path(tool_ui.__file__).parents[1]
    named: set[str] = set()
    for file in source.rglob("*.py"):
        named.update(re.findall(r'tabler_icon\(\s*"([a-z0-9-]+)"', file.read_text("utf-8")))
    assert "info-circle" in named
    assert not {name for name in named if not (TABLER_DIR / f"{name}.svg").is_file()}
