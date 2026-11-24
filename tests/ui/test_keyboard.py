from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from fake_console import FakeConsole
from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QContextMenuEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.ui import about, help_links
from capypanel.ui.import_hosts import ImportDialog
from capypanel.ui.keyboard import Keyboard, tab_stop_while_it_scrolls
from capypanel.ui.list_workspace import workspace as workspace_module
from capypanel.ui.main_window.toolbar import ToolButton
from capypanel.ui.menus import label
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.ssh_tool.terminal import view as view_module
from capypanel.ui.ssh_tool.terminal.view import PAD, TerminalView
from capypanel.ui.tab_strip import PINNED, TabStrip

K = Qt.Key


@pytest.fixture
def keys(qapp: QApplication) -> Iterator[Keyboard]:
    keys = Keyboard()
    qapp.installEventFilter(keys)
    yield keys
    qapp.removeEventFilter(keys)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []
    monkeypatch.setattr(about, "open_url", urls.append)
    return urls


@pytest.fixture
def office(tmp_path: Path) -> Path:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    hl, _ = hl.add_host("HQ-01", hq.id, address="192.0.2.1", tags=["kiosk"])
    hl, _ = hl.add_host("FIN-01", finance.id, tags=["floor-3"])
    hl, _ = hl.add_host("FIN-02", finance.id)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    return path


def _shown(widget: QWidget) -> None:
    widget.show()
    widget.activateWindow()
    QApplication.processEvents()
    assert QApplication.activeWindow() is widget


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, keys: Keyboard) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.resize(1100, 700)
    _shown(win)
    yield win
    win.close()


def _press(key: K, mods: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> QWidget | None:
    focus = QApplication.focusWidget()
    assert focus is not None
    QTest.keyClick(focus, key, mods)
    QApplication.processEvents()
    return QApplication.focusWidget()


def _tabs(count: int) -> list[QWidget | None]:
    return [_press(K.Key_Tab) for _turn in range(count)]


def _row(window: CapyWindow, name: str) -> QTreeWidgetItem:
    table = window.hosts.table
    rows = (table.topLevelItem(i) for i in range(table.topLevelItemCount()))
    return next(r for r in rows if r is not None and r.text(0) == name)


def test_the_rail_is_one_tab_stop_entered_at_the_tool_shown(
    window: CapyWindow, office: Path
) -> None:
    window.show_tool("ssh")
    rail = window.rail
    rail.settings_button.setFocus(Qt.FocusReason.OtherFocusReason)
    after = _press(K.Key_Tab)
    assert after is not None and not rail.isAncestorOf(after)
    assert _press(K.Key_Backtab) is rail.buttons["ssh"]
    before = _press(K.Key_Backtab)
    assert before is not None and not rail.isAncestorOf(before)
    stops = _tabs(40)
    assert rail.help_button not in stops and rail.settings_button not in stops


def test_enter_opens_the_rail_s_button_with_the_ring_as_space_does(window: CapyWindow) -> None:
    window.show_tool("hosts")
    rail = window.rail
    rail.buttons["hosts"].setFocus(Qt.FocusReason.OtherFocusReason)
    _press(K.Key_Down)
    _press(K.Key_Return)
    assert window.shown_tool() is window.tools["printers"]
    _press(K.Key_Down)
    _press(K.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    assert window.shown_tool() is window.tools["profiles"]


def test_tab_goes_through_the_tool_as_it_stands(window: CapyWindow, office: Path) -> None:
    window.show_tool("hosts")
    hosts = window.hosts
    hosts.open_list(office)
    window.rail.settings_button.setFocus(Qt.FocusReason.TabFocusReason)
    stops = _tabs(30)
    assert isinstance(stops[0], ToolButton) and hosts.toolbar.isAncestorOf(stops[0])
    seen = [hosts.list_picker, hosts.nav.everything, hosts.nav.groups, hosts.search, hosts.table]
    places = [stops.index(w) for w in seen]
    assert places == sorted(places) and places[0] > 0


def test_up_and_down_move_along_the_rail_opening_nothing(window: CapyWindow) -> None:
    window.show_tool("hosts")
    rail = window.rail.in_order()
    rail[0].setFocus(Qt.FocusReason.OtherFocusReason)
    assert [_press(K.Key_Down) for _b in rail[1:]] == rail[1:]
    assert _press(K.Key_Down) is rail[-1]
    assert _press(K.Key_Up) is rail[-2]
    rail[0].setFocus(Qt.FocusReason.OtherFocusReason)
    assert _press(K.Key_Up) is rail[0]
    assert window.shown_tool() is window.hosts


def _in_page_shown(dialog: SettingsDialog, widget: QWidget | None) -> bool:
    view = dialog.stack.currentWidget()
    return widget is not None and view is not None and (widget is view or view.isAncestorOf(widget))


def _settings(window: CapyWindow, page: str) -> SettingsDialog:
    dialog = window.settings_dialog()
    dialog.show_page(page)
    _shown(dialog)
    return dialog


def test_settings_pages_about_and_help_are_one_stop_and_tab_goes_into_the_page_shown(
    window: CapyWindow,
) -> None:
    dialog = _settings(window, "general")
    dialog.search.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is dialog.page_list
    assert dialog.page_list.currentRow() == dialog.row_of("general")
    assert _in_page_shown(dialog, _press(K.Key_Tab))
    assert _press(K.Key_Backtab) is dialog.page_list
    assert _press(K.Key_Backtab) is dialog.search
    stops = _tabs(30)
    assert dialog.pinned_list not in stops and dialog.help_button not in stops
    assert dialog.current_page() == "general"
    dialog.show_page("about")
    dialog.search.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is dialog.pinned_list
    assert _in_page_shown(dialog, _press(K.Key_Tab)) and dialog.current_page() == "about"
    dialog.close()


def test_settings_arrows_walk_pages_about_and_help_opening_nothing_till_enter_or_space(
    window: CapyWindow, opened: list[str]
) -> None:
    dialog = _settings(window, "general")
    pages = dialog.page_list
    pages.setFocus(Qt.FocusReason.TabFocusReason)
    while pages.currentRow() != dialog.row_of("hosts"):
        assert _press(K.Key_Down) is pages
    assert dialog.current_page() == "general"
    _press(K.Key_Return)
    assert dialog.current_page() == "hosts"
    assert _press(K.Key_End) is dialog.help_button
    assert _press(K.Key_Up) is dialog.pinned_list and dialog.current_page() == "hosts"
    assert _press(K.Key_Down) is dialog.help_button
    _press(K.Key_Return)
    assert opened == [help_links.url(dialog.pages["hosts"].place)]
    _press(K.Key_Up)
    _press(K.Key_Space)
    assert dialog.current_page() == "about"
    assert _press(K.Key_Up) is pages and pages.currentRow() == pages.count() - 1
    assert _press(K.Key_Home) is pages and pages.currentRow() == dialog.row_of("general")
    assert dialog.current_page() == "about"
    dialog.close()


def test_settings_tab_comes_back_at_the_page_shown_wherever_the_arrows_left_the_ring(
    window: CapyWindow,
) -> None:
    dialog = _settings(window, "hosts")
    dialog.page_list.setFocus(Qt.FocusReason.TabFocusReason)
    _press(K.Key_End)
    assert _press(K.Key_Up) is dialog.pinned_list
    assert _in_page_shown(dialog, _press(K.Key_Tab))
    assert _press(K.Key_Backtab) is dialog.page_list
    assert dialog.page_list.currentRow() == dialog.row_of("hosts")
    assert dialog.pinned_list.currentRow() == -1 and dialog.current_page() == "hosts"
    dialog.close()


def test_home_s_tiles_take_tab_the_arrows_as_they_stand_and_enter_or_space(
    window: CapyWindow,
) -> None:
    window.show_home()
    tiles = window.home.tiles
    assert len(tiles) == 4
    window.rail.settings_button.setFocus(Qt.FocusReason.TabFocusReason)
    assert _tabs(4) == tiles
    tiles[0].setFocus(Qt.FocusReason.TabFocusReason)
    assert [_press(k) for k in (K.Key_Right, K.Key_Down, K.Key_Left, K.Key_Up)] == [
        tiles[1], tiles[3], tiles[2], tiles[0]
    ]  # fmt: skip
    assert _press(K.Key_Up) is tiles[0] and _press(K.Key_Left) is tiles[0]
    _press(K.Key_Return)
    assert window.shown_tool() is window.hosts
    window.show_home()
    tiles[3].setFocus(Qt.FocusReason.TabFocusReason)
    _press(K.Key_Space)
    assert window.shown_tool() is window.tools["ssh"]


def test_the_groups_panel_s_list_picker_is_reached_before_its_lists(
    window: CapyWindow, office: Path
) -> None:
    window.show_tool("hosts")
    hosts = window.hosts
    hosts.open_list(office)
    hosts.list_picker.setFocus(Qt.FocusReason.TabFocusReason)
    assert _tabs(2) == [hosts.nav.everything, hosts.nav.add_group_button]


def _menus(monkeypatch: pytest.MonkeyPatch) -> list[tuple[QMenu, QPoint]]:
    shown: list[tuple[QMenu, QPoint]] = []
    monkeypatch.setattr(workspace_module, "popup", lambda menu, where: shown.append((menu, where)))
    return shown


def _windows_menu(widget: QWidget) -> None:
    corner = QPoint(0, 0)
    reason = QContextMenuEvent.Reason.Keyboard
    QApplication.sendEvent(widget, QContextMenuEvent(reason, corner, widget.mapToGlobal(corner)))
    QApplication.processEvents()


WAYS: dict[str, Callable[[QWidget], object]] = {
    "the menu key": lambda w: QTest.keyClick(w, K.Key_Menu),
    "Shift+F10": lambda w: QTest.keyClick(w, K.Key_F10, Qt.KeyboardModifier.ShiftModifier),
    "Windows' Shift+F10, aimed at the table's corner": _windows_menu,
}


@pytest.mark.parametrize("way", WAYS)
def test_each_keyboard_way_opens_the_current_row_s_menu_at_that_row(
    window: CapyWindow, office: Path, monkeypatch: pytest.MonkeyPatch, way: str
) -> None:
    shown = _menus(monkeypatch)
    window.show_tool("hosts")
    hosts = window.hosts
    hosts.open_list(office)
    table = hosts.table
    table.setFocus(Qt.FocusReason.TabFocusReason)
    row = _row(window, "FIN-02")
    table.setCurrentItem(row)
    WAYS[way](table)
    assert len(shown) == 1
    menu, where = shown[0]
    under = table.itemAt(table.viewport().mapFromGlobal(where))
    assert under is not None and under.text(0) == row.text(0) == "FIN-02"
    assert [h.name for h in hosts.selected_items()] == ["FIN-02"]
    assert any(a.text() == "Co&py" for a in menu.actions())


def test_the_menu_key_picks_the_current_row_first_as_a_right_click_does(
    window: CapyWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _menus(monkeypatch)
    window.show_tool("hosts")
    hosts = window.hosts
    hosts.open_list(office)
    table = hosts.table
    table.setFocus(Qt.FocusReason.TabFocusReason)
    table.clearSelection()
    flag = QItemSelectionModel.SelectionFlag.NoUpdate
    table.setCurrentItem(_row(window, "HQ-01"), 0, flag)
    assert not hosts.selected_items()
    QTest.keyClick(table, K.Key_Menu)
    assert [h.name for h in hosts.selected_items()] == ["HQ-01"] and len(shown) == 1


def _names(window: CapyWindow) -> list[str]:
    table = window.hosts.table
    rows = (table.topLevelItem(i) for i in range(table.topLevelItemCount()))
    return [r.text(0) for r in rows if r is not None]


def _picks(menu: QMenu) -> dict[str, QAction]:
    menu.aboutToShow.emit()
    return {label(a): a for a in menu.actions() if not a.isSeparator()}


def test_view_sorts_the_list_and_picks_its_columns_as_the_header_does(
    window: CapyWindow, office: Path
) -> None:
    window.show_tool("hosts")
    hosts = window.hosts
    hosts.open_list(office)
    view = window._view_menu  # pyright: ignore[reportPrivateUsage]
    table_group = [hosts.sort_menu.menuAction(), hosts.columns_menu.menuAction()]
    assert hosts.view_actions()[1] == [*table_group, hosts.commands.show_domains]
    assert set(table_group) <= set(view.actions())
    picks = _picks(hosts.sort_menu)
    assert list(picks) == ["Name", "Address", "Status", "User", "Tags", "&Ascending", "&Descending"]
    assert picks["Name"].isChecked() and picks["&Ascending"].isChecked()
    picks["&Descending"].trigger()
    assert _names(window) == ["HQ-01", "FIN-02", "FIN-01"]
    picks = _picks(hosts.sort_menu)
    assert picks["&Descending"].isChecked() and not picks["&Ascending"].isChecked()
    picks["Tags"].trigger()
    header = hosts.table.header()
    assert header.sortIndicatorSection() == hosts.table.TAGS
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(hosts.sort_menu.findChildren(QActionGroup)) == 2
    _picks(hosts.columns_menu)["Address"].trigger()
    assert hosts.table.isColumnHidden(hosts.table.ADDRESS)
    assert "Address" not in _picks(hosts.sort_menu)


def test_a_scroll_area_is_a_tab_stop_only_while_there_s_more_to_scroll(
    qapp: QApplication,
) -> None:
    area = QScrollArea()
    inside = QWidget()
    inside.setMinimumHeight(100)
    area.setWidget(inside)
    area.setWidgetResizable(True)
    area.resize(200, 300)
    tab_stop_while_it_scrolls(area)
    _shown(area)
    assert area.focusPolicy() == Qt.FocusPolicy.NoFocus
    inside.setMinimumHeight(900)
    QApplication.processEvents()
    assert area.focusPolicy() == Qt.FocusPolicy.TabFocus
    inside.setMinimumHeight(100)
    QApplication.processEvents()
    assert area.focusPolicy() == Qt.FocusPolicy.NoFocus
    area.close()


def test_one_tab_marks_a_label_s_first_link_and_shift_tab_its_last(
    qapp: QApplication, keys: Keyboard
) -> None:
    window = QWidget()
    before, after = QLineEdit(), QLineEdit()
    label = QLabel('<a href="one">One</a> or <a href="two">two</a>')
    label.setTextInteractionFlags(help_links.LINK_KEYS)
    column = QVBoxLayout(window)
    for widget in (before, label, after):
        column.addWidget(widget)
    _shown(window)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is label and label.selectedText() == "One"
    assert _press(K.Key_Tab) is label and label.selectedText() == "two"
    assert _press(K.Key_Tab) is after
    assert _press(K.Key_Backtab) is label and label.selectedText() == "two"
    window.close()


def test_tab_moves_on_from_import_s_paste_box(qapp: QApplication, keys: Keyboard) -> None:
    dialog = ImportDialog(None, HostList(), NO_GROUP)
    _shown(dialog)
    dialog.text.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is not dialog.text
    assert dialog.text.toPlainText() == ""
    dialog.close()


def _strip(picked: list[str]) -> tuple[QWidget, TabStrip, QLineEdit]:
    window = QWidget()
    strip = TabStrip("device-desktop")
    before, after = QLineEdit(), QLineEdit()
    column = QVBoxLayout(window)
    for widget in (before, strip, after):
        column.addWidget(widget)

    def pick(key: str) -> None:
        picked.append(key)
        strip.set_current(key)

    strip.picked.connect(pick)
    strip.set_height(30)
    _shown(window)
    return window, strip, before


def test_the_tab_strip_is_a_stop_once_it_has_tabs_and_the_arrows_walk_them(
    qapp: QApplication, keys: Keyboard
) -> None:
    picked: list[str] = []
    window, strip, before = _strip(picked)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) not in (strip.pinned, strip.bar)
    for key, name in (("a", "core-sw-01"), ("b", "nas-01")):
        strip.add(key, name)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is strip.pinned
    assert _press(K.Key_Right) is strip.bar and strip.current() == "a"
    assert _press(K.Key_Right) is strip.bar and strip.current() == "b"
    assert _press(K.Key_Right) is strip.bar and strip.current() == "b"
    assert _press(K.Key_Home) is strip.pinned and strip.current() == PINNED
    assert _press(K.Key_End) is strip.bar and strip.current() == "b"
    assert picked == ["a", "b", PINNED, "b"]
    assert _press(K.Key_Tab) is strip.more
    assert _press(K.Key_Backtab) is strip.bar
    assert _press(K.Key_Backtab) is before
    window.close()


def test_the_menu_key_on_the_strip_opens_the_current_tab_s_menu_there(
    qapp: QApplication, keys: Keyboard
) -> None:
    window, strip, _before = _strip([])
    for key, name in (("a", "core-sw-01"), ("b", "nas-01")):
        strip.add(key, name)
    strip.set_current("b")
    asked: list[tuple[str, QPoint]] = []
    strip.menu_requested.connect(lambda key, where: asked.append((key, where)))
    strip.bar.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(strip.bar, K.Key_Menu)
    assert [key for key, _where in asked] == ["b"]
    assert strip.bar.tabAt(strip.bar.mapFromGlobal(asked[0][1])) == strip.index_of("b")
    window.close()


@pytest.fixture
def consoles(monkeypatch: pytest.MonkeyPatch) -> list[FakeConsole]:
    made: list[FakeConsole] = []

    def start(*args: Any, **kwargs: Any) -> FakeConsole:
        made.append(FakeConsole(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(view_module, "PseudoConsole", start)
    return made


@pytest.fixture
def terminal(
    qapp: QApplication, keys: Keyboard, consoles: list[FakeConsole]
) -> Iterator[tuple[TerminalView, QPushButton]]:
    window = QWidget()
    view = TerminalView(host="web-01", parent=window)
    after = QPushButton("Next")
    column = QVBoxLayout(window)
    column.addWidget(view)
    column.addWidget(after)
    _shown(window)
    yield view, after
    view.close_connection()
    window.close()


def _until(test: Callable[[], bool]) -> None:
    for _turn in range(2000):
        if test():
            return
        QApplication.processEvents()
    raise AssertionError("timed out")


def test_the_menu_key_opens_the_terminal_s_menu_at_its_cursor(
    terminal: tuple[TerminalView, QPushButton], consoles: list[FakeConsole]
) -> None:
    view, _after = terminal
    view.start(["ssh.exe", "--", "192.0.2.42"])
    consoles[-1].prints(b"$ ")
    _until(lambda: view.term.cursor.x == 2)
    shown: list[tuple[list[str], QPoint]] = []
    view.open_menu = lambda menu, where: shown.append(([label(a) for a in menu.actions()], where))
    view.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(view, K.Key_Menu)
    assert len(shown) == 1 and "&Find…" in shown[0][0]
    cell = view.viewport().mapFromGlobal(shown[0][1])
    assert (cell.x() - PAD) // view.cell_w == 2 and (cell.y() - PAD) // view.cell_h == 0


def test_tab_completes_while_the_connection_runs_and_moves_on_once_it_ends(
    terminal: tuple[TerminalView, QPushButton], consoles: list[FakeConsole]
) -> None:
    view, after = terminal
    view.start(["ssh.exe", "--", "192.0.2.42"])
    console = consoles[-1]
    view.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is view and console.written
    console.ends(0)
    _until(lambda: not view.running)
    view.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is after
