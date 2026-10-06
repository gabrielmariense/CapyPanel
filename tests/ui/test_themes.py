import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
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


CUSTOM = [t for t in themes.Registry().all() if t.engine == "custom"]


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_text_is_readable_in_every_custom_theme(theme: themes.Theme) -> None:
    # WCAG AA: at least 4.5:1 for normal text, on every surface it's drawn on.
    # Selected rows always use the main text colour.
    pairs = [(t, s) for t in ("text", "text2", "text3") for s in ("bg", "card", "chrome")]
    for text, surface in [*pairs, ("text", "sel_solid")]:
        ratio = themes.contrast_ratio(theme.colors[text], theme.colors[surface])
        assert ratio >= 4.5, f"{theme.id}: {text} on {surface} is only {ratio:.1f}:1"


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_structure_is_visible_in_every_custom_theme(theme: themes.Theme) -> None:
    # Borders, panes, header/footer and the selected row must stand out from what's around them.
    c, ratio = theme.colors, themes.contrast_ratio
    checks = {
        "border on card": (ratio(c["border"], c["card"]), 2.2),
        "border on bg": (ratio(c["border"], c["bg"]), 1.5),
        "card on bg": (ratio(c["card"], c["bg"]), 1.25),
        "chrome on bg": (ratio(c["chrome"], c["bg"]), 1.15),
        "selection on card": (ratio(c["sel_solid"], c["card"]), 1.35),
    }
    for name, (value, minimum) in checks.items():
        assert value >= minimum, f"{theme.id}: {name} is {value:.2f}:1, needs {minimum}"


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_native_overlay_is_readable_and_visible(scheme: str) -> None:
    c, ratio = themes.NATIVE_TOKENS[scheme], themes.contrast_ratio
    for text in ("text", "text2"):
        for surface in ("bg", "card", "chrome"):
            assert ratio(c[text], c[surface]) >= 4.5, f"{scheme}: {text} on {surface}"
    assert ratio(c["border"], c["card"]) >= 2.2
    assert ratio(c["border"], c["bg"]) >= 1.5
    assert ratio(c["card"], c["bg"]) >= 1.25
    assert ratio(c["chrome"], c["bg"]) >= 1.15


ACCENTS = ["#0078d4", "#350461", "#ffb900", "#107c10", "#e81123", "#ffffff", "#000000"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_selection_is_visible_and_readable_with_any_accent(scheme: str, accent: str) -> None:
    c = themes.NATIVE_TOKENS[scheme]
    tint = themes.selection_tint(QColor(accent), c["card"], c["text"])
    assert themes.contrast_ratio(tint, c["card"]) >= 1.35
    assert themes.contrast_ratio(c["text"], tint) >= 4.5


def test_every_theme_applies_in_any_order(qapp: QApplication) -> None:
    order = themes.Registry().all()
    for theme in [*order, *reversed(order)]:  # native <-> custom and custom <-> custom switches
        themes.apply(theme)
        assert themes.current() is theme
        if theme.engine == "custom":
            assert qapp.styleSheet()
            window = qapp.palette().color(QPalette.ColorRole.Window)
            assert window == QColor(theme.colors["bg"])
        else:  # native widgets plus the structure layer for the resolved dark/light
            overlay = themes.NATIVE_TOKENS[themes.native_scheme()]
            assert overlay["border"] in qapp.styleSheet()


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


def test_clicking_a_row_draws_no_focus_box(qapp: QApplication, tmp_path: Path) -> None:
    # Windows drew a focus box around the clicked row, which looked broken on the selection tint.
    # A box edge shows up as a line where nearly the whole row is dark (in Windows light).
    (tmp_path / settings.PORTABLE_MARKER).touch()
    window = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    window.set_theme("windows-light")
    window.show()
    window.activateWindow()  # the box only appears in the active window
    qapp.processEvents()
    tree = window.nav.groups
    [item] = tree.findItems("Default group", Qt.MatchFlag.MatchStartsWith)
    rect = tree.visualItemRect(item)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    image = tree.viewport().grab().toImage()
    window.close()
    for y in range(rect.top(), rect.bottom() + 1):
        dark = sum(
            image.pixelColor(x, y).lightness() < 90 for x in range(rect.left(), rect.right())
        )
        assert dark < rect.width() * 0.8, f"a focus box edge was drawn at line {y}"


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_images_the_stylesheet_uses_ship_with_the_themes(theme: themes.Theme) -> None:
    # Custom themes draw their own checkbox ticks and drop-down arrows; a missing file
    # means an empty checked box or a drop-down that doesn't look clickable.
    sheet = themes.stylesheet(theme)
    images = set(re.findall(r'url\("([^"]+)"\)', sheet))
    assert len(images) == 2  # the tick, and the arrow of drop-downs and toolbar buttons
    assert all(Path(image).is_file() for image in images), images
