"""What every window shares: its main button and Cancel, running it modally, and never
opening larger than the screen."""

from PySide6.QtCore import QEvent, QObject, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QWidget,
)

from capypanel.ui.themes import engine as themes

FRAME = QSize(16, 40)  # px Windows adds around a window: its borders and title bar


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


def fit_screen(window: QWidget, free: QSize | None = None) -> bool:
    """A window never opens larger than the screen's free area (a small laptop, a big text
    scale): it takes what there is, and its panes shrink and scroll. One of a fixed size
    stays fixed, at what fits. `free`: that area, when it isn't the window's own screen's.
    True when the window was made smaller."""
    if free is None:
        screen = window.screen()
        if screen is None:
            return False
        area = screen.availableGeometry()
        free = area.size()
    else:
        area = None
    most = (free - FRAME).expandedTo(QSize(320, 240))  # never to nothing, on an odd answer
    size = window.size().boundedTo(most)
    if size == window.size():
        return False
    if window.minimumSize() == window.maximumSize():
        window.setFixedSize(size)
    else:
        window.setMinimumSize(window.minimumSize().boundedTo(size))
        window.resize(size)
    if area is not None and window.isVisible():  # still where it opened, as far as it fits
        left = min(max(window.x(), area.left()), max(area.left(), area.right() - size.width()))
        top = min(max(window.y(), area.top()), max(area.top(), area.bottom() - size.height()))
        window.move(left, top)
    return True


class ScreenFit(QObject):
    """Installed on the application: every window and dialog is fitted to its screen as it
    shows, so no screen has to remember to."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            kinds = (Qt.WindowType.Window, Qt.WindowType.Dialog)
            if watched.isWindow() and watched.windowType() in kinds:
                fit_screen(watched)
        return False
