"""The Printers tool's commands: the list workspace's, plus adding printers, their web pages and
Report."""

from dataclasses import dataclass

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from capypanel.core.i18n import _
from capypanel.ui.list_workspace import actions as list_actions
from capypanel.ui.list_workspace.actions import ListActions, retranslate_list_actions
from capypanel.ui.main_window.actions import make_actions


@dataclass(frozen=True)
class PrintersActions(ListActions):
    add_printer: QAction
    export_printers: QAction
    open_web_page: QAction
    copy_address: QAction


SHORTCUTS = {
    **list_actions.SHORTCUTS,
    "add_printer": "Ctrl+N",
    "open_web_page": "Return",  # only while the printer table has focus (see PrintersTool)
    "copy_address": "Ctrl+Shift+C",
}
CHECKABLE = set(list_actions.CHECKABLE)


def create_actions(parent: QObject | None) -> PrintersActions:
    actions = make_actions(PrintersActions, parent, SHORTCUTS, CHECKABLE)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: PrintersActions) -> None:
    retranslate_list_actions(a)
    a.add_printer.setText(_("Add &printer…"))
    a.export_printers.setText(_("&Report…"))
    a.open_web_page.setText(_("Open &web page"))
    a.copy_address.setText(_("&Address"))  # in the printer menu's Copy submenu
