"""Message boxes as tests read them."""

from PySide6.QtWidgets import QLabel, QMessageBox


def help_place(box: QMessageBox) -> str:
    """The docs line `box`'s "What does this mean?" opens (help_links.add_link), or "" when it
    has none: the link's address is its label's tooltip, which ends #place."""
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    return label.toolTip().rpartition("#")[2] if label is not None else ""
