"""What every small window shares: its OK and Cancel buttons, and running it modally."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

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


def ok_cancel(dialog: QDialog) -> QDialogButtonBox:
    """OK and Cancel for `dialog`: OK accepts it, Cancel rejects it."""
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box
