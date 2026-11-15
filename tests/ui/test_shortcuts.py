"""Settings › CapyPanel › Keyboard shortcuts: every command a key can run, today's keys as the
defaults, a person's changes kept and applied at once, and the keys no command may take."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

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
    edit = keys.row("list.edit")  # one row, one key, for Hosts and Printers
    assert edit.places == ["hosts", "printers"] and len(edit.actions) == 2
    assert keys.key(edit) == "F2"
    assert keys.row("hosts.add_host").places == ["hosts"]
    assert keys.row("printers.add_printer").places == ["printers"]
    page = _page(window)
    item = page.item_of("list.edit")
    assert [item.text(c) for c in range(3)] == ["Edit…", "Hosts, Printers", "F2"]
    assert page.item_of("app.settings").text(1) == "Everywhere"
    assert page.item_of("hosts.connect_host").text(KEY) == "Enter"  # Windows' name for Return
    assert page.table.property("mostRows") == shortcuts_page.ROWS  # a long list, a tall table


def test_a_new_key_is_kept_and_works_at_once_in_every_tool(window: CapyWindow) -> None:
    page = _page(window)
    _press(page, "list.edit", Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert page.item_of("list.edit").text(KEY) == "Ctrl+K"
    row = window.keys.row("list.edit")
    assert all(a.shortcut() == QKeySequence("Ctrl+K") for a in row.actions)
    assert window.prefs["shortcuts"] == {"list.edit": "Ctrl+K"}  # only what differs
    page.table.setCurrentItem(page.item_of("list.edit"))
    assert page.restore.isEnabled() and page.clear.isEnabled()
    page.restore.click()
    assert window.prefs["shortcuts"] == {} and row.actions[0].shortcut() == QKeySequence("F2")
    assert not page.restore.isEnabled()
    page.clear.click()  # no key at all
    assert window.prefs["shortcuts"] == {"list.edit": ""} and row.actions[1].shortcut().isEmpty()
    assert page.item_of("list.edit").text(KEY) == ""


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
    assert shortcuts.refused("Ctrl+Shift+S") == "" and shortcuts.refused("F6") == ""
