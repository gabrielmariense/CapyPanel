from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from capypanel.core.i18n import _
from capypanel.ui.list_workspace import actions as list_actions
from capypanel.ui.list_workspace.actions import ListActions, retranslate_list_actions
from capypanel.ui.main_window.actions import make_actions


@dataclass(frozen=True)
class SshActions(ListActions):
    add_host: QAction
    import_hosts: QAction
    connect_host: QAction
    connect_window: QAction
    copy_address: QAction
    refresh_shown: QAction
    refresh_selected: QAction


SHORTCUTS = {
    **list_actions.SHORTCUTS,
    "add_host": "Ctrl+N",
    "connect_host": "Return",
    "copy_address": "Ctrl+Shift+C",
    "refresh_shown": "F5",
}
CHECKABLE = set(list_actions.CHECKABLE)


def create_actions(parent: QObject | None) -> SshActions:
    actions = make_actions(SshActions, parent, SHORTCUTS, CHECKABLE)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: SshActions) -> None:
    retranslate_list_actions(a)
    a.add_host.setText(_("Add &host…"))
    a.import_hosts.setText(_("&Import hosts…"))
    a.connect_host.setText(_("&Connect"))
    a.connect_window.setText(_("Connect in a separate &window"))
    a.connect_window.setToolTip(_("Opens ssh.exe in a window of its own, outside CapyPanel"))
    a.copy_address.setText(_("&Address"))
    a.refresh_shown.setText(_("Refresh all"))
    a.refresh_selected.setText(_("Re&fresh host"))
