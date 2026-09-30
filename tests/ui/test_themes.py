import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.themes import engine as themes


@pytest.fixture(autouse=True)
def back_to_default(qapp: QApplication) -> Iterator[None]:
    yield
    themes.apply(themes.DEFAULT_THEME)


def test_all_shipped_themes_load() -> None:
    ids = [t.id for t in themes.Registry().all()]
    assert ids == [
        "windows-system",
        "windows-dark",
        "windows-light",
        "capypanel-dark",
        "capypanel-light",
        "graphite",
        "paper",
    ]


def test_unknown_or_missing_theme_falls_back_to_the_default() -> None:
    registry = themes.Registry()
    assert registry.find("no-such-theme") is themes.DEFAULT_THEME
    assert registry.find(None) is themes.DEFAULT_THEME


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{ nope", "JSON"),
        ({"base": "dark"}, "name"),
        ({"name": "X", "base": "blue"}, "base"),
        ({"name": "X", "base": "dark", "colors": {"sparkle": "#fff"}}, "unknown colour"),
        ({"name": "X", "base": "dark", "colors": {"accent": "not-a-colour"}}, "not a colour"),
        ({"name": "X", "base": "dark", "radius": 99}, "radius"),
    ],
)
def test_broken_theme_files_are_rejected_and_skipped(
    tmp_path: Path, content: object, reason: str
) -> None:
    path = tmp_path / "broken.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        themes.load_theme_file(path)
    assert themes.Registry(tmp_path).shipped == []


def test_every_theme_applies_in_any_order(qapp: QApplication) -> None:
    order = themes.Registry().all()
    for theme in [*order, *reversed(order)]:  # native <-> custom and custom <-> custom switches
        themes.apply(theme)
        assert themes.current() is theme
        if theme.engine == "custom":
            assert qapp.styleSheet()
            window = qapp.palette().color(QPalette.ColorRole.Window)
            assert window == QColor(theme.colors["bg"])
        else:
            assert qapp.styleSheet() == ""
            assert qapp.style().name() == "windows11"


def test_picking_a_theme_in_the_menu_applies_and_remembers_it(
    qapp: QApplication, tmp_path: Path
) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    window = MainWindow(paths, {"schema": 1})
    window.set_theme("graphite")
    assert themes.current().id == "graphite"
    checked = [a.data() for a in window._theme_group.actions() if a.isChecked()]
    assert checked == ["graphite"]
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["theme"] == "graphite"
    window.close()
