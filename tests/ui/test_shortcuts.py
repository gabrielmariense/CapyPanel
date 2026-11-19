"""Settings › CapyPanel › Keyboard shortcuts: every command a key can run, today's keys as the
defaults, a person's changes kept and applied at once, and the keys no command may take."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QKeyCombination, QRect, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMessageBox,
    QStyle,
    QStyleOptionFrame,
    QTreeWidgetItem,
    QWidget,
)

from capypanel.core import settings
from capypanel.ui import shortcuts
from capypanel.ui.printers_tool.tool import PrintersTool, refresh_words
from capypanel.ui.settings import shortcuts_page
from capypanel.ui.settings.shortcuts_page import KEY, KeyCatcher, ShortcutsPage


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


@pytest.fixture
def window(qapp: QApplication, paths: settings.Paths) -> Iterator[CapyWindow]:
    win = CapyWindow(paths, {"schema": 1})
    yield win
    win.close()


def _page(window: CapyWindow) -> ShortcutsPage:
    dialog = window.settings_dialog()
    page = dialog.shortcuts
    assert dialog.pages["shortcuts"] is page and page.title == "Keyboard shortcuts"
    return page


def _press(
    page: ShortcutsPage, row_id: str, key: Qt.Key, mods: Any = Qt.KeyboardModifier.NoModifier
) -> None:
    item = page.item_of(row_id)
    page.change(item)
    catcher = page.table.itemWidget(item, KEY)
    assert isinstance(catcher, KeyCatcher)
    QTest.keyClick(catcher, key, mods)


def _answer(monkeypatch: pytest.MonkeyPatch, give: bool) -> list[str]:
    """The "give it to … instead?" question, answered; its words are kept."""
    asked: list[str] = []

    def run(box: QMessageBox) -> int:
        asked.append(f"{box.text()} {box.informativeText()}")
        for button in box.buttons():
            role = box.buttonRole(button)
            if (role == QMessageBox.ButtonRole.AcceptRole) == give:
                button.click()
                break
        return 0

    monkeypatch.setattr(shortcuts_page, "run_modal", run)
    return asked


def test_every_command_is_listed_with_today_s_key_and_power_never_is(window: CapyWindow) -> None:
    keys = window.keys
    ids = [row.id for row in keys.rows]
    assert ids[:2] == ["app.settings", "app.exit"]  # the window's own come first
    assert keys.key(keys.row("app.settings")) == "Ctrl+,"
    assert keys.key(keys.row("go.home")) == "Ctrl+0"
    assert keys.key(keys.row("go.hosts")) == "Ctrl+1"
    assert keys.key(keys.row("command.c-share")) == "Ctrl+E"
    assert keys.key(keys.row("command.services")) == ""  # most have none, for you to fill
    for never in ("restart", "shut-down", "cancel-restart", "spooler"):  # disturb the PC's user
        assert f"command.{never}" not in ids
    hosts_edit, printers_edit = keys.row("hosts.edit"), keys.row("printers.edit")
    # Each tool's own row, even for a command both have (Gabriel, 2026-11-16).
    assert hosts_edit.places == ["hosts"] and printers_edit.places == ["printers"]
    assert keys.key(hosts_edit) == keys.key(printers_edit) == "F2"
    assert keys.row("hosts.add_host").places == ["hosts"]
    assert keys.row("printers.add_printer").places == ["printers"]
    page = _page(window)
    assert page.table.columnCount() == 2  # Command and Key: the place is the heading
    item = page.item_of("hosts.edit")
    assert [item.text(c) for c in range(2)] == ["Edit…", "F2"]
    assert page.item_of("hosts.copy_address").text(0) == "Copy address"  # not a bare "Address"
    # Connect's key works only in the host list, whatever key it is, and the page says so.
    connect = page.item_of("hosts.connect_host")
    cell = page.table.itemWidget(connect, KEY)
    assert connect.text(KEY) == "" and cell is not None
    assert [w.text() for w in cell.findChildren(QLabel)] == ["Enter", "(in the list)"]
    assert page.item_of("hosts.add_host").text(KEY) == "Ctrl+N"  # the others: just the key
    assert page.table.itemWidget(page.item_of("hosts.add_host"), KEY) is None
    # No card and no fixed height: the list fills the page, which never scrolls (Dante's redo).
    assert page.section.heading.isHidden() and page.section.inner.objectName() == ""
    assert page.table.maximumHeight() == 16777215
    # Each tool's row runs that tool's own action, so it has its own word ("Atualizar todas"
    # in Printers, "Atualizar todos" in Hosts).
    hosts_refresh, printers_refresh = (
        keys.row("hosts.refresh_shown"),
        keys.row("printers.refresh_shown"),
    )
    assert hosts_refresh.actions[0] is not printers_refresh.actions[0]
    # The key column fits the waiting field's "Press the new key…" in full.
    page.change(page.item_of("command.services"))
    catcher = page.table.itemWidget(page.item_of("command.services"), KEY)
    assert isinstance(catcher, KeyCatcher)
    text = catcher.fontMetrics().horizontalAdvance(catcher.placeholderText())
    assert page.table.columnWidth(KEY) >= text


RESERVED_LINE = (
    "F1, Esc, Ctrl+F, Tab and Ctrl+Shift+W are kept for CapyPanel itself. In an SSH terminal, "
    "all but Ctrl+Shift+W go to the server."
)


def _headings(page: ShortcutsPage) -> list[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]]:
    """Each heading row with the command rows under it."""
    table = page.table
    found: list[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]] = []
    for i in range(table.topLevelItemCount()):
        item = table.topLevelItem(i)
        assert item is not None
        if item.data(0, shortcuts_page.FIXED_ROLE):
            continue  # the SSH terminal's own keys: never a command, never a heading
        if item.data(0, shortcuts_page.ROW_ROLE):
            found[-1][1].append(item)
        else:
            found.append((item, []))
    return found


def test_no_waiting_field_is_left_in_the_list_when_the_page_opens(window: CapyWindow) -> None:
    """The Key column's width is measured on a waiting field; it must be gone at once, since
    Settings runs in its own loop (exec) where a deleteLater never comes, and the field showed
    across the list's top row (Gabriel's test of build 576)."""
    page = _page(window)  # no events run between building the page and this check
    assert page.table.viewport().findChildren(KeyCatcher) == []


def test_every_command_has_its_place_in_the_order_you_meet_it(window: CapyWindow) -> None:
    ids = {row.id for row in window.keys.rows}
    assert ids == set(shortcuts_page.ORDER)  # a new command needs its place in ORDER
    assert len(shortcuts_page.ORDER) == len(ids)  # and only one


def test_the_commands_sit_under_their_menu_or_tool_in_app_order(window: CapyWindow) -> None:
    page = _page(window)
    headings = _headings(page)
    assert [h.text(0) for h, _rows in headings] == [
        "File", "View", "Help", "Hosts", "Printers", "SSH", "SSH terminal",
    ]  # fmt: skip
    shown: list[str] = []
    for heading, rows in headings:
        assert heading.flags() == Qt.ItemFlag.NoItemFlags  # can't be picked
        shown += [row.data(0, shortcuts_page.ROW_ROLE) for row in rows]
    assert shown == list(shortcuts_page.ORDER)  # as you meet them on screen, never A–Z
    file_rows = [row.data(0, shortcuts_page.ROW_ROLE) for row in headings[0][1]]
    assert file_rows == ["app.settings", "app.exit"]  # the File menu's order
    # Every heading but the first has empty space above it.
    first, second = headings[0][0], headings[1][0]
    assert second.sizeHint(0).height() == first.sizeHint(0).height() + shortcuts_page.HEADING_GAP
    # A double-click on a heading waits for nothing (Qt's tree activates even a disabled row).
    page.table.itemActivated.emit(first, 0)
    assert page.table.itemWidget(first, KEY) is None
    assert not any(isinstance(page.table.itemWidget(i, KEY), KeyCatcher) for i in page._items())
    # The arrow keys go past a heading.
    last_of_file = headings[0][1][-1]
    page.table.setCurrentItem(last_of_file)
    QTest.keyClick(page.table, Qt.Key.Key_Down)
    assert page.table.currentItem() is headings[1][1][0]
    # One line on top, as body text a point up; the reserved keys under the buttons.
    assert page.about.text() == "Double-click a command and press its new key."
    assert page.about.objectName() == "lead" and page.problem.objectName() == "hint"
    assert page.about.font().pointSizeF() == page.table.font().pointSizeF() + 1
    assert page.problem.text() == RESERVED_LINE


def test_the_ssh_terminal_s_own_keys_follow_the_ssh_tool_greyed_and_say_where_the_rest_go(
    window: CapyWindow,
) -> None:
    page = _page(window)
    table = page.table
    items = [table.topLevelItem(i) for i in range(table.topLevelItemCount())]
    heading = next(i for i in items if i is not None and i.text(0) == "SSH terminal")
    start = items.index(heading)
    before = items[start - 1]
    assert before is not None and before.data(0, shortcuts_page.ROW_ROLE) == "ssh.open_list"
    line = items[start + 1]
    assert line is not None and table.itemWidget(line, 0) is page.terminal_words
    assert page.terminal_words.text() == (
        "Inside a terminal, every key goes to the server except the ones below and the keys "
        "that change tools or open Settings."
    )
    assert page.terminal_words.wordWrap()  # never "…"
    rows = [i for i in items[start + 2 :] if i is not None]
    assert [(i.text(0), i.text(1)) for i in rows] == [
        ("Copy", "Ctrl+Shift+C"),
        ("Copy, with text selected", "Ctrl+C"),
        ("Paste", "Ctrl+Shift+V"),
        ("Bigger text", "Ctrl+="),
        ("Smaller text", "Ctrl+-"),
        ("Next tab", "Ctrl+Tab"),
        ("Previous tab", "Ctrl+Shift+Tab"),
        ("Close tab", "Ctrl+Shift+W"),
    ]
    for item in [line, *rows]:
        assert item.flags() == Qt.ItemFlag.NoItemFlags  # greyed: nobody changes them
    assert {i.toolTip(0) for i in rows} == {"The terminal's own keys can't be changed."}
    assert all(i not in page._items() for i in rows)  # pyright: ignore[reportPrivateUsage]
    # A double-click waits for no key there.
    table.itemActivated.emit(rows[0], 0)
    assert table.itemWidget(rows[0], KEY) is None


def test_the_terminal_s_line_is_as_tall_as_its_words_at_the_list_s_width(
    window: CapyWindow,
) -> None:
    dialog = window.settings_dialog()
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.show_page("shortcuts")
    dialog.show()
    page = dialog.shortcuts
    line = next(
        item
        for i in range(page.table.topLevelItemCount())
        if (item := page.table.topLevelItem(i)) is not None
        and page.table.itemWidget(item, 0) is page.terminal_words
    )
    heights = []
    for width in (1400, 500):
        dialog.resize(max(width, dialog.minimumSizeHint().width()), 700)
        QApplication.processEvents()
        heights.append(line.sizeHint(0).height())
        words = page.terminal_words.heightForWidth(page.table.viewport().width())
        assert line.sizeHint(0).height() >= words  # all of it shows
    assert heights[1] > heights[0]  # narrower: more lines
    dialog.close()


def test_a_command_whose_menu_text_changes_keeps_its_plain_name(window: CapyWindow) -> None:
    """The right-click menu counts the printers ("Refresh 3 printers") and the host menu names
    who's signed in; the page names the command, never what was last picked."""
    keys = window.keys
    refresh = keys.row("printers.refresh_selected")
    refresh.actions[0].setText("&Refresh 3 printers")
    folder = keys.row("command.user-folder")
    plain = folder.name()
    folder.actions[0].setText(f"{plain} (ana)")
    assert refresh.name() == "Refresh printer"
    assert folder.name() == plain
    page = _page(window)
    assert page.item_of("printers.refresh_selected").text(0) == "Refresh printer"
    assert page.item_of("command.user-folder").text(0) == plain


def test_a_new_key_is_kept_and_works_at_once_in_its_own_tool_only(window: CapyWindow) -> None:
    page = _page(window)
    _press(page, "hosts.edit", Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert page.item_of("hosts.edit").text(KEY) == "Ctrl+K"
    row = window.keys.row("hosts.edit")
    assert [a.shortcut() for a in row.actions] == [QKeySequence("Ctrl+K")]
    assert window.keys.key(window.keys.row("printers.edit")) == "F2"  # the other tool's stays
    assert page.item_of("printers.edit").text(KEY) == "F2"
    assert window.prefs["shortcuts"] == {"hosts.edit": "Ctrl+K"}  # only what differs
    page.table.setCurrentItem(page.item_of("hosts.edit"))
    assert page.restore.isEnabled() and page.clear.isEnabled()
    page.restore.click()
    assert window.prefs["shortcuts"] == {} and row.actions[0].shortcut() == QKeySequence("F2")
    assert not page.restore.isEnabled()
    page.clear.click()  # no key at all
    assert window.prefs["shortcuts"] == {"hosts.edit": ""} and row.actions[0].shortcut().isEmpty()
    assert page.item_of("hosts.edit").text(KEY) == ""


def test_a_key_kept_for_both_tools_before_goes_to_each(
    qapp: QApplication, paths: settings.Paths
) -> None:
    prefs: dict[str, Any] = {"schema": 1, "shortcuts": {"list.edit": "Ctrl+K", "list.remove": ""}}
    win = CapyWindow(paths, prefs)
    try:
        keys = win.keys
        for tool in ("hosts", "printers", "ssh"):  # every list tool, SSH too
            assert keys.key(keys.row(f"{tool}.edit")) == "Ctrl+K", tool
            assert keys.key(keys.row(f"{tool}.remove")) == "", tool
        assert prefs["shortcuts"] == {
            "hosts.edit": "Ctrl+K", "printers.edit": "Ctrl+K", "ssh.edit": "Ctrl+K",
            "hosts.remove": "", "printers.remove": "", "ssh.remove": "",
        }  # fmt: skip
    finally:
        win.close()


def test_keys_kept_from_before_apply_at_start(qapp: QApplication, paths: settings.Paths) -> None:
    prefs = {"schema": 1, "shortcuts": {"command.services": "Ctrl+Alt+S", "command.c-share": ""}}
    win = CapyWindow(paths, prefs)
    try:
        assert win.hosts.host_actions["services"].shortcut() == QKeySequence("Ctrl+Alt+S")
        assert win.hosts.host_actions["c-share"].shortcut().isEmpty()
    finally:
        win.close()


def test_a_tip_that_names_a_key_shows_the_key_set_here_at_once(window: CapyWindow) -> None:
    rail, refresh = window.rail, window.hosts.toolbar.refresh_button
    assert rail.home_button.toolTip() == "Home (Ctrl+0)"
    assert rail.settings_button.toolTip() == "Settings (Ctrl+,)"
    assert rail.buttons["hosts"].toolTip() == "Hosts (Ctrl+1)"
    assert refresh.toolTip().endswith(" ticked on a right-click (F5)")
    _press(_page(window), "go.hosts", Qt.Key.Key_7, Qt.KeyboardModifier.ControlModifier)
    assert rail.buttons["hosts"].toolTip() == "Hosts (Ctrl+7)"
    keys = window.keys
    refresh_all = next(r for r in keys.rows if window.hosts.commands.refresh_shown in r.actions)
    keys.set(refresh_all, "F6")
    assert refresh.toolTip().endswith(" ticked on a right-click (F6)")
    keys.set(keys.row("app.settings"), "F9")
    assert rail.settings_button.toolTip() == "Settings (F9)"
    keys.set(keys.row("go.home"), "")  # no key: just the words
    assert rail.home_button.toolTip() == "Home"
    keys.restore(keys.row("go.home"))
    assert rail.home_button.toolTip() == "Home (Ctrl+0)"


def _ink_rows(widget: QWidget, ink: QColor, inside: QRect) -> list[int]:
    """The rows inside `inside` where `widget` shows something close to `ink`."""
    image = widget.grab().toImage()

    def near(x: int, y: int) -> bool:
        c = image.pixelColor(x, y)
        apart = abs(c.red() - ink.red()) + abs(c.green() - ink.green()) + abs(c.blue() - ink.blue())
        return apart < 150

    columns = range(inside.left(), inside.right() + 1)
    return [y for y in range(inside.top(), inside.bottom() + 1) if any(near(x, y) for x in columns)]


@pytest.mark.parametrize(
    ("inside", "caps"),
    [
        (QRect(1, 1, 238, 14), QRect(0, -8, 7, 9)),  # Segoe UI 9 pt in the list's field
        (QRect(1, 1, 238, 15), QRect(0, -8, 7, 9)),
        (QRect(2, 3, 238, 22), QRect(0, -10, 9, 11)),  # a bigger font in a taller field
    ],
)
def test_the_waiting_field_s_capitals_sit_in_its_middle(inside: QRect, caps: QRect) -> None:
    """As much room over the capitals as under them. Qt centres a line's whole height: with
    Segoe UI in the list's field that left 4 px over them and 1 px under (Dante, 0.28.1)."""
    baseline = shortcuts_page.caps_baseline(inside, caps)
    top, bottom = baseline + caps.top(), baseline + caps.top() + caps.height() - 1  # its rows
    over, under = top - inside.top(), inside.bottom() - bottom
    assert abs(over - under) <= 1, (over, under)


def test_the_waiting_field_draws_its_words_inside_its_edges(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    dialog.show_page("shortcuts")
    dialog.show()
    QApplication.processEvents()
    page = dialog.shortcuts
    _press(page, "command.services", Qt.Key.Key_F1)  # refused: red words, a red edge
    catcher = page.table.itemWidget(page.item_of("command.services"), KEY)
    assert isinstance(catcher, KeyCatcher)
    frame = QStyleOptionFrame()
    catcher.initStyleOption(frame)
    inside = catcher.style().subElementRect(QStyle.SubElement.SE_LineEditContents, frame, catcher)
    ink = catcher.palette().color(QPalette.ColorRole.PlaceholderText)
    assert _ink_rows(catcher, ink, inside)  # drawn, in the refusal's red
    room, metrics = catcher.words_rect().width(), catcher.fontMetrics()
    for words in (shortcuts_page.waiting_text(), shortcuts_page.refused_text()):
        assert metrics.horizontalAdvance(words) <= room, words  # in full, never cut (Dante)
    dialog.close()


def test_a_refused_key_s_words_stay_where_they_waited(qapp: QApplication) -> None:
    """A theme may style the refused field alone: the Windows themes draw the waiting field
    natively and give the refused one its red edge from the stylesheet, with less padding, so
    the words moved to 1 px from the red edge (Dante, 0.28.1). They keep the room they had."""
    catcher = KeyCatcher()
    catcher.setStyleSheet(
        'QLineEdit { padding: 0 6px; } QLineEdit[refused="true"] { border: 1px solid red;'
        " padding: 0; }"
    )
    catcher.resize(240, 22)
    catcher.show()
    QApplication.processEvents()
    waiting = catcher.words_rect()
    catcher.refuse()
    catcher.refuse()  # a second refused key: still the room it had while waiting
    QApplication.processEvents()
    frame = QStyleOptionFrame()
    catcher.initStyleOption(frame)
    red = catcher.style().subElementRect(QStyle.SubElement.SE_LineEditContents, frame, catcher)
    assert red.left() < waiting.left() - shortcuts_page.LINE_EDIT_MARGIN  # the red style's own
    assert catcher.words_rect() == waiting
    catcher.close()


def test_a_refused_key_s_row_stays_whole_in_a_narrow_window(window: CapyWindow) -> None:
    """A refusal's reason can take more lines than the line it replaces, and the list gets
    shorter: the waiting row on the list's last line scrolls back into view (Dante, 0.28.1).
    How many lines depends on the fonts, so the list is made shorter here by the window."""
    dialog = window.settings_dialog()
    dialog.show_page("shortcuts")
    dialog.resize(dialog.minimumSizeHint().width(), 600)
    dialog.show()
    QApplication.processEvents()
    page = dialog.shortcuts
    table, view = page.table, page.table.viewport()
    whole = [i for i in page._items() if view.rect().contains(table.visualItemRect(i))]  # pyright: ignore[reportPrivateUsage]
    last = whole[-1]  # the last row showing whole, with more under it
    height = view.height()
    page.change(last)
    catcher = table.itemWidget(last, KEY)
    assert isinstance(catcher, KeyCatcher)
    QTest.keyClick(catcher, Qt.Key.Key_F1)
    dialog.resize(dialog.width(), dialog.height() - 3 * table.sizeHintForRow(0))
    QApplication.processEvents()
    assert view.height() < height
    assert view.rect().contains(table.visualItemRect(last))
    assert table.itemWidget(last, KEY) is catcher  # still waiting, in its row
    dialog.close()


def test_printers_tips_and_guide_show_the_key_set_here(window: CapyWindow) -> None:
    printers = window.tools["printers"]
    assert isinstance(printers, PrintersTool)
    bar, a = printers.toolbar, printers.commands
    assert bar.web_button.toolTip() == "Open the selected printers' web pages (Enter)"
    assert bar.refresh_button.toolTip().endswith(" every printer shown (F5)")
    assert refresh_words(a.refresh_shown).endswith(" until you press it or F5.")
    keys = window.keys
    keys.set(next(r for r in keys.rows if a.refresh_shown in r.actions), "F6")
    assert bar.refresh_button.toolTip().endswith(" every printer shown (F6)")
    assert refresh_words(a.refresh_shown).endswith(" until you press it or F6.")
    web = next(r for r in keys.rows if a.open_web_page in r.actions)
    keys.set(web, "")  # no key: just the words
    assert bar.web_button.toolTip() == "Open the selected printers' web pages"
    keys.set(next(r for r in keys.rows if a.refresh_shown in r.actions), "")
    assert refresh_words(a.refresh_shown).endswith(" until you press it.")
    keys.restore(web)
    assert bar.web_button.toolTip().endswith(" web pages (Enter)")


def test_a_key_another_command_runs_moves_only_when_you_say_so(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = _page(window)
    asked = _answer(monkeypatch, give=False)
    _press(page, "command.services", Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert asked == ["Ctrl+E is already the key for C$ share. Give it to Services instead? "
                     "C$ share is left with no key."]  # fmt: skip
    assert window.keys.key(window.keys.row("command.c-share")) == "Ctrl+E"  # unchanged
    assert window.keys.key(window.keys.row("command.services")) == ""
    _answer(monkeypatch, give=True)
    _press(page, "command.services", Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert window.prefs["shortcuts"] == {"command.services": "Ctrl+E", "command.c-share": ""}
    assert page.item_of("command.c-share").text(KEY) == ""
    assert window.hosts.host_actions["services"].shortcut() == QKeySequence("Ctrl+E")


def test_a_tool_s_key_meets_the_window_s_but_not_another_tool_s(window: CapyWindow) -> None:
    keys = window.keys
    add_host, add_printer = keys.row("hosts.add_host"), keys.row("printers.add_printer")
    assert keys.key(add_host) == keys.key(add_printer) == "Ctrl+N"  # each in its own tool
    assert keys.clash(add_host, "Ctrl+N") is None
    assert keys.clash(add_host, "Ctrl+,") is keys.row("app.settings")  # works everywhere
    assert keys.clash(keys.row("app.settings"), "Ctrl+N") is not None


def test_keys_kept_for_capypanel_and_typed_text_are_refused(window: CapyWindow) -> None:
    page = _page(window)
    for key, mods in (
        (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier),  # help, in 0.30
        (Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier),  # search
        (Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier),  # typed in a name
    ):
        _press(page, "command.services", key, mods)
        assert not page.problem.isHidden() and page.problem.text()
        assert window.keys.key(window.keys.row("command.services")) == ""
    assert (
        page.problem.text()
        == "Shift+A is for typing in names and searches: use it with Ctrl or Alt."
    )
    # A refused key is an error where you're looking: the field stays, red, saying so, and the
    # reason shows under the list in red with its icon (Gabriel's pick, Luna Q1).
    services = page.item_of("command.services")
    catcher = page.table.itemWidget(services, KEY)
    assert isinstance(catcher, KeyCatcher) and catcher.property("refused") is True
    assert catcher.placeholderText() == "Key not allowed"
    assert page.problem.objectName() == "refusal" and not page.problem_icon.isHidden()
    QTest.keyClick(catcher, Qt.Key.Key_F6)  # the next key, in the same field, just works
    assert window.keys.key(window.keys.row("command.services")) == "F6"
    assert page.table.itemWidget(services, KEY) is None
    assert page.problem.text() == RESERVED_LINE
    assert page.problem.objectName() == "hint" and page.problem_icon.isHidden()
    _press(page, "command.services", Qt.Key.Key_F1)
    _press(page, "command.services", Qt.Key.Key_Escape)  # Esc leaves it as it was
    assert page.table.itemWidget(services, KEY) is None
    assert window.keys.key(window.keys.row("command.services")) == "F6"
    assert page.problem.objectName() == "hint"  # the refusal leaves with its field
    assert shortcuts.refused("Ctrl+Shift+S") == "" and shortcuts.refused("F6") == ""
    # Typed text past ASCII too: Ç and é are keys of their own on a Brazilian keyboard, and ´
    # (a dead key) starts an accented letter.
    for key, mods in (
        (Qt.Key.Key_Ccedilla, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Ccedilla, Qt.KeyboardModifier.ShiftModifier),
        (Qt.Key.Key_Eacute, Qt.KeyboardModifier.NoModifier),
        (Qt.Key.Key_Dead_Acute, Qt.KeyboardModifier.NoModifier),
    ):
        typed = shortcuts.portable(QKeySequence(QKeyCombination(mods, key)))
        assert "is for typing" in shortcuts.refused(typed), typed
    ctrl_c_cedilla = QKeyCombination(Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Ccedilla)
    assert shortcuts.refused(shortcuts.portable(QKeySequence(ctrl_c_cedilla))) == ""  # a shortcut
