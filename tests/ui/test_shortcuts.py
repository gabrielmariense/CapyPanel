"""Settings › CapyPanel › Keyboard shortcuts: every command a key can run, today's keys as the
defaults, a person's changes kept and applied at once, and the keys no command may take."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTreeWidgetItem

from capypanel.core import settings
from capypanel.ui import shortcuts
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


def _headings(page: ShortcutsPage) -> list[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]]:
    """Each heading row with the command rows under it."""
    table = page.table
    found: list[tuple[QTreeWidgetItem, list[QTreeWidgetItem]]] = []
    for i in range(table.topLevelItemCount()):
        item = table.topLevelItem(i)
        assert item is not None
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
    assert [h.text(0) for h, _rows in headings] == ["File", "View", "Help", "Hosts", "Printers"]
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
    assert page.problem.text() == "F1, Esc, Ctrl+F and Tab are kept for CapyPanel itself."


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
        for tool in ("hosts", "printers"):
            assert keys.key(keys.row(f"{tool}.edit")) == "Ctrl+K", tool
            assert keys.key(keys.row(f"{tool}.remove")) == "", tool
        assert prefs["shortcuts"] == {
            "hosts.edit": "Ctrl+K", "printers.edit": "Ctrl+K",
            "hosts.remove": "", "printers.remove": "",
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
    _press(page, "command.services", Qt.Key.Key_Escape)  # Esc leaves it as it was
    assert page.table.itemWidget(page.item_of("command.services"), KEY) is None
    assert window.keys.key(window.keys.row("command.services")) == ""
    _press(page, "command.services", Qt.Key.Key_F6)  # a key taken: the reserved keys again
    assert page.problem.text() == "F1, Esc, Ctrl+F and Tab are kept for CapyPanel itself."
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
