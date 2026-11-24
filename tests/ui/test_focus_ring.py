import re
from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QCheckBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.ui import focus_ring, help_links
from capypanel.ui.focus_ring import OUT, Ring
from capypanel.ui.keyboard import Keyboard
from capypanel.ui.themes import engine as themes

K = Qt.Key


@pytest.fixture
def keys(qapp: QApplication) -> Iterator[Keyboard]:
    keys = Keyboard()
    qapp.installEventFilter(keys)
    yield keys
    qapp.removeEventFilter(keys)


def _shown(widget: QWidget) -> None:
    widget.show()
    widget.activateWindow()
    QApplication.processEvents()
    assert QApplication.activeWindow() is widget


def _press(key: K) -> QWidget | None:
    focus = QApplication.focusWidget()
    assert focus is not None
    QTest.keyClick(focus, key)
    for _turn in range(2):  # a label marks its link a turn after the focus comes
        QApplication.processEvents()
    return QApplication.focusWidget()


def _ring(keys: Keyboard) -> Ring | None:
    ring = keys.ring.ring
    return ring if ring is not None and ring.isVisible() else None


def _around(ring: Ring) -> list[QRect]:
    at = QPointF(ring.pos())
    return [rect.adjusted(OUT, OUT, -OUT, -OUT).translated(at).toRect() for rect, _r in ring.paths]


def _window(*widgets: QWidget) -> QWidget:
    window = QWidget()
    column = QVBoxLayout(window)
    for widget in widgets:
        column.addWidget(widget)
    window.resize(320, 60 * len(widgets))
    _shown(window)
    return window


def test_tab_rings_a_button_and_a_click_takes_the_ring_away(keys: Keyboard) -> None:
    field, first, second = QLineEdit(), QPushButton("First"), QPushButton("Second")
    window = _window(field, first, second)
    field.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is first
    ring = _ring(keys)
    assert ring is not None and ring.parentWidget() is window
    assert _around(ring) == [first.geometry()]
    assert not window.testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange)
    QTest.mouseClick(second, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert QApplication.focusWidget() is second and _ring(keys) is None
    assert _press(K.Key_Backtab) is first and _ring(keys) is not None
    window.close()


def test_a_field_keeps_its_ring_however_it_got_the_keyboard(keys: Keyboard) -> None:
    first, field = QPushButton("First"), QLineEdit()
    window = _window(first, field)
    first.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert _ring(keys) is None
    QTest.mouseClick(field, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    ring = _ring(keys)
    assert QApplication.focusWidget() is field and ring is not None
    assert _around(ring) == [field.geometry()]
    window.close()


def _office() -> QTreeWidget:
    table = QTreeWidget()
    table.setHeaderLabels(["Name", "Address", "Tags"])
    for n in range(5):
        table.addTopLevelItem(QTreeWidgetItem([f"DESK-0{n}", f"192.0.2.{n}", ""]))
    return table


def _item(table: QTreeWidget, index: int) -> QTreeWidgetItem:
    item = table.topLevelItem(index)
    assert item is not None
    return item


def test_a_table_rings_its_current_row_across_its_columns(keys: Keyboard) -> None:
    before, table = QLineEdit(), _office()
    window = _window(before, table)
    window.resize(420, 320)
    QApplication.processEvents()
    table.setCurrentItem(_item(table, 1))
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is table
    ring = _ring(keys)
    assert ring is not None and ring.parentWidget() is table
    assert ring.geometry() == table.viewport().geometry()
    for index in (1, 2):
        row = table.visualItemRect(_item(table, index))
        ((rect, radius),) = focus_ring.row_paths(table)
        whole = QRect(0, row.top(), table.header().length(), row.height())
        assert rect.adjusted(-OUT, -OUT, OUT, OUT).toRect() == whole and radius == 0
        _press(K.Key_Down)
    assert _ring(keys) is ring
    window.close()


def test_a_row_wider_than_its_table_closes_its_ring_at_the_table_s_edge(keys: Keyboard) -> None:
    before, table = QLineEdit(), _office()
    for column in range(3):
        table.setColumnWidth(column, 300)
    window = _window(before, table)
    table.setCurrentItem(_item(table, 1))
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is table
    viewport, bar = table.viewport(), table.horizontalScrollBar()
    assert table.header().length() > viewport.width()
    row = table.visualItemRect(_item(table, 1))
    for value in (0, bar.maximum() // 2, bar.maximum()):
        bar.setValue(value)
        QApplication.processEvents()
        ((rect, _radius),) = focus_ring.row_paths(table)
        seen = QRect(0, row.top(), viewport.width(), row.height())
        assert rect.adjusted(-OUT, -OUT, OUT, OUT).toRect() == seen
    window.close()


class _Pane(QAbstractScrollArea):
    def __init__(self, typed: bool) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, typed)


def test_a_pane_s_ring_goes_inside_it_round_what_it_shows(keys: Keyboard) -> None:
    before, pane = QLineEdit(), _Pane(typed=False)
    window = _window(before, pane)
    pane.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    assert QApplication.focusWidget() is pane and _ring(keys) is None
    before.setFocus(Qt.FocusReason.OtherFocusReason)
    assert _press(K.Key_Tab) is pane
    ring = _ring(keys)
    viewport = pane.viewport()
    assert ring is not None and ring.parentWidget() is pane
    assert ring.geometry() == viewport.geometry()
    assert ring.paths == [(QRectF(viewport.rect()).adjusted(OUT, OUT, -OUT, -OUT), 0.0)]
    window.close()


def test_a_pane_you_type_in_keeps_its_ring_however_it_got_the_keyboard(keys: Keyboard) -> None:
    first, pane = QPushButton("First"), _Pane(typed=True)
    window = _window(first, pane)
    pane.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    ring = _ring(keys)
    assert QApplication.focusWidget() is pane and ring is not None
    assert ring.parentWidget() is pane and ring.geometry() == pane.viewport().geometry()
    window.close()


@pytest.mark.parametrize("theme", ["none", "capypanel-dark", "paper", "windows-light"])
def test_a_link_s_ring_takes_the_place_of_qt_s_dotted_box(
    keys: Keyboard, default_theme_after: None, theme: str
) -> None:
    if theme != "none":
        themes.apply(themes.Registry().find(theme))
    before, after = QLineEdit(), QLineEdit()
    label = QLabel('Read <a href="one">the guide</a> now')
    label.setObjectName("hint")
    label.setTextInteractionFlags(help_links.LINK_KEYS)
    window = _window(before, label, after)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is label and label.selectedText() == "the guide"
    ring = _ring(keys)
    assert ring is not None
    (box,) = _around(ring)
    assert box.width() < label.width() // 2
    inside = box.adjusted(-1, -1, 1, 1)
    marked = window.grab(inside).toImage()
    after.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert not label.hasSelectedText()
    assert window.grab(inside).toImage() == marked
    window.close()


def test_a_tick_box_s_ring_goes_round_its_box_not_its_words(keys: Keyboard) -> None:
    before, box = QLineEdit(), QCheckBox("Remember the password on this PC")
    window = _window(before, box)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is box
    ring = _ring(keys)
    assert ring is not None
    option = QStyleOptionButton()
    option.initFrom(box)
    tick = box.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, box)
    assert _around(ring) == [tick.translated(box.pos())]
    assert tick.width() < box.width() // 2
    window.close()


def test_a_row_of_tabs_rings_the_tab_the_arrows_reach(keys: Keyboard) -> None:
    before, bar = QLineEdit(), QTabBar()
    for name in ("core-sw-01", "nas-01", "web-01"):
        bar.addTab(name)
    window = _window(before, bar)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is bar
    for index in (0, 1):
        ring = _ring(keys)
        assert ring is not None and bar.currentIndex() == index
        assert _around(ring) == [bar.tabRect(index).translated(bar.pos())]
        _press(K.Key_Right)
    window.close()


def test_the_ring_is_the_accent_where_it_reads_and_the_text_colour_where_it_doesnt(
    keys: Keyboard, default_theme_after: None
) -> None:
    light = themes.Registry().find("capypanel-light")
    colors = light.colors
    for accent, drawn in ((colors["accent"], colors["accent"]), (colors["bg"], colors["text"])):
        themes.apply(replace(light, colors={**colors, "accent": accent}))
        before, button = QLineEdit(), QPushButton("Refresh")
        window = _window(before, button)
        before.setFocus(Qt.FocusReason.TabFocusReason)
        assert _press(K.Key_Tab) is button
        ring = _ring(keys)
        assert ring is not None and ring.ink.name() == drawn
        window.close()


def test_a_picked_row_takes_the_text_colour_where_the_accent_doesnt_read_on_it(
    keys: Keyboard, default_theme_after: None
) -> None:
    dark = themes.Registry().find("capypanel-dark")
    themes.apply(dark)
    colors = dark.colors
    assert themes.contrast_ratio(colors["accent"], colors["sel_solid"]) < focus_ring.CONTRAST
    before, table = QLineEdit(), _office()
    window = _window(before, table)
    table.setCurrentItem(_item(table, 0))
    before.setFocus(Qt.FocusReason.TabFocusReason)
    assert _press(K.Key_Tab) is table
    ring = _ring(keys)
    assert ring is not None and ring.ink.name() == colors["text"]
    table.clearSelection()
    QApplication.processEvents()
    assert ring.ink.name() == colors["accent"]
    window.close()


@pytest.mark.parametrize("sheet", ["capypanel-dark", "paper", "native"])
def test_no_theme_draws_a_focus_mark_of_its_own(sheet: str) -> None:
    theme = themes.Registry().find(sheet)
    text = themes._NATIVE_QSS if sheet == "native" else themes.stylesheet(theme)
    rules = re.findall(r"([^{}]+)[{]", re.sub(r"/[*].*?[*]/", "", text, flags=re.DOTALL))
    focused = [r.strip() for r in rules if ":focus" in r and "refused" not in r]
    assert focused == []
    assert "focused" not in text
