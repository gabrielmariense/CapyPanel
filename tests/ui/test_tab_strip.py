"""The tab bar SSH and Profile cleanup share (ui/tab_strip.py)."""

from PySide6.QtWidgets import QApplication

from capypanel.ui.tab_strip import TabStrip


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
