"""The commands every list tool has: lists, groups, editing, and its panels in View. A tool's own
actions extend these (a dataclass with more fields)."""

from dataclasses import dataclass

from PySide6.QtGui import QAction

from capypanel.core.i18n import _


@dataclass(frozen=True)
class ListActions:
    new_list: QAction
    open_list: QAction
    add_group: QAction
    manage_groups: QAction
    edit: QAction
    remove: QAction
    show_groups: QAction
    show_tags: QAction
    show_details: QAction


SHORTCUTS = {
    "open_list": "Ctrl+O",
    "add_group": "Ctrl+Shift+N",
    "edit": "F2",
    "remove": "Del",
}
CHECKABLE = {"show_groups", "show_tags", "show_details"}


def retranslate_list_actions(a: ListActions) -> None:
    a.new_list.setText(_("&New list…"))
    a.open_list.setText(_("&Open list…"))
    a.add_group.setText(_("Add &group…"))
    a.manage_groups.setText(_("&Manage groups…"))
    a.edit.setText(_("&Edit selected…"))
    a.remove.setText(_("&Remove selected"))
    a.show_groups.setText(_("&Groups pane"))
    a.show_tags.setText(_("T&ags pane"))
    a.show_details.setText(_("&Details pane"))
