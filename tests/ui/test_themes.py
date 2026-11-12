import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette
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
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.remote.status import Status
from capypanel.ui.main_window.tray import counted_icon
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
        ({"name": "X", "base": "dark", "control_radius": -1}, "control_radius"),
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
    # Selected rows always use the main text colour. The hint grey (text3) is drawn on panes;
    # its one label on the window's own background gets a darker step.
    pairs = [(t, s) for t in ("text", "text2") for s in ("bg", "card", "chrome")]
    for text, surface in [*pairs, ("text", "sel_solid"), ("text3", "card")]:
        ratio = themes.contrast_ratio(theme.colors[text], theme.colors[surface])
        assert ratio >= 4.5, f"{theme.id}: {text} on {surface} is only {ratio:.1f}:1"
    heading = _rule(themes.stylesheet(theme), "QLabel#groupHeading")
    color = re.search(r"color: rgba[(](\d+), (\d+), (\d+)", heading) or re.search(
        r"color: #(..)(..)(..)", heading
    )
    assert color is not None
    red, green, blue = (int(c, 16 if "#" in color[0] else 10) for c in color.groups())
    on_window = themes.contrast_ratio(QColor(red, green, blue).name(), theme.colors["bg"])
    assert on_window >= 4.5, f"{theme.id}: a group's heading on the window is {on_window:.1f}:1"


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_hints_step_back_from_the_text_beside_them(theme: themes.Theme) -> None:
    # Three real levels of text in every theme: "Nobody" and "Not checked" are a visible step
    # lighter than the second level, as they always were in the dark themes.
    c, ratio = theme.colors, themes.contrast_ratio
    assert ratio(c["text2"], c["card"]) - ratio(c["text3"], c["card"]) >= 1.5, theme.id


def _surfaces() -> list[tuple[str, str, str, str, dict[str, str]]]:
    """Each built-in theme's pane, selection and text, with its status colours. The Windows
    themes with Windows' default accent; any other accent is the next test's."""
    found = []
    for theme in CUSTOM:
        c = theme.colors
        status = {key: c[key] for key in themes.STATUS_KEYS}
        found.append((theme.id, c["card"], c["sel_solid"], c["text"], status))
    for scheme in ("dark", "light"):
        c = themes.NATIVE_TOKENS[scheme]
        tint = themes.selection_tint(QColor("#0078d4"), c["card"], c["text"])
        status = {key: themes.TOKENS[scheme][key] for key in themes.STATUS_KEYS}
        found.append((f"windows-{scheme}", c["card"], tint, c["text"], status))
    return found


@pytest.mark.parametrize("surface", _surfaces(), ids=lambda s: s[0])
def test_status_colours_read_in_every_built_in_theme(
    surface: tuple[str, str, str, str, dict[str, str]],
) -> None:
    """Amber, green, red, grey and blue as each theme has them: words on the pane (4.5:1) and
    at least a dot on a selected row (3:1); amber is a whole row's text, so 4.5:1 there too.
    The picked colours pass as written: the fallback doesn't have to move any of them."""
    theme_id, card, selection, text, status = surface
    for key, color in status.items():
        on_pane, on_selection = themes.status_floors(key)
        got = themes.contrast_ratio(color, card), themes.contrast_ratio(color, selection)
        assert got[0] >= on_pane, f"{theme_id}: {key} {color} is {got[0]:.2f}:1 on the pane"
        assert got[1] >= on_selection, f"{theme_id}: {key} {color} is {got[1]:.2f}:1 when picked"
        assert themes.fit_status(key, color, card, selection, text) == QColor(color).name()
    # A count on the red, and the words on a button filled in amber.
    assert themes.contrast_ratio("#ffffff", themes.button_fill(QColor(status["stopped"]))) >= 4.5
    amber = status["attention"]
    assert themes.contrast_ratio(themes.text_on(amber), amber) >= 4.5, theme_id


def test_amber_is_one_gold_and_paper_keeps_its_own() -> None:
    registry = themes.Registry()
    assert registry.find("capypanel-dark").colors["attention"] == "#e3b341"
    assert registry.find("graphite").colors["attention"] == "#e3b341"
    assert registry.find("capypanel-light").colors["attention"] == "#7d5a00"
    paper = registry.find("paper").colors
    assert paper["attention"] == "#805300"  # further from its orange accent, set in its file
    assert themes.contrast_ratio(paper["attention"], paper["accent"]) >= 1.25


def test_a_theme_file_without_status_colours_gets_readable_ones(tmp_path: Path) -> None:
    # Its pane is a mid grey, where the dark set's red and green are hard to read.
    odd = {"card": "#55575e", "sel_solid": "#3d5a80"}
    path = tmp_path / "odd.json"
    path.write_text(json.dumps({"name": "Odd", "base": "dark", "colors": odd}), encoding="utf-8")
    theme = themes.load_theme_file(path)
    moved = 0
    for key in themes.STATUS_KEYS:
        on_pane, on_selection = themes.status_floors(key)
        assert themes.contrast_ratio(theme.colors[key], odd["card"]) >= on_pane, key
        assert themes.contrast_ratio(theme.colors[key], odd["sel_solid"]) >= on_selection, key
        moved += theme.colors[key] != themes.TOKENS["dark"][key]
    assert moved
    # A colour the file sets is the file's, as written.
    own = {**odd, "stopped": "#ff0000"}
    path.write_text(json.dumps({"name": "Odd", "base": "dark", "colors": own}), encoding="utf-8")
    assert themes.load_theme_file(path).colors["stopped"] == "#ff0000"
    path.write_text(
        json.dumps({"name": "Odd", "base": "dark", "colors": {"danger": "#ff0000"}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown colour"):  # one red: "stopped"
        themes.load_theme_file(path)


def test_every_theme_has_its_ink_colours() -> None:
    for theme in CUSTOM:
        assert all(QColor.isValidColorName(theme.colors[key]) for key in themes.INK_KEYS)
    light, dark = themes.TOKENS["light"], themes.TOKENS["dark"]
    assert themes.contrast_ratio(light["ink_black"], "#ffffff") >= 10  # black toner reads black
    assert themes.contrast_ratio(light["ink_yellow_edge"], "#ffffff") >= themes.MARK_CONTRAST
    assert dark["ink_yellow_edge"] == dark["ink_yellow"]  # no edge to see on a dark pane


def _dot(icon: object) -> str:
    """The colour in the middle of a status dot."""
    assert isinstance(icon, QIcon)
    image = icon.pixmap(10, 10).toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name()


def test_a_theme_switch_redraws_what_was_drawn_in_status_colours(
    qapp: QApplication, tmp_path: Path
) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hosts, host = HostList().add_host("DESK-01", NO_GROUP, address="192.0.2.10")
    listfile.save(tmp_path / "office.json", hosts, expected=None)
    window = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    window.hosts.open_list(tmp_path / "office.json")
    window.set_theme("capypanel-dark")
    tool = window.hosts
    tool._status_found[host.id] = (Status.ONLINE, datetime.now(UTC), None)
    tool.table.show_cells(host.id, tool._cells(host.id))
    row = tool.table._rows[host.id]
    assert themes.status_color("online") == themes.TOKENS["dark"]["online"]
    assert _dot(row.icon(tool.table.STATUS)) == themes.TOKENS["dark"]["online"]
    assert themes.status_color(Status.NOT_FOUND) == themes.TOKENS["dark"]["attention"]
    badge = counted_icon(3).pixmap(32, 32).toImage().pixelColor(28, 3).name()
    assert badge == themes.button_fill(QColor(themes.TOKENS["dark"]["stopped"]))

    window.set_theme("paper")
    assert _dot(row.icon(tool.table.STATUS)) == themes.TOKENS["light"]["online"]
    assert themes.status_color("attention") == "#805300"
    assert themes.ink_colors()["black"] == themes.TOKENS["light"]["ink_black"]

    # The Windows themes: the light set on a light Windows, the dark one on a dark Windows.
    window.set_theme("windows-light")
    assert _dot(row.icon(tool.table.STATUS)) == themes.TOKENS["light"]["online"]
    # Windows switching dark and light under "follow system" reaches the tools the same way.
    seen = []
    themes.switches().switched.connect(lambda: seen.append(themes.current().id))
    themes.apply(themes.Registry().find("capypanel-dark"))
    assert seen == ["capypanel-dark"]
    assert _dot(row.icon(tool.table.STATUS)) == themes.TOKENS["dark"]["online"]
    window.close()


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
def test_status_colours_read_on_a_selection_of_any_accent(scheme: str, accent: str) -> None:
    # The Windows themes' selected row is a tint of the accent the person picked in Windows.
    c = themes.NATIVE_TOKENS[scheme]
    tint = themes.selection_tint(QColor(accent), c["card"], c["text"])
    for key in themes.STATUS_KEYS:
        color = themes.fit_status(key, themes.TOKENS[scheme][key], c["card"], tint, c["text"])
        on_pane, on_selection = themes.status_floors(key)
        assert themes.contrast_ratio(color, c["card"]) >= on_pane, key
        assert themes.contrast_ratio(color, tint) >= on_selection, key


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


def test_picking_a_theme_applies_and_remembers_it(qapp: QApplication, tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    window = CapyWindow(paths, {"schema": 1})
    window.set_theme("graphite")
    assert themes.current().id == "graphite"
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["theme"] == "graphite"
    window.close()


def test_clicking_a_row_draws_no_focus_box(qapp: QApplication, tmp_path: Path) -> None:
    # Windows drew a focus box around the clicked row, which looked broken on the selection tint.
    # A box edge shows up as a line where nearly the whole row is dark (in Windows light).
    (tmp_path / settings.PORTABLE_MARKER).touch()
    window = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    window.set_theme("windows-light")
    window.show()
    window.activateWindow()  # the box only appears in the active window
    qapp.processEvents()
    tree = window.hosts.nav.groups
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


def test_dropdowns_open_at_once_in_every_theme(qapp: QApplication) -> None:
    # Windows' "slide open" made a long dropdown list roll open in visible steps.
    QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)  # as on a PC with it on
    for theme in themes.Registry().all():
        themes.apply(theme)
        assert not QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    themes.apply(themes.DEFAULT_THEME)


def test_a_switch_sets_the_theme_s_stylesheet_only_once(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each stylesheet set restyles every widget, the slow part of a switch: from a Windows
    # theme it was set twice.
    sheets: list[str] = []
    set_sheet = QApplication.setStyleSheet

    def counting(app: QApplication, sheet: str) -> None:
        sheets.append(sheet)
        set_sheet(app, sheet)

    monkeypatch.setattr(QApplication, "setStyleSheet", counting)
    registry = themes.Registry()
    paper = registry.find("paper")
    for start in ("capypanel-dark", "windows-light"):
        themes.apply(registry.find(start))
        sheets.clear()
        themes.apply(paper)
        assert sheets.count(themes.stylesheet(paper)) == 1, start


def test_home_tiles_take_the_new_theme_s_icon_colour(qapp: QApplication, tmp_path: Path) -> None:
    # Switching between two custom themes left the tiles' icons in the previous theme's colour.
    (tmp_path / settings.PORTABLE_MARKER).touch()
    window = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    window.set_theme("capypanel-dark")
    window.set_theme("paper")
    for tile in window.home.tiles:
        want = tile.palette().color(QPalette.ColorRole.Text)
        image = tile.badge.pixmap().toImage()
        inked = [
            QColor(image.pixel(x, y))
            for y in range(image.height())
            for x in range(image.width())
            if QColor(image.pixelColor(x, y)).alpha() == 255
        ]
        assert inked
        assert all(
            abs(c.red() - want.red()) + abs(c.green() - want.green()) + abs(c.blue() - want.blue())
            < 24
            for c in inked
        ), tile.tool.name
    window.close()


def test_the_font_is_the_first_family_this_pc_has_alone(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QFontDatabase, "families", lambda *_a: ["Arial", "Segoe UI", "Tahoma"])
    assert themes.installed(("Segoe UI Variable Text", "Segoe UI")) == ["Segoe UI"]  # Windows 10
    assert themes.installed(("TAHOMA", "Segoe UI")) == ["TAHOMA"]  # any case
    assert themes.installed(("No Such Font", "Nor This")) == ["No Such Font", "Nor This"]
    themes.apply(themes.Registry().find("capypanel-dark"))
    assert qapp.font().families() == ["Segoe UI"]


def _rule(sheet: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r" \{([^}]*)\}", sheet)
    assert found is not None, selector
    return found[1]


def test_corners_come_in_two_sizes_from_the_theme(tmp_path: Path) -> None:
    for theme_id in ("capypanel-dark", "capypanel-light"):
        theme = themes.Registry().find(theme_id)
        assert (theme.radius, theme.control) == (6, 4)  # panels and menus; what you click
        sheet = themes.stylesheet(theme)
        assert "border-radius: 6px" in _rule(sheet, "QMenu")
        assert "border-radius: 6px" in _rule(sheet, "QFrame#card")
        assert "border-radius: 4px" in _rule(sheet, "QMenu::item")
        assert "border-radius: 4px" in _rule(sheet, "QToolButton#commandButton")
        assert "border-radius: 4px" in _rule(sheet, "QProgressBar#thin")  # bars: a control
        assert "border-radius: 6px" in _rule(sheet, "QFrame#attentionStrip")  # strips: a panel
    path = tmp_path / "one.json"
    path.write_text(json.dumps({"name": "One", "base": "dark", "radius": 10}), encoding="utf-8")
    assert themes.load_theme_file(path).control == 8  # only "radius": controls 2 px tighter
    path.write_text(
        json.dumps({"name": "Two", "base": "dark", "radius": 10, "control_radius": 3}),
        encoding="utf-8",
    )
    assert themes.load_theme_file(path).control == 3
    for other in ("graphite", "paper"):  # the same two sizes, set in their files
        same = themes.Registry().find(other)
        assert (same.radius, same.control) == (6, 4)


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_no_corner_is_fixed_in_the_stylesheet_but_the_round_ones(theme: themes.Theme) -> None:
    """Tags, badges, the radio button and the scroll bar stay round; a tick box keeps its
    small corner. Everything else takes one of the theme's two sizes."""
    odd = themes.Theme("odd", "custom", theme.scheme, colors=theme.colors, radius=17,
                       control_radius=13)  # fmt: skip
    sheet = re.sub(r"/\*.*?\*/", "", themes.stylesheet(odd), flags=re.DOTALL)
    fixed = set()
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", sheet):
        for size in re.findall(r"border(?:-[a-z]+)*-radius: (\d+)px", body):
            if size not in ("17", "13", "0"):
                fixed.add(selector.strip())
    assert fixed == {
        "QFrame#tagChip", "QLabel#tileBadge", "QLabel#railBadge", "QLabel#tagValue",
        "QLabel#stateBadge", "QRadioButton::indicator", "QCheckBox::indicator",
        "QScrollBar::handle",
    }  # fmt: skip


def test_tables_draw_a_line_under_each_row_and_none_between_columns() -> None:
    sheets = [themes.stylesheet(themes.Registry().find(i)) for i in ("capypanel-dark", "paper")]
    for sheet in (*sheets, themes._NATIVE_QSS):  # the Windows themes' own sheet too
        assert "border-bottom: 1px solid" in _rule(sheet, "QTreeView#grid::item")
        rules = re.findall(r"([^{}]+)[{]([^}]*)[}]", sheet)
        grid = [body for selector, body in rules if "#grid" in selector]
        assert grid and not any("border-right" in body for body in grid)


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_row_lines_are_softer_than_the_table_s_frame(theme: themes.Theme) -> None:
    c, ratio = theme.colors, themes.contrast_ratio
    line = themes._card_tokens(c)["row_line"]
    frame = _rule(themes.stylesheet(theme), "QTreeView, QListView")
    assert themes._qss_color(c["border"]) in frame and line not in frame
    assert line in _rule(themes.stylesheet(theme), "QTreeView#grid::item")
    assert 1.25 <= ratio(line, c["card"]) < ratio(c["border"], c["card"]) - 0.5, theme.id


def test_column_titles_have_a_line_between_them_to_drag(qapp: QApplication) -> None:
    """The rows have no lines between columns, so the titles show where a column ends."""
    theme = themes.Registry().find("capypanel-dark")
    themes.apply(theme)
    table = QTreeWidget()
    table.setObjectName("grid")
    table.setHeaderLabels(["Name", "Address", "Status"])
    table.addTopLevelItem(QTreeWidgetItem(["DESK-01", "192.0.2.11", "Online"]))
    table.resize(480, 160)
    table.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    table.show()
    qapp.processEvents()
    header = table.header()
    titles = header.grab().toImage()
    rows = table.viewport().grab().toImage()
    table.close()
    line = QColor(theme.colors["border"])
    middle = header.height() // 2
    for column in (1, 2):
        x = header.sectionViewportPosition(column)
        assert titles.pixelColor(x, middle) == line, column
        assert rows.pixelColor(x, 8) != line, column  # the rows stay clear
    assert titles.pixelColor(0, middle) != line  # none before the first title


@pytest.mark.parametrize("theme", CUSTOM, ids=lambda t: t.id)
def test_enabled_disabled_hover_and_focus_read_apart(theme: themes.Theme) -> None:
    c, ratio = theme.colors, themes.contrast_ratio
    sheet = re.sub(r"/[*].*?[*]/", "", themes.stylesheet(theme), flags=re.DOTALL)
    # Disabled: fainter words and no fill, so it isn't mistaken for a button that works.
    assert ratio(c["text"], c["text3"]) >= 1.5, theme.id
    disabled = _rule(sheet, "QPushButton:disabled")
    assert "background: transparent" in disabled and "color:" in disabled
    # Hover: another fill than at rest.
    rest, hover = _rule(sheet, "QPushButton"), _rule(sheet, "QPushButton:hover")
    fill = re.search(r"background: ([^;]+);", rest)
    assert fill is not None and f"background: {fill[1]};" not in hover
    assert ratio(c["raised"], c["card"]) >= 1.08, theme.id
    # Focus: the accent ring, which stands out from the border it replaces, on everything Tab
    # reaches.
    assert ratio(c["accent"], c["border"]) >= 1.5, theme.id
    for selector in (
        "QPushButton:focus, QComboBox:focus",
        "QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus",
        "QRadioButton::indicator:focus, QCheckBox::indicator:focus",
    ):
        assert themes._qss_color(c["accent"]) in _rule(sheet, selector), selector


def test_headings_come_in_two_styles() -> None:
    sheets = [themes.stylesheet(themes.Registry().find(i)) for i in ("capypanel-dark", "paper")]
    for sheet in (*sheets, themes._NATIVE_QSS):  # the Windows themes' own sheet too
        rules = dict(
            re.findall(r"([^{}]+)[{]([^}]*)[}]", re.sub(r"/[*].*?[*]/", "", sheet, flags=re.DOTALL))
        )
        rules = {" ".join(k.split()): v for k, v in rules.items()}
        # A section's heading, wherever it is: Settings, Details, Groups and Tags, the Report.
        sections = next(v for k, v in rules.items() if k.startswith("QLabel#detailsSection,"))
        names = next(k for k in rules if k.startswith("QLabel#detailsSection,"))
        for name in ("#sectionTitle", "#paneTitle", '#rowName[heading="true"]'):
            assert name in names
        assert "font-weight: bold" in sections and "font-size" not in sections  # the text's size
        # A small label over a group of lines: the Commands window's groups, a menu's label.
        for small in ("QLabel#groupHeading", "QLabel#menuSection"):
            assert "font-size: 8pt" in rules[small] and "font-weight: 600" in rules[small]
