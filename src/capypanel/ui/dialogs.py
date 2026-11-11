"""What every small window shares: its main button and Cancel, and running it modally."""

from PySide6.QtWidgets import QAbstractButton, QDialog, QDialogButtonBox, QMessageBox

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


def ok_cancel(dialog: QDialog, verb: str = "") -> QDialogButtonBox:
    """The main button and Cancel for `dialog`: the first accepts it, Cancel rejects it. A
    window ends in what it does, so `verb` names the main button ("Add", "Save", "Connect");
    it's still found as StandardButton.Ok."""
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    if verb:
        box.button(QDialogButtonBox.StandardButton.Ok).setText(verb)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def quiet_default(button: QAbstractButton) -> None:
    """Enter presses `button`, but it isn't the window's main action (Cancel before something
    risky, a lone Close): the default button drawn plain with a ring, where the filled one
    would say "this is what the window is for"."""
    button.setObjectName("quietDefault")
    if hasattr(button, "setDefault"):
        button.setDefault(True)  # type: ignore[attr-defined]
