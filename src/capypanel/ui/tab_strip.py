"""A tool's tab bar: the pinned list, then a tab per thing opened, never reordered."""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QStyle,
    QStyleOptionTab,
    QTabBar,
    QToolButton,
    QWidget,
)

from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes import engine as themes

PINNED = ""  # the pinned tab's key; every other tab has a key of its own
GAP = 14  # px between the pinned tab and the others
ARROW = 18  # px: the chevrons of the scroll arrows and ▾, buttons the theme draws (toolTabs)
CUT = 4  # px of the bar's own colour between the tabs and a scroll arrow


class _Bar(QTabBar):
    """A tab bar that can show none of its tabs as the current one: the pinned tab and the
    others are two bars, and only one of them holds the tab in front."""

    middle_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("toolTabs")
        self.active = True
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setUsesScrollButtons(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._height = 0  # every tab's, once the strip gives one; until then the style's
        self._hidden_from = -1  # x from which tabs are hidden before the arrows; -1: none

    def set_tab_height(self, height: int) -> None:
        self._height = height
        self.setElideMode(self.elideMode())  # Qt lays the tabs out again; the mode is ours
        self.updateGeometry()  # hidden, Qt only marks them: the strip asks again on its own

    def tabSizeHint(self, index: int) -> QSize:  # noqa: N802 -- Qt's name
        size = super().tabSizeHint(index)
        if self._height:
            size.setHeight(self._height)
        return size

    def minimumTabSizeHint(self, index: int) -> QSize:  # noqa: N802 -- Qt's name
        size = super().minimumTabSizeHint(index)
        if self._height:
            size.setHeight(self._height)
        return size

    def set_active(self, active: bool) -> None:
        self.active = active
        self.update()

    def _scrollers(self) -> list[QToolButton]:
        """Qt's own two buttons, left then right."""
        names = ("ScrollLeftButton", "ScrollRightButton")
        return [b for name in names if (b := self.findChild(QToolButton, name)) is not None]

    def tabLayoutChange(self) -> None:
        """Qt gives its two buttons their arrows back each time it lays the tabs out, and a
        button with an arrow draws no icon."""
        super().tabLayoutChange()
        for button in self._scrollers():
            if button.arrowType() != Qt.ArrowType.NoArrow:
                button.setArrowType(Qt.ArrowType.NoArrow)

    def restyle(self) -> None:
        """The scroll arrows' chevrons; the end the bar is at gets a faded one."""
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        window = self.palette().color(QPalette.ColorRole.Window)
        muted = QColor(
            round(color.red() * 0.4 + window.red() * 0.6),
            round(color.green() * 0.4 + window.green() * 0.6),
            round(color.blue() * 0.4 + window.blue() * 0.6),
        )
        names = ("chevron-left", "chevron-right")
        for button, name in zip(self._scrollers(), names, strict=False):
            icon = tabler_icon(name, color, ARROW)
            icon.addPixmap(
                tabler_icon(name, muted, ARROW).pixmap(ARROW, ARROW), QIcon.Mode.Disabled
            )
            button.setArrowType(Qt.ArrowType.NoArrow)
            button.setIcon(icon)
            button.setIconSize(QSize(ARROW, ARROW))

    def paintEvent(self, event: QPaintEvent) -> None:
        """The tabs stop CUT px before a scroll arrow; a tab that would reach under one isn't
        shown, so no tab is ever half drawn there."""
        super().paintEvent(event)
        arrows = [b for b in self._scrollers() if b.isVisible()]
        if not arrows or self.isRightToLeft():
            self._hidden_from = -1
            return
        painter = QPainter(self)
        back = QColor(themes.background())
        ends = [a.x() for a in arrows if a.x() > self.width() // 2]
        self._hidden_from = -1
        if ends:
            edge = min(ends)
            start = edge - CUT
            for index in range(self.count()):
                tab = self.tabRect(index)
                if tab.left() < start <= tab.right() and tab.right() >= edge:
                    start = tab.left()
            self._hidden_from = start
            painter.fillRect(start, 0, edge - start, self.height(), back)
        for arrow in arrows:
            if arrow.x() <= self.width() // 2:  # Windows' style puts ‹ at the left end
                painter.fillRect(arrow.x() + arrow.width(), 0, CUT, self.height(), back)
        painter.end()

    def hides(self, rect: QRect) -> bool:
        """Whether `rect` is where tabs are hidden before the arrows."""
        return self._hidden_from >= 0 and rect.left() >= self._hidden_from

    def initStyleOption(self, option: QStyleOptionTab, index: int) -> None:
        super().initStyleOption(option, index)
        if not self.active:
            option.state &= ~QStyle.StateFlag.State_Selected

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()  # Qt picks a tab on any press: a middle-click went there, then closed
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self.middle_clicked.emit(index)
                return
        super().mouseReleaseEvent(event)


class _Close(QToolButton):
    """A tab's ×, neither drawn nor clicked while its tab is hidden before the arrows."""

    def _hidden(self) -> bool:
        bar = self.parentWidget()
        return isinstance(bar, _Bar) and bar.hides(self.geometry())

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._hidden():
            super().paintEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._hidden():
            event.ignore()  # the bar takes it, as a click on the hidden tab
            return
        super().mousePressEvent(event)


class TabStrip(QWidget):
    """Which tab is in front is a key: PINNED, or another tab's key. `pinned_icon` is the
    pinned tab's Tabler icon."""

    picked = Signal(str)  # a tab was clicked: its key
    close_requested = Signal(str)  # its ×, or a middle-click
    menu_requested = Signal(str, QPoint)  # a right-click on a tab: its key, where (global)

    def __init__(self, pinned_icon: str) -> None:
        super().__init__()
        self._current = PINNED
        self._pinned_icon = pinned_icon
        self.pinned = _Bar()
        self.pinned.addTab("")
        self.pinned.setUsesScrollButtons(False)
        self.line = QFrame()
        self.line.setFrameShape(QFrame.Shape.VLine)
        self.line.setFixedHeight(16)
        self.line.hide()  # with the list alone it parted nothing, and looked like a text cursor
        gap = QWidget()
        gap.setFixedWidth(GAP)
        inside = QHBoxLayout(gap)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addWidget(self.line, 0, Qt.AlignmentFlag.AlignCenter)
        self.bar = _Bar()
        self.more = QToolButton()
        self.more.setObjectName("tabsMenu")
        self.more.setFixedWidth(28)  # as each scroll arrow
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setMenu(QMenu(self.more))
        self.more.menu().aboutToShow.connect(self._fill_more)
        self._more_items: list[tuple[str, str, QIcon]] = []  # every tab: key, text, mark
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.pinned, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(gap)
        row.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignBottom)
        row.addSpacing(4)
        row.addWidget(self.more, 0, Qt.AlignmentFlag.AlignBottom)
        self.pinned.tabBarClicked.connect(lambda _i: self.picked.emit(PINNED))
        self.bar.tabBarClicked.connect(self._clicked)
        self.bar.middle_clicked.connect(lambda i: self.close_requested.emit(self.key_at(i)))
        self.bar.customContextMenuRequested.connect(self._menu)
        self.restyle()

    def set_height(self, height: int) -> None:
        """As tall as `height` (the list dropdown's, plus the gap under it), its tabs filling it,
        so the panels under the tabs start where the Groups panel does."""
        for bar in (self.pinned, self.bar):
            bar.set_tab_height(height)
        self.more.setFixedHeight(height)
        self.setFixedHeight(height)

    def restyle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.more.setIcon(tabler_icon("chevron-down", color, ARROW))
        self.more.setIconSize(QSize(ARROW, ARROW))
        self.bar.restyle()
        self.pinned.setTabIcon(0, tabler_icon(self._pinned_icon, color))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for index in range(self.bar.count()):
            button = self.bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(tabler_icon("x", muted, 14))

    def set_pinned_text(self, text: str, tip: str = "") -> None:
        self.pinned.setTabText(0, text)
        self.pinned.setTabToolTip(0, tip)

    def tab_keys(self) -> list[str]:
        """The tabs after the pinned one, left to right."""
        return [self.key_at(i) for i in range(self.bar.count())]

    def key_at(self, index: int) -> str:
        data = self.bar.tabData(index)
        return data if isinstance(data, str) else ""

    def index_of(self, key: str) -> int:
        return next((i for i in range(self.bar.count()) if self.key_at(i) == key), -1)

    def add(self, key: str, text: str) -> None:
        """A tab at the right end."""
        self.bar.blockSignals(True)
        index = self.bar.addTab(text)
        self.bar.setTabData(index, key)
        close = _Close()  # a plain × in the theme's colour: Qt's own is a grey block here
        close.setAutoRaise(True)
        close.setFixedSize(18, 18)
        close.setStyleSheet("QToolButton { padding: 0px; }")  # the theme's padding hides it
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setIcon(
            tabler_icon("x", self.palette().color(QPalette.ColorRole.PlaceholderText), 14)
        )
        close.clicked.connect(lambda _c=False, k=key: self.close_requested.emit(k))
        self.bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        if self._current == PINNED:  # adding a first tab makes it current in Qt's eyes
            self.bar.set_active(False)
        self.bar.blockSignals(False)
        self.line.show()

    def remove(self, key: str) -> None:
        index = self.index_of(key)
        if index >= 0:
            self.bar.blockSignals(True)
            self.bar.removeTab(index)
            self.bar.blockSignals(False)
            self.line.setVisible(self.bar.count() > 0)

    def show_tab(self, key: str, text: str, icon: QIcon, tip: str, closable: bool) -> None:
        """A tab as it stands: its name, its mark and the mark's words, and its × only while it
        may close."""
        index = self.index_of(key)
        if index < 0:
            return
        self.bar.setTabText(index, text)
        self.bar.setTabIcon(index, icon)
        self.bar.setTabToolTip(index, tip)
        button = self.bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
        if button is not None:
            button.setVisible(closable)

    def current(self) -> str:
        return self._current

    def set_current(self, key: str) -> None:
        self._current = key if key == PINNED or self.index_of(key) >= 0 else PINNED
        self.pinned.set_active(self._current == PINNED)
        self.bar.set_active(self._current != PINNED)
        if self._current != PINNED:
            self.bar.blockSignals(True)
            self.bar.setCurrentIndex(self.index_of(self._current))
            self.bar.blockSignals(False)

    def set_more(self, items: list[tuple[str, str, QIcon]]) -> None:
        """What ▾ lists: every tab's key, its words ("LAB-01 · deleting 2 of 3") and mark."""
        self._more_items = items

    def _clicked(self, index: int) -> None:
        if index >= 0:
            self.picked.emit(self.key_at(index))

    def _menu(self, point: QPoint) -> None:
        index = self.bar.tabAt(point)
        if index >= 0:
            self.menu_requested.emit(self.key_at(index), self.bar.mapToGlobal(point))

    def _fill_more(self) -> None:
        menu = self.more.menu()
        menu.clear()
        for key, text, icon in self._more_items:
            action = menu.addAction(icon, text.replace("&", "&&"))
            action.setCheckable(True)
            action.setChecked(key == self._current)
            action.triggered.connect(lambda _c=False, k=key: self.picked.emit(k))


def mark_icon(name: str, color: str) -> QIcon:
    """A tab's mark; none when `name` is "" (a host simply scanned)."""
    return tabler_icon(name, QColor(color), 16) if name else QIcon()
