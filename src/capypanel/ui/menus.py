"""Menu helpers: section headings, right-click menus, and a menu that stays open while its boxes
are ticked."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QLabel, QMenu, QWidgetAction


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
