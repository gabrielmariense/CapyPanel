from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
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
    assert rail.hosts_button.isChecked() and rail.hosts_button.toolTip() == "Hosts (Ctrl+1)"
    rail.hosts_button.click()  # the tool shown, clicked again, stays picked
    assert rail.hosts_button.isChecked()
    opened: list[object] = []
    monkeypatch.setattr(window, "open_settings", lambda page=None: opened.append(page))
    rail.settings_button.click()  # the gear at the bottom opens Settings
    assert opened == [None]
