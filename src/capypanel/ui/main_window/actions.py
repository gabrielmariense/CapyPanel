"""The window's own commands, defined once for menus, right-click menus and shortcuts."""

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
    documentation: QAction
    report_problem: QAction
    show_guide: QAction
    show_all_guides: QAction
    help_screen: QAction
    check_updates: QAction
    about: QAction


SHORTCUTS = {
    "settings": "Ctrl+,",
    "exit": "Ctrl+Q",
    "help_screen": "F1",
}
CHECKABLE = {"show_toolbar", "show_status_bar"}
FIXED = {"help_screen"}  # F1 is help's: shown on the Keyboard shortcuts page, never changed


def create_actions(parent: QObject) -> ShellActions:
    actions = make_actions(ShellActions, parent, SHORTCUTS, CHECKABLE)
    retranslate_actions(actions)
    return actions


def retranslate_actions(a: ShellActions) -> None:
    a.settings.setText(_("&Settings…"))
    a.exit.setText(_("E&xit"))
    a.documentation.setText(_("&Documentation"))
    a.report_problem.setText(_("&Report a problem"))
    a.show_guide.setText(_("&Guide to this screen"))
    a.show_all_guides.setText(_("&Show all the guides again"))
    a.help_screen.setText(_("&Help for this screen"))
    a.check_updates.setText(_("Check for &updates…"))
    a.about.setText(_("&About CapyPanel"))
    a.show_toolbar.setText(_("T&oolbar"))
    a.show_status_bar.setText(_("&Status bar"))
