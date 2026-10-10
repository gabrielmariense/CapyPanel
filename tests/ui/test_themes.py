import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QListWidget,
    QMenu,
    QMessageBox,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from capypanel.core import settings
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.themes import engine as themes


@pytest.fixture(autouse=True)
def back_to_default(qapp: QApplication) -> Iterator[None]:
    yield
    if themes.current() is not themes.DEFAULT_THEME:  # a theme switch restyles every window
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


# Every accent colour Windows offers in Settings > Personalization > Colors, plus extremes and a
# deep custom purple: anything made from the accent must work with all of them.
WINDOWS_ACCENTS = [
    "#ffb900", "#ff8c00", "#f7630c", "#ca5010", "#da3b01", "#ef6950", "#d13438", "#ff4343",
    "#e74856", "#e81123", "#ea005e", "#c30052", "#e3008c", "#bf0077", "#c239b3", "#9a0089",
    "#0078d7", "#0063b1", "#8e8cd8", "#6b69d6", "#8764b8", "#744da9", "#b146c2", "#881798",
    "#0099bc", "#2d7d9a", "#00b7c3", "#038387", "#00b294", "#018574", "#00cc6a", "#10893e",
    "#7a7574", "#5d5a58", "#68768a", "#515c6b", "#567c73", "#486860", "#498205", "#107c10",
    "#767676", "#4c4a48", "#69797e", "#4a5459", "#647c64", "#525e54", "#847545", "#7e735f",
]  # fmt: skip
ACCENTS = [*WINDOWS_ACCENTS, "#0078d4", "#350461", "#5e08a9", "#ffffff", "#000000"]


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_selection_is_visible_and_readable_with_any_accent(scheme: str, accent: str) -> None:
    c = themes.NATIVE_TOKENS[scheme]
    tint = themes.selection_tint(QColor(accent), c["card"], c["text"])
    assert themes.contrast_ratio(tint, c["card"]) >= 1.35
    assert themes.contrast_ratio(c["text"], tint) >= 4.5


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_a_marked_menu_row_stands_out_with_any_accent(scheme: str, accent: str) -> None:
    c = themes.NATIVE_TOKENS[scheme]
    tint = themes.mark_tint(QColor(accent), c["card"], c["text"])
    assert themes.contrast_ratio(tint, c["card"]) >= 1.6
    assert themes.contrast_ratio(c["text"], tint) >= 4.5


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_accent_headings_are_readable_with_any_accent(scheme: str, accent: str) -> None:
    c = themes.NATIVE_TOKENS[scheme]
    heading = themes.readable_on(QColor(accent), c["card"], c["text"])
    assert themes.contrast_ratio(heading, c["card"]) >= 4.5


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("accent", ACCENTS)
def test_the_groups_heading_reads_while_a_group_is_dragged_on_it(scheme: str, accent: str) -> None:
    c = themes.NATIVE_TOKENS[scheme]
    sel = themes.selection_tint(QColor(accent), c["card"], c["text"])
    drop = themes.readable_on(QColor(accent), sel, c["text"])
    assert themes.contrast_ratio(drop, sel) >= 4.5


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_accent_text_and_buttons_read_in_every_custom_theme(theme: themes.Theme) -> None:
    colors = theme.colors
    accent = QColor(colors["accent"])
    heading = themes.readable_on(accent, colors["card"], colors["text"])
    assert themes.contrast_ratio(heading, colors["card"]) >= 4.5
    drop = themes.readable_on(accent, colors["sel_solid"], colors["text"])
    assert themes.contrast_ratio(drop, colors["sel_solid"]) >= 4.5
    for fill in (accent, QColor(colors["accent_hover"])):  # the OK button, and hovered
        assert themes.contrast_ratio("#ffffff", themes.button_fill(fill)) >= 4.5


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
    # Custom themes draw their own checkbox ticks and arrows; a missing file means an empty
    # checked box, or a drop-down or number box that doesn't look clickable.
    sheet = themes.stylesheet(theme)
    images = set(re.findall(r'url\("([^"]+)"\)', sheet))
    assert len(images) == 3  # the tick, the down arrow, and number boxes' up arrow
    assert all(Path(image).is_file() for image in images), images


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_dialog_buttons_never_cut_their_text(qapp: QApplication, theme: themes.Theme) -> None:
    # A fixed minimum width in the stylesheet let message boxes squeeze long button labels.
    themes.apply(theme)
    box = QMessageBox(QMessageBox.Icon.Question, "Remove group", "What should happen to them?")
    buttons = [box.addButton(text, QMessageBox.ButtonRole.AcceptRole) for text in (
        "Move them into “Campainhas”", "Remove everything", "Cancel"
    )]  # fmt: skip
    box.show()
    qapp.processEvents()
    for button in buttons:
        assert button.width() > button.fontMetrics().horizontalAdvance(button.text())
    box.close()


def test_rows_placed_before_the_theme_arrived_never_overlap(qapp: QApplication) -> None:
    # Choosing a row before the list is shown places the rows without the theme's padding.
    themes.apply(themes.Registry().find("capypanel-dark"))
    dialog = QDialog()
    flat, tree = QListWidget(), QTreeWidget()
    flat.addItems(["General", "Host lists", "Connections"])
    flat.setCurrentRow(0)
    items = [QTreeWidgetItem([name]) for name in ("Offices", "Clinics", "Labs")]
    tree.addTopLevelItems(items)
    tree.setCurrentItem(items[0])
    layout = QVBoxLayout(dialog)
    layout.addWidget(flat)
    layout.addWidget(tree)
    dialog.show()
    qapp.processEvents()
    rows = [flat.visualItemRect(flat.item(i)) for i in range(3)]
    rows += [tree.visualItemRect(item) for item in items]
    dialog.close()
    for above, below in [
        *zip(rows[:2], rows[1:3], strict=True),
        *zip(rows[3:5], rows[4:], strict=True),
    ]:
        assert below.top() > above.bottom(), f"rows overlap: {above} and {below}"
    assert all(r.height() > flat.fontMetrics().height() for r in rows)


def test_menus_with_ticks_line_up_with_other_menus(qapp: QApplication) -> None:
    # Qt adds a tick's width before every item of a menu with ticks, submenu titles included.
    themes.apply(themes.Registry().find("paper"))
    plain, ticks, mixed = QMenu(), QMenu(), QMenu()
    plain.addAction("Status bar")
    ticks.addAction("Status bar").setCheckable(True)
    # Unmarked it was 18 px wider; Qt sizes it 4 px wider than it draws the text.
    assert ticks.sizeHint().width() - plain.sizeHint().width() == 4
    mixed.addMenu("Language")  # a submenu title beside a ticked item: marked too
    tick = mixed.addAction("Status bar")
    assert mixed.property("ticks") is not True
    tick.setCheckable(True)
    assert mixed.property("ticks") is True


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_number_boxes_show_their_arrows(qapp: QApplication, theme: themes.Theme) -> None:
    # Styling a spin box drops Fusion's arrows: the buttons were empty squares.
    themes.apply(theme)
    box = QSpinBox()
    box.resize(120, 32)
    box.show()
    qapp.processEvents()
    image = box.grab().toImage()
    box.close()
    width, height = image.width(), image.height()
    for top, bottom in ((4, height // 2 - 3), (height // 2 + 3, height - 4)):  # up, then down
        colors = {
            image.pixelColor(x, y).lightness()
            for x in range(width - 15, width - 4)
            for y in range(top, bottom)
        }
        assert max(colors) - min(colors) > 40, "an arrow button is empty"
