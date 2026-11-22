from PySide6.QtWidgets import QLabel, QMessageBox


def help_place(box: QMessageBox) -> str:
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    return label.toolTip().rpartition("#")[2] if label is not None else ""
