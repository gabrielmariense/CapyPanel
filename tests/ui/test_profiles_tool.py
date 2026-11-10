"""The User profiles tool's page: the PCs it takes from Hosts' open list, the Scan button that
names its target, the profiles table with its filters and order, a profile's details, sizes, and
what a failed scan says. Nothing here reaches a PC: the scan and the sizes are answered by hand."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.remote import user_profiles
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.user_profiles import (
    Deleted,
    Kind,
    Outcome,
    Profile,
    Scan,
    State,
    Why,
)
from capypanel.ui.profiles_tool import panels, rows
from capypanel.ui.profiles_tool import tool as tool_ui
from capypanel.ui.profiles_tool.panels import DeleteDialog
from capypanel.ui.profiles_tool.rows import Filters
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
    """The PC the tool talks to: what a scan and a size answer, and what was asked."""

    def __init__(self) -> None:
        self.answer: Scan | BaseException = Scan("192.0.2.13", "C:\\Users", ROWS)
        self.scanned: list[tuple[str, Account | None]] = []
        self.sized: list[str] = []

    def scan(self, host: str, account: Account | None = None, **_more: object) -> Scan:
        self.scanned.append((host, account))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def size(self, scanned: Scan, profile: Profile, account: Account | None = None,
             **_more: object) -> int | None:  # fmt: skip
        self.sized.append(profile.user)
        return SIZES.get(profile.ident, 0)


def _at_once(
    work: Callable[[], Any], done: Callable[[Any], None], failed: Callable[[BaseException], None]
) -> None:
    """The tool's background work, done on the spot."""
    try:
        value = work()
    except Exception as e:  # noqa: BLE001 - as the tool's own worker does
        failed(e)
    else:
        done(value)


@pytest.fixture
def pc(monkeypatch: pytest.MonkeyPatch) -> Pc:
    pc = Pc()
    monkeypatch.setattr(user_profiles, "scan", pc.scan)
    monkeypatch.setattr(user_profiles, "profile_size", pc.size)
    monkeypatch.setattr(tool_ui, "windows_account", lambda: "EXAMPLE\\support")
    return pc


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, pc: Pc) -> Iterator[CapyWindow]:
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
    tool._start = _at_once  # type: ignore[method-assign]
    return tool


def _pcs(tool: ProfilesTool) -> list[str]:
    tree = tool.pcs.tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]  # type: ignore[union-attr]


def _pick(tool: ProfilesTool, name: str) -> None:
    tree = tool.pcs.tree
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item is not None and item.text(0) == name:
            tree.setCurrentItem(item)
            return
    raise AssertionError(name)


def _pick_row(tool: ProfilesTool, user: str) -> None:
    tree = tool.table.tree
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        if item is not None and item.text(panels.USER) == user:
            tree.setCurrentItem(item)
            return
    raise AssertionError(user)


def _users(tool: ProfilesTool) -> list[str]:
    return [row[panels.USER] for row in tool.table.texts()]


def _scanned(tool: ProfilesTool, name: str = "DESK-03") -> ProfilesTool:
    _pick(tool, name)
    tool.pcs.scan_button.click()
    return tool


# ---- the PCs ----


def test_it_is_the_third_tool_and_lists_the_pcs_of_hosts_open_list(
    window: CapyWindow, tmp_path: Path
) -> None:
    tool = _tool(window)
    assert list(window.tools) == ["hosts", "printers", "profiles"]
    assert (tool.tool_name(), tool.ICON) == ("User profiles", "profile-card")
    assert tool.pcs.picker.text() == "clinic"
    assert _pcs(tool) == ["DESK-03", "DESK-10", "LAB-02"]  # in natural order; reachable ones
    assert tool.status_label.text() == "No PC scanned"
    assert tool.card is not None and tool.card.heading.text() == "Choose a PC"
    assert not tool.bar.rescan_button.isEnabled() and not tool.bar.sizes_button.isEnabled()

    hl, group = HostList().add_group("Lab")
    hl, _host = hl.add_host("LAB-07", group.id, address="198.51.100.7")
    other = tmp_path / "lab.json"
    listfile.save(other, hl, expected=None)
    window.hosts.open_list(other)  # Hosts opens another list: this page follows
    assert tool.pcs.picker.text() == "lab" and _pcs(tool) == ["LAB-07"]
    choices = {name: current for _path, name, current in tool.pcs._choices()}
    assert (choices["clinic"], choices["lab"]) == (False, True)  # among Hosts' other lists
    tool.pcs.list_picked.emit(tmp_path / "clinic.json")  # and its dropdown opens one in Hosts
    assert window.hosts.document is not None and window.hosts.document.path.name == "clinic.json"
    assert _pcs(tool) == ["DESK-03", "DESK-10", "LAB-02"]


def test_the_search_narrows_the_pcs_by_name_or_address(window: CapyWindow) -> None:
    tool = _tool(window)
    tool.pcs.search.setText("desk")
    assert _pcs(tool) == ["DESK-03", "DESK-10"]
    tool.pcs.search.setText("0.2.20")
    assert _pcs(tool) == ["DESK-10"]
    tool.pcs.search.clear()
    assert len(_pcs(tool)) == 3


def test_scan_names_its_target_the_pc_picked_or_the_one_typed(window: CapyWindow) -> None:
    tool = _tool(window)
    button, other = tool.pcs.scan_button, tool.pcs.other
    assert (button.text(), button.isEnabled()) == ("Scan", False)
    _pick(tool, "DESK-03")
    assert (button.text(), button.isEnabled()) == ("Scan DESK-03", True)
    other.setText("192.0.2.50")
    other.textEdited.emit("192.0.2.50")  # typing clears the list's pick
    assert button.text() == "Scan 192.0.2.50" and not tool.pcs.tree.selectedItems()
    target = tool.pcs.target()
    assert target is not None and (target.key, target.address) == ("@192.0.2.50", "192.0.2.50")
    _pick(tool, "DESK-10")  # picking empties the field
    assert other.text() == "" and button.text() == "Scan DESK-10"
    other.setText("desk-03")
    other.textEdited.emit("desk-03")  # a PC of the list, typed: that PC, with its own account
    target = tool.pcs.target()
    assert target is not None and (target.name, target.address) == ("DESK-03", "192.0.2.13")
    assert not target.key.startswith("@")


def test_typing_never_scans_by_itself_and_a_double_click_does(window: CapyWindow, pc: Pc) -> None:
    tool = _tool(window)
    tool.pcs.other.setText("192.0.2.50")
    tool.pcs.other.textEdited.emit("192.0.2.50")
    tool.pcs.other.returnPressed.emit()
    assert pc.scanned == [] and not tool.pcs.scan_button.autoDefault()
    _pick(tool, "DESK-03")
    item = tool.pcs.tree.currentItem()
    assert item is not None
    tool.pcs.tree.itemDoubleClicked.emit(item, 0)
    assert pc.scanned == [("192.0.2.13", None)]


# ---- a scanned PC ----


def test_a_scan_shows_the_pc_its_profiles_and_what_can_be_deleted(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _scanned(_tool(window))
    assert pc.scanned == [("192.0.2.13", None)]
    assert tool.header.name.text() == "DESK-03"
    about = tool.header.about.text()
    assert about.startswith("192.0.2.13 · read at ") and about.endswith(" · as EXAMPLE\\support")
    assert tool.header.shown.text() == "6 of 7 shown"  # Windows' own is hidden at first
    assert tool.table.texts() == [  # the newest use first; rows with no date last
        ["", "EXAMPLE\\ana", "11/10/2026", "", "Profile", "In use"],
        ["", "EXAMPLE\\rui", "11/03/2026", "", "Profile", "Ready"],
        ["", "EXAMPLE\\bia", "08/14/2026", "", "Profile", "Ready"],
        ["", "marta.old  (unknown)", "03/11/2025", "", "Profile", "Ready"],
        ["", "pedro  (unknown)", "—", "", "Registry entry, no folder", "Ready"],
        ["", "temp.joao  (unknown)", "—", "", "Folder, no registry entry", "Ready"],
    ]
    assert tool.status_label.text() == "DESK-03 · 7 profiles · 5 can be deleted"
    assert tool.bar.rescan_button.isEnabled() and tool.bar.sizes_button.isEnabled()
    assert tool.details.shown_value("path") == ""  # nothing picked yet


def test_the_filters_narrow_the_rows(window: CapyWindow) -> None:
    tool = _scanned(_tool(window))
    tool.header.hide_own.setChecked(False)
    assert "Public" in "".join(_users(tool)) and tool.header.shown.text() == "7 of 7 shown"
    tool.header.leftovers.setChecked(True)
    assert _users(tool) == ["pedro  (unknown)", "Public  (unknown)", "temp.joao  (unknown)"]
    tool.header.hide_own.setChecked(True)
    assert tool.header.shown.text() == "2 of 7 shown"
    choices = [tool.header.since.itemText(i) for i in range(tool.header.since.count())]
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
    tool = _scanned(_tool(window))
    tool.count_sizes()
    tree = tool.table.tree
    tree.sortByColumn(panels.SIZE, Qt.SortOrder.DescendingOrder)
    assert _users(tool)[:3] == ["EXAMPLE\\bia", "EXAMPLE\\rui", "marta.old  (unknown)"]
    tree.sortByColumn(panels.USED, Qt.SortOrder.AscendingOrder)  # the oldest on top
    assert _users(tool)[2:4] == ["marta.old  (unknown)", "EXAMPLE\\bia"]
    tree.sortByColumn(panels.USER, Qt.SortOrder.AscendingOrder)
    assert _users(tool)[:2] == ["EXAMPLE\\ana", "EXAMPLE\\bia"]


def test_details_say_why_a_row_is_in_its_state(window: CapyWindow) -> None:
    tool = _scanned(_tool(window))
    _pick_row(tool, "marta.old  (unknown)")
    details = tool.details
    assert details.shown_value("name") == "marta.old"
    assert details.shown_value("sid") == f"{SID}1147"
    assert details.shown_value("path") == "C:\\Users\\marta.old"
    assert details.shown_value("account") == ""  # Windows no longer knows it: "Unknown", muted
    assert details.shown_value("used") == "03/11/2025"
    _pick_row(tool, "EXAMPLE\\ana")
    assert details.shown_value("account") == "EXAMPLE\\ana"
    assert rows.state_why(ANA, "C:\\Users").startswith("This person is signed in now.")
    outside = _row("svc", 1150, None, state=State.OUTSIDE, path="D:\\Perfis\\svc")
    assert rows.state_why(outside, "C:\\Users").endswith("profiles inside C:\\Users.")


# ---- sizes ----


def test_sizes_are_counted_on_demand_for_the_rows_shown_that_have_a_folder(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _scanned(_tool(window))
    assert pc.sized == [] and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    tool.count_sizes()
    assert "pedro" not in pc.sized and "Public" not in pc.sized  # no folder; hidden
    assert len(pc.sized) == 5
    sizes = {row[panels.USER]: row[panels.SIZE] for row in tool.table.texts()}
    assert sizes["EXAMPLE\\rui"] == "3.0 GB" and sizes["marta.old  (unknown)"] == "0.5 GB"
    assert sizes["temp.joao  (unknown)"] == "40 MB" and sizes["pedro  (unknown)"] == ""
    assert tool.status_label.text() == "DESK-03 · 7 profiles · 5 can be deleted"
    assert not tool.counting() and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    tool.count_sizes()  # nothing left to count
    assert len(pc.sized) == 5


def test_counting_can_be_stopped_and_what_was_counted_stays(window: CapyWindow, pc: Pc) -> None:
    tool = _scanned(_tool(window))
    held: list[Callable[[], None]] = []

    def later(work: Callable[[], Any], done: Callable[[Any], None], failed: Any) -> None:
        held.append(lambda: done(work()))

    tool._start = later  # type: ignore[method-assign]
    tool.count_sizes()
    assert len(held) == tool_ui.SIZES_AT_ONCE and tool.counting()
    assert tool.bar.sizes_button.text().strip() == "Stop counting"
    assert [row[panels.SIZE] for row in tool.table.texts()].count("counting…") == 4
    held.pop(0)()  # one ends; the next one starts
    assert len(held) == 4 and "0 MB" in "".join(r[panels.SIZE] for r in tool.table.texts())
    tool.toggle_sizes()  # Stop
    assert not tool.counting() and tool.bar.sizes_button.text().strip() == "Calculate sizes"
    assert "counting…" not in [row[panels.SIZE] for row in tool.table.texts()]
    for late in held:  # the ones under way end later: dropped
        late()
    assert sum(size is not None for size in tool._sizes.values()) == 1


def test_scanning_the_same_pc_again_keeps_the_sizes_of_rows_still_there(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _scanned(_tool(window))
    tool.count_sizes()
    pc.answer = Scan("192.0.2.13", "C:\\Users", (ANA, RUI, MARTA))  # bia was deleted meanwhile
    tool.bar.rescan_button.click()
    assert len(pc.scanned) == 2
    sizes = {row[panels.USER]: row[panels.SIZE] for row in tool.table.texts()}
    assert sizes == {"EXAMPLE\\ana": "0 MB", "EXAMPLE\\rui": "3.0 GB",
                     "marta.old  (unknown)": "0.5 GB"}  # fmt: skip
    pc.answer = Scan("192.0.2.20", "C:\\Users", (RUI,))
    _scanned(tool, "DESK-10")  # another PC: nothing carried over
    assert tool.table.texts()[0][panels.SIZE] == ""


# ---- a scan that fails ----


def test_a_pc_that_doesnt_answer_says_so_and_offers_to_try_again(
    window: CapyWindow, pc: Pc
) -> None:
    tool = _tool(window)
    pc.answer = RemoteError(Reason.UNREACHABLE)
    _scanned(tool)
    card = tool.card
    assert card is not None and card.heading.text() == "DESK-03 didn't answer"
    assert card.body.text().endswith("Nothing was read.")
    assert [b.text() for b in card.buttons] == ["Try again"]
    assert tool.status_label.text() == "DESK-03 · didn't answer"
    assert " · tried at " in tool.header.about.text() and tool.header.filters.isHidden()
    assert tool.bar.rescan_button.isEnabled() and not tool.bar.sizes_button.isEnabled()
    pc.answer = Scan("192.0.2.13", "C:\\Users", ROWS)
    card.buttons[0].click()
    assert len(pc.scanned) == 2 and len(tool.table.texts()) == 6


def test_a_pc_that_refuses_the_account_offers_another_one(
    window: CapyWindow, pc: Pc, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    pc.answer = RemoteError(Reason.REJECTED, 5)
    _scanned(tool)
    card = tool.card
    assert card is not None
    assert card.heading.text() == "DESK-03 refused the account EXAMPLE\\support"
    assert [b.text() for b in card.buttons] == ["Try another account…", "Try again"]
    assert tool.status_label.text() == "DESK-03 · account refused"
    asked: list[tuple[str, BaseException | None]] = []
    monkeypatch.setattr(
        window.hosts.runner, "another_account",
        lambda target, error, again: asked.append((target.name, error)),
    )  # fmt: skip
    card.buttons[0].click()
    assert asked == [("DESK-03", pc.answer)]


def test_any_other_failure_names_windows_error(window: CapyWindow, pc: Pc) -> None:
    tool = _tool(window)
    pc.answer = RemoteError(Reason.OTHER, 1722)
    _scanned(tool)
    card = tool.card
    assert card is not None and card.heading.text() == "Couldn't read DESK-03's profiles"
    assert card.body.text().startswith("Windows error 1722.")
    said = rows.failure(TimeoutError("slow"), "DESK-03", "192.0.2.13", "EXAMPLE\\support")
    assert "took too long" in said.lines[0] and not said.another_account


# ---- how values read ----


def test_sizes_read_in_gigabytes_from_a_tenth_up_and_megabytes_under() -> None:
    assert rows.size_text(int(3.44 * GB)) == "3.4 GB"
    assert rows.size_text(250 * GB) == "250 GB"
    assert rows.size_text(GB // 10) == "0.1 GB"
    assert rows.size_text(40 * 1024**2) == "40 MB"
    assert rows.size_text(1) == "1 MB" and rows.size_text(0) == "0 MB"


def test_the_panels_widths_are_kept(window: CapyWindow) -> None:
    tool = _tool(window)
    tool.splitter.setSizes([230, 600, 300])
    tool.save_state()
    left, right = tool.prefs[tool_ui.PANES_KEY]
    assert left > 0 and right > 0
    assert tool_ui._two_widths([230, 300]) == (230, 300)
    assert tool_ui._two_widths([0, 300]) is None and tool_ui._two_widths("wide") is None


# ---- deleting ----


class Deletes:
    """What the PC answers to each delete, by user; and what was asked, in order."""

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


def _answer(monkeypatch: pytest.MonkeyPatch, fill: Callable[[DeleteDialog], bool]) -> list[Any]:
    """The Delete window is answered by `fill` (True: its action is pressed; False: Cancel);
    the windows opened are kept."""
    opened: list[DeleteDialog] = []

    def run(dialog: Any) -> int:
        opened.append(dialog)
        if fill(dialog) and dialog.action.isEnabled():
            dialog.accept()
            return int(QDialog.DialogCode.Accepted)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(tool_ui, "run_modal", run)
    return opened


def _typed(word: str) -> Callable[[DeleteDialog], bool]:
    def fill(dialog: DeleteDialog) -> bool:
        dialog.word.setText(word)
        return True

    return fill


def test_only_a_row_that_can_be_deleted_has_a_tick_box(window: CapyWindow) -> None:
    tool = _scanned(_tool(window))
    tool.header.hide_own.setChecked(False)
    tree = tool.table.tree
    boxes = {}
    for index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(index)
        assert item is not None
        boxes[item.text(panels.USER)] = item.data(panels.TICK, Qt.ItemDataRole.CheckStateRole)
    assert boxes["EXAMPLE\\ana"] is None and boxes["Public  (unknown)"] is None  # in use; Windows'
    assert all(boxes[user] is not None for user in ("EXAMPLE\\rui", "pedro  (unknown)"))
    assert not tool.bar.delete_button.isEnabled()
    tool.table.tick(ANA.ident)  # as a click where there's no box: nothing
    assert tool.table.ticked() == []
    tool.table.tick(RUI.ident)
    tool.table.tick(BIA.ident)
    assert tool.table.ticked() == [RUI, BIA] and tool.bar.delete_button.isEnabled()
    assert tool.status_label.text() == "DESK-03 · 7 profiles · 5 can be deleted · 2 ticked"
    tool.count_sizes()
    assert tool.status_label.text().endswith(" · 2 ticked · 9.0 GB")
    tool.header.leftovers.setChecked(True)  # a tick on a row no longer shown is dropped
    assert tool.table.ticked() == [] and not tool.bar.delete_button.isEnabled()


def test_the_delete_window_lists_the_ticked_rows_and_wants_the_word_typed(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes
) -> None:
    tool = _scanned(_tool(window))
    tool.count_sizes()
    tool.table.tick(RUI.ident)
    tool.table.tick(MARTA.ident)
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
    assert deletes.asked == [] and tool.table.ticked() == [RUI, MARTA]  # cancelled: as before
    assert rows.confirm_word() == "DELETE" and rows.confirms("Delete") and not rows.confirms("")


def test_ticked_rows_are_deleted_one_at_a_time_and_each_says_how_it_ended(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes
) -> None:
    tool = _scanned(_tool(window))
    tool.count_sizes()
    for profile in (RUI, BIA, MARTA):
        tool.table.tick(profile.ident)
    deletes.answers = {
        BIA.user: (Outcome.SKIPPED, Why.IN_USE, ""),
        MARTA.user: (Outcome.FAILED, Why.ERROR, "Access is denied."),
    }
    _answer(monkeypatch, _typed("delete"))
    tool.bar.delete_button.click()
    assert deletes.asked == [RUI.user, BIA.user, MARTA.user]
    assert deletes.log_files == {window.paths.user_profiles_log_file}
    states = {row[panels.USER]: row[panels.STATE] for row in tool.table.texts()}
    assert (states["EXAMPLE\\rui"], states["EXAMPLE\\bia"], states["marta.old  (unknown)"]) == (
        "Deleted", "Skipped", "Failed",
    )  # fmt: skip
    assert states["temp.joao  (unknown)"] == "Ready"  # not ticked: untouched
    assert tool.table.ticked() == [] and not tool.bar.delete_button.isEnabled()
    progress = tool.progress
    assert tool._side.currentWidget() is progress and progress.over()
    assert progress.title.text() == "Deletion finished"
    assert progress.first.text() == "DESK-03 · 1 deleted, 1 skipped, 1 failed"
    assert progress.second.text().startswith("3.0 GB freed · ")
    assert progress.bar.value() == progress.bar.maximum() == 3
    queue = progress.queue
    assert [queue.topLevelItem(i).text(1) for i in range(3)] == [  # type: ignore[union-attr]
        "Deleted", "Skipped", "Failed",
    ]  # fmt: skip
    log = progress.log.toPlainText().splitlines()
    assert len(log) == 6 and log[1].endswith("EXAMPLE\\rui: deleted, 3.0 GB")
    assert log[3].endswith("EXAMPLE\\bia: skipped, signed in to the PC since the scan")
    assert log[5].endswith("marta.old: failed, Access is denied.")
    assert tool.status_label.text() == ("DESK-03 · 1 deleted · 1 skipped · 1 failed · 3.0 GB freed")
    assert not progress.cancel_button.isVisibleTo(progress)
    assert tool.pcs.isEnabled() and tool.bar.rescan_button.isEnabled()

    _pick_row(tool, "marta.old  (unknown)")  # Details waits behind the panel
    progress.close_button.click()
    assert tool._side.currentWidget() is tool.details
    assert tool.details.shown_value("windows") == "Access is denied."
    states = {row[panels.USER]: row[panels.STATE] for row in tool.table.texts()}
    assert states["EXAMPLE\\rui"] == "Deleted"  # results stay until the next scan
    tool.bar.rescan_button.click()
    states = {row[panels.USER]: row[panels.STATE] for row in tool.table.texts()}
    assert states["EXAMPLE\\rui"] == "Ready"  # the fake PC still has it


def test_cancel_the_rest_lets_the_current_one_finish_and_starts_no_other(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, deletes: Deletes
) -> None:
    tool = _scanned(_tool(window))
    for profile in (RUI, BIA, MARTA):
        tool.table.tick(profile.ident)
    held: list[Callable[[], None]] = []

    def later(work: Callable[[], Any], done: Callable[[Any], None], failed: Any) -> None:
        held.append(lambda: done(work()))

    tool._start = later  # type: ignore[method-assign]
    _answer(monkeypatch, _typed("DELETE"))
    tool.bar.delete_button.click()
    progress = tool.progress
    assert tool._side.currentWidget() is progress and not progress.over()
    assert progress.title.text() == "Deleting profiles"
    assert progress.first.text().startswith("DESK-03 · 1 of 3 · since ")
    assert tool.status_label.text() == "DESK-03 · deleting 1 of 3"
    states = {row[panels.USER]: row[panels.STATE] for row in tool.table.texts()}
    assert (states["EXAMPLE\\rui"], states["EXAMPLE\\bia"]) == ("Deleting…", "Queued")
    # While it runs: no scan, no other PC, no tick, no second run.
    assert not tool.pcs.isEnabled() and not tool.bar.rescan_button.isEnabled()
    assert not tool.bar.delete_button.isEnabled() and not tool.bar.sizes_button.isEnabled()
    tool.table.tick(BIA.ident, on=False)
    assert BIA in tool.table.ticked()
    tool.scan_again()
    assert len(held) == 1 and deletes.asked == []

    progress.cancel_button.click()
    assert not progress.cancel_button.isEnabled() and not progress.over()
    held.pop(0)()  # the current one finishes
    assert deletes.asked == [RUI.user] and held == []  # and no other starts
    assert progress.over() and progress.first.text() == "DESK-03 · 1 deleted"
    assert [progress.queue.topLevelItem(i).text(1) for i in range(3)] == [  # type: ignore[union-attr]
        "Deleted", "Not started", "Not started",
    ]  # fmt: skip
    assert "cancelled: 2 not started" in progress.log.toPlainText()
    states = {row[panels.USER]: row[panels.STATE] for row in tool.table.texts()}
    assert states["EXAMPLE\\bia"] == "Ready" and tool.table.ticked() == [BIA, MARTA]
    assert tool.bar.delete_button.isEnabled()  # the ticks left can be run again


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


def test_open_the_log_says_so_when_there_is_none_yet(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool(window)
    opened: list[Path] = []
    monkeypatch.setattr(tool_ui.os, "startfile", opened.append, raising=False)
    tool.open_log()
    assert opened == []  # nothing was ever deleted: no file to open
    log_file = window.paths.user_profiles_log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("a line\n", encoding="utf-8")
    tool.open_log()
    assert opened == [log_file]


# ---- groups ----


def test_a_dropdown_shows_one_groups_pcs_and_the_search_looks_through_them_all(
    window: CapyWindow, tmp_path: Path
) -> None:
    tool = _tool(window)
    hl, clinic = HostList().add_group("Clinic")
    hl, lab = hl.add_group("Lab", parent=clinic.id)
    hl, er = hl.add_group("ER")
    for name, group, address in (
        ("DESK-01", clinic.id, "192.0.2.11"), ("LAB-01", lab.id, "192.0.2.31"),
        ("ER-01", er.id, "192.0.2.41"), ("SPARE", NO_GROUP, "192.0.2.90"),
        ("Front desk printer room", er.id, ""),  # can't be reached: never listed or counted
    ):  # fmt: skip
        hl, _host = hl.add_host(name, group, address=address)
    path = tmp_path / "wards.json"
    listfile.save(path, hl, expected=None)
    window.hosts.open_list(path)
    groups = tool.pcs.groups
    assert [groups.itemText(i) for i in range(groups.count())] == [
        "All hosts (4)", "No group (1)", "Clinic (2)", "    Lab (1)", "ER (1)",
    ]  # fmt: skip
    assert groups.currentIndex() == 0 and _pcs(tool) == ["DESK-01", "ER-01", "LAB-01", "SPARE"]

    def choose(index: int) -> None:
        groups.setCurrentIndex(index)
        groups.activated.emit(index)

    choose(2)  # Clinic: its own PCs and those of the groups inside it
    assert _pcs(tool) == ["DESK-01", "LAB-01"]
    choose(1)
    assert _pcs(tool) == ["SPARE"]
    choose(4)
    assert _pcs(tool) == ["ER-01"]
    tool.pcs.search.setText("lab")  # a search looks through every group
    assert _pcs(tool) == ["LAB-01"]
    tool.pcs.search.clear()
    assert _pcs(tool) == ["ER-01"]
    _pick(tool, "ER-01")
    assert tool.pcs.scan_button.text() == "Scan ER-01"
    tool.pcs.other.setText("desk-01")  # a PC of another group, typed: still that PC
    tool.pcs.other.textEdited.emit("desk-01")
    target = tool.pcs.target()
    assert target is not None and target.address == "192.0.2.11"

    # Each list comes back on the group it was left on.
    assert tool.prefs[tool_ui.GROUPS_KEY] == {str(path): er.id}
    window.hosts.open_list(tmp_path / "clinic.json")
    assert groups.currentIndex() == 0 and tool.pcs.group() == panels.ALL_GROUPS
    window.hosts.open_list(path)
    assert groups.currentText() == "ER (1)" and _pcs(tool) == ["ER-01"]
    choose(0)
    assert tool.prefs[tool_ui.GROUPS_KEY] == {}
