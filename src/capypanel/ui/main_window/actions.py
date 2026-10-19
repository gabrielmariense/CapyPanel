"""Every command, defined once and reused by menus, right-click menus and shortcuts. The shell has
its own; each tool has its own (see the list workspace and the tools)."""

from dataclasses import dataclass, fields

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence

from capypanel.core.i18n import _


def make_actions[T](
    kind: type[T], parent: QObject | None, shortcuts: dict[str, str], checkable: set[str]
) -> T:
    """One QAction per field of the dataclass `kind`, without text: retranslating fills it in."""
    made = {}
    for field in fields(kind):  # type: ignore[arg-type]
        action = QAction(parent)
        if field.name in shortcuts:
            action.setShortcut(QKeySequence(shortcuts[field.name]))
        action.setCheckable(field.name in checkable)
        made[field.name] = action
    return kind(**made)


@dataclass(frozen=True)
class ShellActions:
    settings: QAction
    exit: QAction
    show_toolbar: QAction
    show_status_bar: QAction
    show_hosts: QAction
    documentation: QAction
    report_problem: QAction
    about: QAction


SHORTCUTS = {
    "settings": "Ctrl+,",
    "exit": "Ctrl+Q",
    "show_hosts": "Ctrl+1",  # the tools, in View and on the rail
}
CHECKABLE = {"show_toolbar", "show_status_bar", "show_hosts"}


def create_actions(parent: QObject) -> ShellActions:
    actions = make_actions(ShellActions, parent, SHORTCUTS, CHECKABLE)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: ShellActions) -> None:
    """Sets every command's text in the current language; runs again when it changes."""
    a.settings.setText(_("&Settings…"))
    a.exit.setText(_("E&xit"))
    a.documentation.setText(_("&Documentation"))
    a.report_problem.setText(_("&Report a problem"))
    a.about.setText(_("&About CapyPanel"))
    a.show_toolbar.setText(_("T&oolbar"))
    a.show_status_bar.setText(_("&Status bar"))
    a.show_hosts.setText(_("&Hosts"))
