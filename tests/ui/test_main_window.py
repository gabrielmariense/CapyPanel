import json
from pathlib import Path

from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.ui.main_window.window import MainWindow


def _portable_paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


def test_window_opens_with_a_file_menu(qapp: QApplication, tmp_path: Path) -> None:
    window = MainWindow(_portable_paths(tmp_path), {"schema": 1})
    assert window.windowTitle().startswith("CapyPanel")
    assert [a.text() for a in window.menuBar().actions()] == ["&File"]


def test_closing_saves_the_window_size(qapp: QApplication, tmp_path: Path) -> None:
    paths = _portable_paths(tmp_path)
    window = MainWindow(paths, {"schema": 1, "kept": True})
    window.show()
    window.close()
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["kept"] is True
    assert isinstance(saved["window_geometry"], str)
