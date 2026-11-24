from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent, QFocusEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QApplication,
    QLabel,
    QMenu,
    QMenuBar,
    QWidget,
)

from capypanel.ui.focus_ring import FocusRing

PLAIN = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
CTRL = Qt.KeyboardModifier.ControlModifier
ALT = Qt.KeyboardModifier.AltModifier
WATCHED = frozenset({
    QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.KeyPress, QEvent.Type.KeyRelease,
    QEvent.Type.ContextMenu, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
})  # fmt: skip


def is_menu_key(event: QKeyEvent) -> bool:
    mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    if event.key() == Qt.Key.Key_Menu:
        return mods in (PLAIN, SHIFT)
    return event.key() == Qt.Key.Key_F10 and mods == SHIFT


def menu_point(widget: QWidget) -> QPoint:
    """An item view's point is in its viewport, as a right-click's is: Qt's own for the keyboard
    counts the header in, a row too low."""
    if isinstance(widget, QAbstractItemView):
        current = widget.currentIndex()
        if not current.isValid():
            return QPoint(0, 0)
        widget.scrollTo(current)
        chosen = widget.selectionModel()
        if chosen is not None and not chosen.isSelected(current):
            widget.setCurrentIndex(current)
        return widget.visualRect(current).center()
    rect = widget.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)
    if isinstance(rect, QRectF):
        rect = rect.toRect()
    if isinstance(rect, QRect) and rect.isValid():
        return rect.center()
    return widget.rect().center()


class Keyboard(QObject):
    """Qt 6 takes Windows' menu key as a plain key and opens nothing, while Windows itself sends
    Shift+F10's menu. Both end here, so both open the same menu at the same place."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sending = False
        self.ring = FocusRing(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind not in WATCHED or self._sending or not isinstance(watched, QWidget):
            return False
        self.ring.note(watched, event)
        if kind == QEvent.Type.FocusIn and isinstance(watched, QLabel):
            _to_a_link(watched, event)
            return False
        if kind not in (QEvent.Type.KeyPress, QEvent.Type.ContextMenu) or _in_menu(watched):
            return False
        if kind == QEvent.Type.KeyPress and isinstance(event, QKeyEvent) and is_menu_key(event):
            self.open_menu(watched, event.modifiers())
            return True
        if (
            kind == QEvent.Type.ContextMenu
            and isinstance(event, QContextMenuEvent)
            and event.reason() == QContextMenuEvent.Reason.Keyboard
        ):
            self.open_menu(watched, event.modifiers())
            return True
        return False

    def open_menu(self, widget: QWidget, mods: Qt.KeyboardModifier = PLAIN) -> None:
        point = menu_point(widget)
        anchor = widget.viewport() if isinstance(widget, QAbstractItemView) else widget
        menu = QContextMenuEvent(
            QContextMenuEvent.Reason.Keyboard, point, anchor.mapToGlobal(point), mods
        )
        self._sending = True
        try:
            QApplication.sendEvent(widget, menu)
        finally:
            self._sending = False


def _in_menu(widget: QWidget) -> bool:
    return isinstance(widget, QMenu | QMenuBar) or QApplication.activePopupWidget() is not None


def _to_a_link(label: QLabel, event: QEvent) -> None:
    """Qt's Tab stops on a label with links first, its first link only at the next Tab; and its
    text part is made as it takes the focus, so the step waits for that."""
    if not isinstance(event, QFocusEvent) or "href" not in label.text():
        return
    if not label.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByKeyboard:
        return
    reason = event.reason()
    if reason not in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
        return
    key = Qt.Key.Key_Tab if reason == Qt.FocusReason.TabFocusReason else Qt.Key.Key_Backtab

    def step() -> None:
        if label.hasFocus() and not label.hasSelectedText():
            QApplication.sendEvent(label, QKeyEvent(QEvent.Type.KeyPress, key, PLAIN))

    QTimer.singleShot(0, label, step)


def tab_stop_while_it_scrolls(area: QAbstractScrollArea) -> None:
    bar = area.verticalScrollBar()

    def follow() -> None:
        stops = bar.maximum() > bar.minimum()
        area.setFocusPolicy(Qt.FocusPolicy.TabFocus if stops else Qt.FocusPolicy.NoFocus)

    bar.rangeChanged.connect(lambda _low, _high: follow())
    follow()


def chain(widgets: Sequence[QWidget]) -> None:
    for before, after in zip(widgets, widgets[1:], strict=False):
        QWidget.setTabOrder(before, after)


class OneStop(QObject):
    def __init__(self, members: Sequence[QWidget], entry: Callable[[], QWidget | None]) -> None:
        super().__init__(members[0])
        self.members: list[QWidget] = []
        self._entry = entry
        self.reset(members)

    def reset(self, members: Sequence[QWidget]) -> None:
        for member in members:
            if member not in self.members:
                member.installEventFilter(self)
        self.members = list(members)
        for member in self.members:
            # Qt's setTabOrder() does nothing for a widget that takes no focus.
            member.setFocusPolicy(_tab_policy(member.focusPolicy(), tab=True))
        chain(self.members)
        self.settle()

    def settle(self) -> None:
        entry = self._entry()
        for member in self.members:
            member.setFocusPolicy(_tab_policy(member.focusPolicy(), tab=member is entry))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
            and not event.modifiers() & (CTRL | ALT)
        ):
            for member in self.members:
                member.setFocusPolicy(_tab_policy(member.focusPolicy(), tab=False))
            # Qt looks for the next stop once this returns, past every member: they come back after.
            QTimer.singleShot(0, self, self.settle)
        return False


def _tab_policy(policy: Qt.FocusPolicy, *, tab: bool) -> Qt.FocusPolicy:
    clicks = policy in (
        Qt.FocusPolicy.ClickFocus, Qt.FocusPolicy.StrongFocus, Qt.FocusPolicy.WheelFocus
    )  # fmt: skip
    if tab:
        return Qt.FocusPolicy.StrongFocus if clicks else Qt.FocusPolicy.TabFocus
    return Qt.FocusPolicy.ClickFocus if clicks else Qt.FocusPolicy.NoFocus
