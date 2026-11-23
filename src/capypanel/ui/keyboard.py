from collections.abc import Sequence

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

PLAIN = Qt.KeyboardModifier.NoModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
WATCHED = frozenset({QEvent.Type.FocusIn, QEvent.Type.KeyPress, QEvent.Type.ContextMenu})


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

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind not in WATCHED or self._sending or not isinstance(watched, QWidget):
            return False
        if kind == QEvent.Type.FocusIn and isinstance(watched, QLabel):
            _to_a_link(watched, event)
            return False
        if _in_menu(watched):
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
