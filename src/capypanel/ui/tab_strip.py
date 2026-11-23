from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
)
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

PINNED = ""
GAP = 14
ARROW = 18
CUT = 4
STEPS = {Qt.Key.Key_Left: -1, Qt.Key.Key_Right: 1}
ENDS = {Qt.Key.Key_Home: False, Qt.Key.Key_End: True}


class _Bar(QTabBar):
    """Qt's bar always shows a current tab; this one can show none: the pinned tab is a bar of
    its own."""

    middle_clicked = Signal(int)
    stepped = Signal(int)
    to_end = Signal(bool)

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
        for arrow in self._scrollers():
            arrow.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Qt makes them Tab stops: arrows suffice
        self._height = 0
        self._hidden_from = -1  # x from which tabs are hidden before the arrows; -1: none

    def set_tab_height(self, height: int) -> None:
        self._height = height
        self.setElideMode(self.elideMode())  # makes Qt lay the tabs out again
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
        names = ("ScrollLeftButton", "ScrollRightButton")
        return [b for name in names if (b := self.findChild(QToolButton, name)) is not None]

    def tabLayoutChange(self) -> None:
        """Qt gives its scroll buttons their arrows back on each layout, and a button with an arrow
        draws no icon."""
        super().tabLayoutChange()
        for button in self._scrollers():
            if button.arrowType() != Qt.ArrowType.NoArrow:
                button.setArrowType(Qt.ArrowType.NoArrow)

    def restyle(self) -> None:
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
        return self._hidden_from >= 0 and rect.left() >= self._hidden_from

    def initStyleOption(self, option: QStyleOptionTab, index: int) -> None:
        super().initStyleOption(option, index)
        if not self.active:
            option.state &= ~QStyle.StateFlag.State_Selected

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()  # Qt makes any pressed tab current, a middle-clicked one too
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.tabAt(event.position().toPoint())
            if index >= 0:
                self.middle_clicked.emit(index)
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = Qt.Key(event.key())
        if event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier:
            super().keyPressEvent(event)
        elif key in STEPS:
            self.stepped.emit(STEPS[key])
        elif key in ENDS:
            self.to_end.emit(ENDS[key])
        else:
            super().keyPressEvent(event)

    def inputMethodQuery(self, query: Qt.InputMethodQuery) -> object:
        if query == Qt.InputMethodQuery.ImCursorRectangle and self.currentIndex() >= 0:
            return self.tabRect(self.currentIndex())
        return super().inputMethodQuery(query)


class _Close(QToolButton):
    def _hidden(self) -> bool:
        bar = self.parentWidget()
        return isinstance(bar, _Bar) and bar.hides(self.geometry())

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._hidden():
            super().paintEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._hidden():
            event.ignore()
            return
        super().mousePressEvent(event)


class TabStrip(QWidget):
    picked = Signal(str)
    close_requested = Signal(str)
    menu_requested = Signal(str, QPoint)

    def __init__(self, pinned_icon: str) -> None:
        super().__init__()
        self._current = PINNED
        self._pinned_icon = pinned_icon
        self.pinned = _Bar()
        self.pinned.addTab("")
        self.pinned.setUsesScrollButtons(False)
        self.line = QFrame()
        self.line.setObjectName("toolDivider")
        self.line.setFixedSize(1, 16)
        self.line.hide()
        gap = QWidget()
        gap.setFixedWidth(GAP)
        inside = QHBoxLayout(gap)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addWidget(self.line, 0, Qt.AlignmentFlag.AlignCenter)
        self.bar = _Bar()
        self.more = QToolButton()
        self.more.setObjectName("tabsMenu")
        self.more.setFixedWidth(28)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setMenu(QMenu(self.more))
        self.more.menu().aboutToShow.connect(self._fill_more)
        self._more_items: list[tuple[str, str, QIcon]] = []
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
        for bar in (self.pinned, self.bar):
            bar.stepped.connect(self._step)
            bar.to_end.connect(self._to_end)
        self.restyle()

    def set_height(self, height: int) -> None:
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
        return [self.key_at(i) for i in range(self.bar.count())]

    def key_at(self, index: int) -> str:
        data = self.bar.tabData(index)
        return data if isinstance(data, str) else ""

    def index_of(self, key: str) -> int:
        return next((i for i in range(self.bar.count()) if self.key_at(i) == key), -1)

    def add(self, key: str, text: str) -> None:
        self.bar.blockSignals(True)
        index = self.bar.addTab(text)
        self.bar.setTabData(index, key)
        close = _Close()  # Qt's own × is a grey block here
        close.setAutoRaise(True)
        close.setFixedSize(18, 18)
        close.setStyleSheet("QToolButton { padding: 0px; }")
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
        self._stops()

    def remove(self, key: str) -> None:
        index = self.index_of(key)
        if index >= 0:
            self.bar.blockSignals(True)
            self.bar.removeTab(index)
            self.bar.blockSignals(False)
            self.line.setVisible(self.bar.count() > 0)
            self._stops()

    def show_tab(self, key: str, text: str, icon: QIcon, tip: str, closable: bool) -> None:
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
        self._stops()

    def _holder(self) -> _Bar:
        return self.pinned if self._current == PINNED else self.bar

    def _stops(self) -> None:
        holder = self._holder() if self.bar.count() else None
        for bar in (self.pinned, self.bar):
            policy = Qt.FocusPolicy.TabFocus if bar is holder else Qt.FocusPolicy.NoFocus
            bar.setFocusPolicy(policy)

    def _to_end(self, last: bool) -> None:
        self._step(self.bar.count() + 1 if last else -self.bar.count() - 1)

    def _step(self, by: int) -> None:
        keys = [PINNED, *self.tab_keys()]
        index = keys.index(self._current) if self._current in keys else 0
        to = min(max(index + by, 0), len(keys) - 1)
        if to != index:
            self.picked.emit(keys[to])
        self._holder().setFocus(Qt.FocusReason.OtherFocusReason)

    def set_more(self, items: list[tuple[str, str, QIcon]]) -> None:
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
    return tabler_icon(name, QColor(color), 16) if name else QIcon()
