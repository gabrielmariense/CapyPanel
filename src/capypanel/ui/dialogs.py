"""What every window shares: its main button and Cancel, running it modally, never opening
larger than the screen, and room for its wrapped text."""

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
    """exec(), then deletes the window: kept alive, every closed one is restyled on each theme
    switch. One open during a switch stays, hidden: deleting it can crash inside Qt."""
    before = themes.generation()
    result = dialog.exec()
    if themes.generation() == before:
        dialog.deleteLater()  # after the caller has read what it needs from it
    return result


def ok_cancel(dialog: QDialog, verb: str = "") -> QDialogButtonBox:
    """The main button and Cancel for `dialog`: the first accepts, Cancel rejects. `verb` names the
    main button ("Add", "Save", "Connect"): a window ends in what it does. Still found as Ok."""
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
    risky, a lone Close): drawn plain with a ring, as a filled one says "this is what it's for"."""
    button.setObjectName("quietDefault")
    if hasattr(button, "setDefault"):
        button.setDefault(True)  # type: ignore[attr-defined]
    # Already styled under its old name (a button box sizes its buttons as it adds them):
    # styled again, or the new look only shows after the next theme switch.
    button.style().unpolish(button)
    button.style().polish(button)


def fit_screen(window: QWidget, free: QSize | None = None) -> bool:
    """A window never opens larger than the screen's free area: it takes what there is, its panes
    shrinking; a fixed one stays fixed. `free`: another screen's. True when it was made smaller."""
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


def fit_height(window: QWidget, shrink: bool = False) -> None:
    """Gives a window the height its rows and wrapped text need at its width, as dragging its
    edge would: Qt counts wrapped lines only then. Taller only, unless `shrink`."""
    layout = window.layout()
    if layout is None:
        return
    layout.activate()
    need = window.heightForWidth(window.width())
    if need < 0:  # no wrapped text
        if not shrink:
            return
        need = window.sizeHint().height()
    screen = window.screen()
    if screen is not None:
        need = min(need, screen.availableGeometry().height() - FRAME.height())
    if need > window.height() or (shrink and need < window.height()):
        window.resize(window.width(), need)


def kept_size(kept: object, default: tuple[int, int]) -> tuple[int, int]:
    """A window's size as the person left it, kept in their settings as [width, height];
    `default` the first time, or when the file holds anything else (it can be edited by hand)."""
    if isinstance(kept, list) and len(kept) == 2:
        width, height = kept
        if all(type(n) is int and 200 <= n <= 20000 for n in (width, height)):
            return width, height
    return default


class ScreenFit(QObject):
    """Installed on the application: every window fits its screen as it shows, and a dialog
    grows to its wrapped text as it shows and whenever its rows change."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Show and isinstance(watched, QWidget):
            kinds = (Qt.WindowType.Window, Qt.WindowType.Dialog)
            if watched.isWindow() and watched.windowType() in kinds:
                if watched.windowType() == Qt.WindowType.Dialog:
                    fit_height(watched)
                fit_screen(watched)
        elif kind == QEvent.Type.LayoutRequest and isinstance(watched, QWidget):
            dialog = watched.isWindow() and watched.windowType() == Qt.WindowType.Dialog
            if dialog and watched.isVisible():
                fit_height(watched)
        return False
