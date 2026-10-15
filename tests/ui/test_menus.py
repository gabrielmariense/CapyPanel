from PySide6.QtCore import QPoint
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QMenu

from capypanel.ui import menus
from capypanel.ui.themes import engine as themes


def test_shortcuts_are_drawn_dimmed_at_the_right_edge_not_after_the_text(
    qapp: QApplication,
) -> None:
    themes.apply(themes.DEFAULT_THEME)  # its watcher keeps the room in every menu
    menu = QMenu()
    edit = menu.addAction("&Edit selected…")
    edit.setShortcut(QKeySequence("F2"))
    connect = menu.addAction("&Connect")
    connect.setShortcut(QKeySequence("Return"))
    plain = menu.addAction("&Status")
    name, tab, room = edit.text().partition("\t")
    assert (name, tab) == ("&Edit selected…", "\t") and room and not room.strip()  # Qt draws blanks
    assert menus.label(edit) == "&Edit selected…" and plain.text() == "&Status"
    assert menus.shortcut_text(connect) == "Enter"  # Windows' name for the key
    edit.setText("&Edit…")  # a language switch: the room comes back
    assert menus.label(edit) == "&Edit…" and "\t" in edit.text()
    menu.popup(QPoint(-3000, -3000))
    qapp.processEvents()
    layer = menu.findChild(menus.ShortcutLayer)
    assert layer is not None and layer.geometry() == menu.rect()
    menu.hide()
