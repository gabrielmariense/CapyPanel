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
    strip.close()
