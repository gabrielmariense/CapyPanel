"""The User profiles tool's tab bar: the pinned Hosts tab first, then a gap with a short line,
then a tab per host, which scroll when they don't fit while the Hosts tab stays. A ▾ at the end
lists every tab. Tabs never reorder themselves: a new one opens at the right end."""

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QMouseEvent, QPalette
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

HOSTS = ""  # the Hosts tab's key; a host's tab has the host's key
GAP = 14  # px between the Hosts tab and the hosts' tabs


class _Bar(QTabBar):
    """A tab bar that can show none of its tabs as the current one: the Hosts tab and the hosts'
    tabs are two bars, and only one of them holds the tab in front."""

    middle_clicked = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.active = True
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setUsesScrollButtons(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

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
        """The two arrows that scroll the tabs when they don't fit. Qt's own are tool buttons,
        and the theme's padding for tool buttons left them see-through with no arrow: the
        last tab just looked cut. They get a chevron and the window's own background."""
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        window = self.palette().color(QPalette.ColorRole.Window)
        # The end the bar is already at: its arrow faded towards the background, drawn so by
        # us (the style's own greying of an icon barely showed). Mixed from the two colours,
        # so it's fainter in every theme.
        muted = QColor(
            round(color.red() * 0.4 + window.red() * 0.6),
            round(color.green() * 0.4 + window.green() * 0.6),
            round(color.blue() * 0.4 + window.blue() * 0.6),
        )
        back = window.name()
        names = ("chevron-left", "chevron-right")
        for button, name in zip(self._scrollers(), names, strict=False):
            icon = tabler_icon(name, color, 16)
            icon.addPixmap(tabler_icon(name, muted, 16).pixmap(16, 16), QIcon.Mode.Disabled)
            button.setArrowType(Qt.ArrowType.NoArrow)
            button.setIcon(icon)
            button.setIconSize(QSize(16, 16))
            button.setStyleSheet(
                f"QToolButton {{ padding: 0px; border: none; border-radius: 0px;"
                f" background: {back}; }}"
            )

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


class TabStrip(QWidget):
    """Which tab is in front is a key: HOSTS, or a host's key."""

    picked = Signal(str)  # a tab was clicked: its key
    close_requested = Signal(str)  # its ×, or a middle-click
    menu_requested = Signal(str, QPoint)  # a right-click on a tab: its key, where (global)

    def __init__(self) -> None:
        super().__init__()
        self._current = HOSTS
        self.pinned = _Bar()
        self.pinned.addTab("")
        self.pinned.setUsesScrollButtons(False)
        self.line = QFrame()
        self.line.setFrameShape(QFrame.Shape.VLine)
        self.line.setFixedHeight(16)
        gap = QWidget()
        gap.setFixedWidth(GAP)
        inside = QHBoxLayout(gap)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addWidget(self.line, 0, Qt.AlignmentFlag.AlignCenter)
        self.bar = _Bar()
        self.more = QToolButton()
        self.more.setAutoRaise(True)
        self.more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.more.setMenu(QMenu(self.more))
        self.more.menu().aboutToShow.connect(self._fill_more)
        self._more_items: list[tuple[str, str, QIcon]] = []  # every tab: key, text, mark
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.pinned, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(gap)
        row.addWidget(self.bar, 1, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.more)
        self.pinned.tabBarClicked.connect(lambda _i: self.picked.emit(HOSTS))
        self.bar.tabBarClicked.connect(self._clicked)
        self.bar.middle_clicked.connect(lambda i: self.close_requested.emit(self.key_at(i)))
        self.bar.customContextMenuRequested.connect(self._menu)
        self.restyle()

    def restyle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.more.setIcon(tabler_icon("chevron-down", color))
        self.bar.restyle()
        self.pinned.setTabIcon(0, tabler_icon("device-desktop", color))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for index in range(self.bar.count()):
            button = self.bar.tabButton(index, QTabBar.ButtonPosition.RightSide)
            if isinstance(button, QToolButton):
                button.setIcon(tabler_icon("x", muted, 14))

    # ---- the tabs ----

    def set_hosts_text(self, text: str, tip: str = "") -> None:
        self.pinned.setTabText(0, text)
        self.pinned.setTabToolTip(0, tip)

    def host_keys(self) -> list[str]:
        """The hosts' tabs, left to right."""
        return [self.key_at(i) for i in range(self.bar.count())]

    def key_at(self, index: int) -> str:
        data = self.bar.tabData(index)
        return data if isinstance(data, str) else ""

    def index_of(self, key: str) -> int:
        return next((i for i in range(self.bar.count()) if self.key_at(i) == key), -1)

    def add(self, key: str, text: str) -> None:
        """A host's tab at the right end."""
        self.bar.blockSignals(True)
        index = self.bar.addTab(text)
        self.bar.setTabData(index, key)
        close = QToolButton()  # a plain × in the theme's colour: Qt's own is a grey block here
        close.setAutoRaise(True)
        close.setFixedSize(18, 18)
        close.setStyleSheet("QToolButton { padding: 0px; }")  # the theme's padding hides it
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.setIcon(
            tabler_icon("x", self.palette().color(QPalette.ColorRole.PlaceholderText), 14)
        )
        close.clicked.connect(lambda _c=False, k=key: self.close_requested.emit(k))
        self.bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        if self._current == HOSTS:  # adding a first tab makes it current in Qt's eyes
            self.bar.set_active(False)
        self.bar.blockSignals(False)

    def remove(self, key: str) -> None:
        index = self.index_of(key)
        if index >= 0:
            self.bar.blockSignals(True)
            self.bar.removeTab(index)
            self.bar.blockSignals(False)

    def show_tab(self, key: str, text: str, icon: QIcon, tip: str, closable: bool) -> None:
        """A host's tab as it stands: its name, its mark and the mark's words, and its × only
        while it may close."""
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
        self._current = key if key == HOSTS or self.index_of(key) >= 0 else HOSTS
        self.pinned.set_active(self._current == HOSTS)
        self.bar.set_active(self._current != HOSTS)
        if self._current != HOSTS:
            self.bar.blockSignals(True)
            self.bar.setCurrentIndex(self.index_of(self._current))
            self.bar.blockSignals(False)

    def set_more(self, items: list[tuple[str, str, QIcon]]) -> None:
        """What ▾ lists: every tab's key, its words ("LAB-01 · deleting 2 of 3") and mark."""
        self._more_items = items

    # ---- clicks ----

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
    """A tab's mark; none for a host simply scanned."""
    return tabler_icon(name, QColor(color), 16) if name else QIcon()
