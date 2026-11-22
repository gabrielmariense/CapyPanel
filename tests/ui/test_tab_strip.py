"""The tab bar SSH and Profile cleanup share (ui/tab_strip.py)."""

from PySide6.QtWidgets import QApplication, QToolButton

from capypanel.ui.tab_strip import TabStrip
from capypanel.ui.themes import engine as themes


def test_the_line_after_the_list_s_tab_shows_only_while_another_tab_is_open(
    qapp: QApplication,
) -> None:
    strip = TabStrip("device-desktop")
    assert not strip.line.isVisibleTo(strip)  # the list alone: a line there parted nothing
    strip.add("a", "core-sw-01")
    strip.add("b", "nas-01")
    assert strip.line.isVisibleTo(strip)
    strip.remove("a")
    assert strip.line.isVisibleTo(strip)  # one still follows the list's tab
    strip.remove("b")
    assert not strip.line.isVisibleTo(strip)


def test_the_line_after_the_list_s_tab_takes_the_border_colour_as_the_toolbar_s_lines_do(
    qapp: QApplication, default_theme_after: None
) -> None:
    tokens = {"windows-dark": themes.NATIVE_TOKENS["dark"]}
    for name in ("capypanel-dark", "capypanel-light", "windows-dark"):
        theme = themes.Registry().find(name)
        colours = tokens.get(name, theme.colors)
        themes.apply(theme)
        strip = TabStrip("device-desktop")
        strip.restyle()
        strip.add("a", "core-sw-01")
        strip.show()
        QApplication.processEvents()
        colour = strip.line.grab().toImage().pixelColor(0, 8).name()
        assert colour == colours["border"] != colours["text"], name
        strip.close()


def test_the_scroll_arrows_and_the_list_of_tabs_are_buttons_as_tall_as_the_tabs(
    qapp: QApplication, default_theme_after: None
) -> None:
    theme = themes.Registry().find("capypanel-dark")
    themes.apply(theme)
    strip = TabStrip("device-desktop")
    strip.restyle()
    strip.set_height(36)
    for n in range(12):
        strip.add(str(n), f"DESK-{n:02}")
    strip.resize(420, 36)
    strip.show()
    QApplication.processEvents()
    arrows = [b for b in strip.bar.findChildren(QToolButton) if b.objectName().startswith("Scroll")]
    assert len(arrows) == 2 and all(a.isVisible() for a in arrows)
    face = theme.colors["raised"]  # the toolbar buttons' face, never the window behind
    for button in (*arrows, strip.more):
        assert (button.width(), button.height()) == (28, 36)
        assert button.grab().toImage().pixelColor(4, 18).name() == face != theme.colors["bg"]


def test_no_tab_runs_under_the_scroll_arrows_nor_is_half_drawn_before_them(
    qapp: QApplication, default_theme_after: None
) -> None:
    theme = themes.Registry().find("capypanel-dark")
    themes.apply(theme)
    strip = TabStrip("device-desktop")
    strip.restyle()
    strip.set_height(36)
    for n in range(12):
        strip.add(str(n), f"DESK-{n:02}")
    strip.resize(420, 36)
    strip.show()
    QApplication.processEvents()
    bar = strip.bar
    edge = min(b.x() for b in bar.findChildren(QToolButton) if b.objectName().startswith("Scroll"))
    picture = bar.grab().toImage()
    hidden = [
        i for i in range(bar.count()) if bar.tabRect(i).left() < edge <= bar.tabRect(i).right()
    ]
    assert hidden  # the case under test: a tab that would run under the arrows
    start = bar.tabRect(hidden[0]).left()
    for x in range(start, edge):  # the bar's own colour, the tab and its × hidden alike
        assert picture.pixelColor(x, 18).name() == theme.colors["bg"], x
    shown = [bar.tabRect(i) for i in range(bar.count()) if bar.tabRect(i).right() < start]
    assert shown and all(tab.right() < edge for tab in shown)  # whole, or short of CUT px
    strip.close()
