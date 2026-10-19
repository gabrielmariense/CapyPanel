from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from capypanel.core import settings
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.main_window.tool import Shell, Tool
from capypanel.ui.main_window.toolbar import ToolBar
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    yield win
    win.close()


def test_the_rail_runs_down_the_left_edge_beside_the_tool_s_toolbar(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.resize(1000, 500)
    window.show()
    QApplication.processEvents()
    rail, toolbar = window.rail, window.hosts.toolbar
    assert rail.x() == 0 and rail.height() > toolbar.height()  # from the menu bar down
    assert toolbar.mapTo(window, toolbar.rect().topLeft()).x() == rail.width()  # beside it
    assert rail.buttons["hosts"].isChecked() and rail.buttons["hosts"].toolTip() == "Hosts (Ctrl+1)"
    rail.buttons["hosts"].click()  # the tool shown, clicked again, stays picked
    assert rail.buttons["hosts"].isChecked()
    opened: list[object] = []
    monkeypatch.setattr(window, "open_settings", lambda page=None: opened.append(page))
    rail.settings_button.click()  # the gear at the bottom opens Settings
    assert opened == [None]


class _Notes(Tool):
    """A made-up second tool: the shell builds everything from the tools it's given."""

    TOOL_ID, ICON = "notes", "report-analytics"

    def __init__(self, shell: Shell) -> None:
        super().__init__(shell, ToolBar())
        self.show_lines = QAction("&Lines", self, checkable=True)
        self.status_label.setText("No notes")
        self.busy = QLabel("busy")

    def tool_name(self) -> str:
        return "Notes"

    def menu_name(self) -> str:
        return "&Notes"

    def title(self) -> str:
        return "Desk notes"

    def status_widgets(self) -> list[QWidget]:
        return [self.busy]

    def view_actions(self) -> list[list[QAction]]:
        return [[self.show_lines]]


def test_the_rail_view_toolbar_tool_and_status_bar_follow_the_tool_shown(
    qapp: QApplication, tmp_path: Path
) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    win = MainWindow(paths, {"schema": 1}, tools=(HostsTool, _Notes))
    win.show()
    QApplication.processEvents()
    notes = win.tools["notes"]
    assert isinstance(notes, _Notes)
    assert list(win.rail.buttons) == ["hosts", "notes"]
    assert win.rail.buttons["notes"].toolTip() == "Notes (Ctrl+2)"
    view = win._view_menu  # pyright: ignore[reportPrivateUsage]
    texts = [a.text().split("\t")[0] for a in view.actions() if a.text()]  # no shortcut
    assert texts[:3] == ["&Hosts", "&Notes", "&Groups pane"]  # the tools, then Hosts' panels
    tool_keys = [a for a in win.actions() if a.shortcut().toString() == "Ctrl+2"]
    tool_keys[0].trigger()  # Ctrl+2
    assert win.rail.buttons["notes"].isChecked() and not win.hosts.isVisible()
    assert notes.isVisible() and notes.toolbar.isVisible() and not win.hosts.toolbar.isVisible()
    assert [a.text() for a in view.actions() if a.text()][2] == "&Lines"  # its panels now
    assert notes.status_label.isVisible() and not win.hosts.status_label.isVisible()
    assert notes.busy.isVisible()
    stop = win.hosts.status_widgets()[1]
    stop.show()  # a Refresh started in Hosts: its Stop stays out of Notes' status bar
    assert not stop.isVisible()
    win.show_tool("hosts")
    assert stop.isVisible() and not notes.busy.isVisible()
    stop.hide()
    win.show_tool("notes")
    assert win.windowTitle().startswith("Desk notes — CapyPanel")
    win.close()
    again = MainWindow(
        paths, settings.load_settings(paths.settings_file), tools=(HostsTool, _Notes)
    )
    assert again.shown_tool() is again.tools["notes"]  # opens on the tool last shown
    assert set(settings.load_settings(paths.settings_file)["tools"]) == {"hosts", "notes"}
    again.close()
