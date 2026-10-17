"""Running a window modally, then freeing it."""

from PySide6.QtWidgets import QDialog, QMessageBox

from capypanel.ui.themes import engine as themes


def run_modal(dialog: QDialog | QMessageBox) -> int:
    """exec(), then deletes the window: kept alive, every closed one was restyled again on each
    theme switch, and switching got slower the longer CapyPanel ran. A window that was open
    during a theme switch stays, hidden: deleting it can crash inside Qt."""
    before = themes.generation()
    result = dialog.exec()
    if themes.generation() == before:
        dialog.deleteLater()  # after the caller has read what it needs from it
    return result
