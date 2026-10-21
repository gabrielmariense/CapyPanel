import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.core import settings
from capypanel.ui.main_window.home import HomePage
from capypanel.ui.settings.pages import SettingRow
from capypanel.ui.tool_catalog import CATALOG, tools_on
from capypanel.ui.tool_switches import ToolsDialog


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


def _window(paths: settings.Paths, **prefs: Any) -> CapyWindow:
    win = CapyWindow(paths, {"schema": 1, **prefs})
    win.resize(1100, 700)
    win.show()
    QApplication.processEvents()
    return win


@pytest.fixture
def home(qapp: QApplication, paths: settings.Paths) -> Iterator[CapyWindow]:
    win = _window(paths, start=settings.START_HOME)
    yield win
    win.close()


def test_the_window_opens_on_home_with_a_tile_per_tool(home: CapyWindow) -> None:
    assert home.shown_tool() is None and home.home.isVisible()
    assert home.rail.home_button.isChecked() and home.rail.home_button.toolTip() == "Home (Ctrl+0)"
    assert not home.hosts.toolbar.isVisible()  # Home has no toolbar
    assert not any(t.status_label.isVisible() for t in home.tools.values())
    assert home.windowTitle().startswith("CapyPanel ")
    tiles = home.home.tiles
    assert [t.tool.tool_id for t in tiles] == ["hosts", "printers"]
    assert [t.keys.text() for t in tiles] == ["Ctrl+1", "Ctrl+2"]
    assert tiles[0].name.text() == "Hosts"
    assert tiles[0].y() == tiles[1].y()  # side by side while they fit
    QTest.mouseClick(tiles[1], Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert home.shown_tool() is home.tools["printers"]
    assert home.prefs[settings.TOOL_KEY] == "printers"
    [ctrl_0] = [a for a in home.actions() if a.shortcut().toString() == "Ctrl+0"]
    ctrl_0.trigger()
    assert home.shown_tool() is None and home.home.isVisible()
    assert home.prefs[settings.TOOL_KEY] == "printers"  # Home isn't a tool to reopen
    home.show_tool("hosts")
    assert not home.rail.home_button.isChecked()
    home.rail.home_button.click()
    assert home.shown_tool() is None


def test_tiles_wrap_into_rows_when_they_don_t_fit(qapp: QApplication) -> None:
    page = HomePage(CATALOG)
    page.resize(500, 700)
    page.show()
    QApplication.processEvents()
    assert page.tiles[1].y() > page.tiles[0].y()  # one under the other
    assert abs(page.tiles[0].x() - page.tiles[1].x()) <= 1  # both centred
    page.close()


@pytest.mark.parametrize(
    ("prefs", "shown"),
    [
        ({}, None),  # Home by default
        ({"start": "last", "tool": "printers"}, "printers"),
        ({"start": "last"}, None),  # no tool shown yet
        ({"start": "printers"}, "printers"),
        ({"start": "gone"}, None),  # a tool that's off, or no more
    ],
)
def test_open_on_startup_picks_what_the_window_shows(
    qapp: QApplication, paths: settings.Paths, prefs: dict[str, Any], shown: str | None
) -> None:
    win = CapyWindow(paths, {"schema": 1, "start": settings.START_HOME, **prefs})
    assert win._shown == shown  # pyright: ignore[reportPrivateUsage]
    win.close()


def test_settings_general_sets_open_on_startup(
    home: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = home.settings_dialog()
    assert dialog.current_page() == "general"  # Settings opens on it
    page = dialog.general
    choices = [page.start.itemText(i) for i in range(page.start.count())]
    assert choices == ["Home page", "The last used tool", "Hosts", "Printers"]
    page.start.setCurrentIndex(3)
    assert settings.load_settings(home.paths.settings_file)["start"] == "printers"
    [tools_row] = [r for r in page.findChildren(SettingRow) if r.name.text() == "Tools that are on"]
    assert tools_row.description.text().startswith("Hosts, Printers. Tools that are off")
    asked: list[list[str]] = []
    dialog.restart_picked.connect(asked.append)
    monkeypatch.setattr(
        ToolsDialog,
        "exec",
        lambda self: (  # Printers unticked, then Restart
            self.ticks["printers"].setChecked(False),
            QDialog.DialogCode.Accepted.value,
        )[1],
    )
    page.choose_tools.click()
    assert asked == [["printers"]]


def test_the_tools_window_keeps_one_tool_on_and_restarts_only_on_a_change(
    qapp: QApplication,
) -> None:
    dialog = ToolsDialog(None, tools=CATALOG, on={"hosts", "printers"})
    hosts, printers = dialog.ticks["hosts"], dialog.ticks["printers"]
    assert not dialog.restart_button.isEnabled() and dialog.at_least_one.isHidden()
    printers.setChecked(False)
    assert dialog.restart_button.isEnabled() and dialog.off() == ["printers"]
    assert not hosts.isEnabled() and not dialog.at_least_one.isHidden()  # the last one on
    printers.setChecked(True)  # back as it was: nothing to restart for
    assert not dialog.restart_button.isEnabled() and hosts.isEnabled()
    dialog.close()


def test_a_restart_saves_the_choice_closes_and_starts_capypanel_again(
    qapp: QApplication, paths: settings.Paths
) -> None:
    started: list[bool] = []
    win = CapyWindow(paths, {"schema": 1}, start_again=lambda: started.append(True))
    win.show()
    win.restart(["printers"])
    QApplication.processEvents()
    assert started == [True] and not win.isVisible()
    saved = settings.load_settings(paths.settings_file)
    assert saved[settings.TOOLS_OFF_KEY] == ["printers"]
    assert "window_geometry" in saved  # closed as on exit: everything saved


def test_tools_that_are_off_aren_t_loaded() -> None:
    assert [t.tool_id for t in tools_on({})] == ["hosts", "printers"]
    assert [t.tool_id for t in tools_on({"tools_off": ["printers", 3]})] == ["hosts"]
    assert [t.tool_id for t in tools_on({"tools_off": ["hosts", "printers"]})] == ["hosts"]
    for info in CATALOG:  # what the catalog says matches the tool itself
        kind = info.load()
        assert (info.tool_id, info.icon) == (kind.TOOL_ID, kind.ICON)  # type: ignore[attr-defined]
    # The start-up, the window and the catalog import no tool by themselves.
    code = (
        "import sys; import capypanel.ui.app; "
        "loaded = [m for m in sys.modules if m.startswith(('capypanel.ui.hosts_tool', "
        "'capypanel.ui.printers_tool'))]; print(loaded)"
    )
    found = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert found == "[]"
