"""The Hosts tool's commands: the list workspace's, plus adding, connecting and Refresh."""

from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from capypanel.core.i18n import _
from capypanel.ui.list_workspace import actions as list_actions
from capypanel.ui.list_workspace.actions import ListActions, retranslate_list_actions
from capypanel.ui.main_window.actions import make_actions


@dataclass(frozen=True)
class HostsActions(ListActions):
    add_host: QAction
    import_hosts: QAction
    export_hosts: QAction
    connect_host: QAction
    manual_connect: QAction
    copy_address: QAction
    check_status: QAction
    check_users: QAction
    refresh_shown: QAction
    forget_passwords: QAction
    connection_profiles: QAction
    show_domains: QAction


SHORTCUTS = {
    **list_actions.SHORTCUTS,
    "add_host": "Ctrl+N",
    "connect_host": "Return",  # only while the host table has focus (see HostsTool)
    "manual_connect": "Ctrl+M",
    "copy_address": "Ctrl+Shift+C",
    "refresh_shown": "F5",  # what Refresh's right-click panel has ticked
}
CHECKABLE = {*list_actions.CHECKABLE, "show_domains"}


def create_actions(parent: QObject | None) -> HostsActions:
    actions = make_actions(HostsActions, parent, SHORTCUTS, CHECKABLE)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: HostsActions) -> None:
    retranslate_list_actions(a)
    a.add_host.setText(_("Add &host…"))
    a.import_hosts.setText(_("&Import hosts…"))
    a.export_hosts.setText(_("&Report…"))
    a.connect_host.setText(_("&Connect"))
    a.manual_connect.setText(_("&Manual connection…"))
    a.copy_address.setText(_("&Address"))  # in the host menu's Copy submenu
    a.refresh_shown.setText(_("Refresh"))
    a.check_status.setText(_("Refresh &status"))
    a.check_users.setText(_("Refresh &logged-on users"))
    a.forget_passwords.setText(_("&All profiles"))  # in Connect's Forget typed passwords
    a.connection_profiles.setText(_("Connection &profiles…"))
    a.show_domains.setText(_("Show users' do&main"))
