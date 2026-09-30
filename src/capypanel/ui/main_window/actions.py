"""Every main-window command, defined once and reused by menus, right-click menus and shortcuts."""

from dataclasses import dataclass, fields

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


SHORTCUTS = {
    "open_list": "Ctrl+O",
    "settings": "Ctrl+,",
    "exit": "Ctrl+Q",
    "add_host": "Ctrl+N",
    "add_group": "Ctrl+Shift+N",
    "edit": "F2",
    "remove": "Del",
}
CHECKABLE = {"show_groups", "show_details", "show_status_bar"}


def create_actions(parent: QWidget) -> Actions:
    made = {}
    for field in fields(Actions):
        action = QAction(parent)
        if field.name in SHORTCUTS:
            action.setShortcut(QKeySequence(SHORTCUTS[field.name]))
        action.setCheckable(field.name in CHECKABLE)
        made[field.name] = action
    actions = Actions(**made)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: Actions) -> None:
    """Sets every command's text in the current language; runs again when it changes."""
    a.new_list.setText(_("&New host list…"))
    a.open_list.setText(_("&Open host list…"))
    a.settings.setText(_("&Settings…"))
    a.exit.setText(_("E&xit"))
    a.add_host.setText(_("Add &host…"))
    a.add_group.setText(_("Add &group…"))
    a.edit.setText(_("&Edit selected…"))
    a.remove.setText(_("&Remove selected"))
    a.show_groups.setText(_("&Groups pane"))
    a.show_details.setText(_("&Details pane"))
    a.show_status_bar.setText(_("&Status bar"))
