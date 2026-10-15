"""Menu helpers: section headings, right-click menus, a menu that stays open while its boxes
are ticked, and shortcuts drawn dimmed at a menu's right edge."""

import math

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
)
from PySide6.QtWidgets import QLabel, QMenu, QWidget, QWidgetAction

SHORTCUT_GAP = 4  # spaces kept between an item's text and its shortcut
SHORTCUT_RIGHT = 12  # px from the menu item's right edge, in line with a submenu's arrow


def section(menu: QMenu, title: str) -> QLabel:
    """A small heading over a part of a menu. Windows' own menu style hides QMenu.addSection()
    titles, so it's a label, styled by the themes. Returns it, to retranslate later."""
    label = QLabel(title)
    label.setObjectName("menuSection")
    heading = QWidgetAction(menu)
    heading.setDefaultWidget(label)
    heading.setEnabled(False)
    if menu.actions():
        menu.addSeparator()
    menu.addAction(heading)
    return label


def popup(menu: QMenu, where: QPoint) -> None:
    """Shows a right-click menu, then frees it: one is made per click, and each would otherwise
    stay until CapyPanel closes."""
    menu.exec(where)
    menu.deleteLater()


def shortcut_text(action: QAction) -> str:
    """How a shortcut reads in a menu: Windows calls the Return key Enter."""
    text = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
    return text.replace("Return", "Enter")


def label(action: QAction) -> str:
    """An item's text, without the room kept for its shortcut."""
    return action.text().partition("\t")[0]


def keep_room_for_shortcut(menu: QMenu, action: QAction) -> None:
    """Qt draws a shortcut right after the text, in the text's colour, where it reads as part of
    the name. Its text ends in a tab and blank space instead: Qt keeps the room, and the menu's
    ShortcutLayer draws the shortcut there."""
    keys = shortcut_text(action)
    name, tab, room = action.text().partition("\t")
    if not keys or (tab and room and not room.strip()):
        return
    metrics = menu.fontMetrics()
    spaces = math.ceil(metrics.horizontalAdvance(keys) / max(1, metrics.horizontalAdvance(" ")))
    action.setText(f"{name}\t{' ' * (spaces + SHORTCUT_GAP)}")


class ShortcutLayer(QWidget):
    """Over a menu: each item's shortcut, dimmed and against the right edge, as in Windows'
    own menus. It lets every click through to the menu."""

    def __init__(self, menu: QMenu) -> None:
        super().__init__(menu)
        self.setObjectName("shortcutLayer")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        menu.installEventFilter(self)

    @staticmethod
    def attach(menu: QMenu) -> None:
        direct = Qt.FindChildOption.FindDirectChildrenOnly
        layer = menu.findChild(ShortcutLayer, "shortcutLayer", direct)
        if layer is None:
            layer = ShortcutLayer(menu)
        layer.setGeometry(menu.rect())
        layer.raise_()
        layer.show()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize and isinstance(watched, QWidget):
            self.setGeometry(watched.rect())
        return False

    def paintEvent(self, event: QPaintEvent) -> None:
        menu = self.parentWidget()
        if not isinstance(menu, QMenu):
            return
        painter = QPainter(self)
        painter.setFont(menu.font())
        # The text's own colour, half see-through: dim on any background, in every theme.
        dim = QColor(menu.palette().color(QPalette.ColorRole.Text))
        dim.setAlphaF(0.55)
        painter.setPen(dim)
        for action in menu.actions():
            keys = shortcut_text(action) if action.isVisible() else ""
            if keys:
                box = menu.actionGeometry(action)
                area = QRect(box.left(), box.top(), box.width() - SHORTCUT_RIGHT, box.height())
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                painter.drawText(area, align, keys)


class StayOpenMenu(QMenu):
    """Ticking a checkable item here toggles it without closing the menu, so several can be
    switched in one go. Other items and submenus behave as usual."""

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.activeAction()
        if action is not None and action.isCheckable() and action.isEnabled():
            action.trigger()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        action = self.activeAction()
        keys = (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
        if event.key() in keys and action is not None and action.isCheckable():
            action.trigger()
            return
        super().keyPressEvent(event)
