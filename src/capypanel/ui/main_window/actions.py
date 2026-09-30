"""Every main-window command, defined once and reused by menus, right-click menus and shortcuts."""

from dataclasses import dataclass

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QWidget

from capypanel.core.i18n import _


@dataclass(frozen=True)
class Actions:
    new_list: QAction
    open_list: QAction
    settings: QAction
    exit: QAction
    add_host: QAction
    add_group: QAction
    edit: QAction
    remove: QAction
    show_groups: QAction
    show_details: QAction
    show_status_bar: QAction


def create_actions(parent: QWidget) -> Actions:
    def action(text: str, shortcut: str | None = None, *, checkable: bool = False) -> QAction:
        new = QAction(text, parent)
        if shortcut:
            new.setShortcut(QKeySequence(shortcut))
        new.setCheckable(checkable)
        return new

    return Actions(
        new_list=action(_("&New host list…")),
        open_list=action(_("&Open host list…"), "Ctrl+O"),
        settings=action(_("&Settings…"), "Ctrl+,"),
        exit=action(_("E&xit"), "Ctrl+Q"),
        add_host=action(_("Add &host…"), "Ctrl+N"),
        add_group=action(_("Add &group…"), "Ctrl+Shift+N"),
        edit=action(_("&Edit selected…"), "F2"),
        remove=action(_("&Remove selected"), "Del"),
        show_groups=action(_("&Groups pane"), checkable=True),
        show_details=action(_("&Details pane"), checkable=True),
        show_status_bar=action(_("&Status bar"), checkable=True),
    )
