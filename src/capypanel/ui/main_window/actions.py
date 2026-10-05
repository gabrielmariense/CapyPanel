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
    manage_groups: QAction
    edit: QAction
    remove: QAction
    connect_host: QAction
    manual_connect: QAction
    copy_address: QAction
    copy_name: QAction
    check_status: QAction
    check_users: QAction
    forget_passwords: QAction
    connection_profiles: QAction
    show_toolbar: QAction
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
    "connect_host": "Return",  # only while the host table has focus (see MainWindow)
    "manual_connect": "Ctrl+M",
    "copy_address": "Ctrl+Shift+C",
}
CHECKABLE = {"show_toolbar", "show_groups", "show_details", "show_status_bar"}


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
    a.open_list.setText(_("&Host lists…"))
    a.settings.setText(_("&Settings…"))
    a.exit.setText(_("E&xit"))
    a.add_host.setText(_("Add &host…"))
    a.add_group.setText(_("Add &group…"))
    a.manage_groups.setText(_("&Manage groups…"))
    a.edit.setText(_("&Edit selected…"))
    a.remove.setText(_("&Remove selected"))
    a.connect_host.setText(_("&Connect"))
    a.manual_connect.setText(_("&Manual connection…"))
    # Under a "Copy" heading in the right-click menu, so the item names stay short.
    a.copy_address.setText(_("&Address"))
    a.copy_name.setText(_("&Name"))
    a.check_status.setText(_("&Status"))
    a.check_users.setText(_("&Logged-on users"))
    a.forget_passwords.setText(_("&Forget typed passwords"))
    a.connection_profiles.setText(_("Connection &profiles…"))
    a.show_toolbar.setText(_("T&oolbar"))
    a.show_groups.setText(_("&Groups pane"))
    a.show_details.setText(_("&Details pane"))
    a.show_status_bar.setText(_("&Status bar"))
