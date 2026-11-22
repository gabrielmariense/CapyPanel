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
    """Deleted after exec(), or every theme switch restyles each closed one; deleting one
    mid-switch crashes Qt."""
    before = themes.generation()
    result = dialog.exec()
    if themes.generation() == before:
        dialog.deleteLater()
    return result


def ok_cancel(dialog: QDialog, verb: str = "") -> QDialogButtonBox:
    box = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    if verb:
        box.button(QDialogButtonBox.StandardButton.Ok).setText(verb)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


def quiet_default(button: QAbstractButton) -> None:
    button.setObjectName("quietDefault")
    if hasattr(button, "setDefault"):
        button.setDefault(True)  # type: ignore[attr-defined]
    # Styled already under its old name: restyled, or the new look waits for a theme switch.
    button.style().unpolish(button)
    button.style().polish(button)


def fit_screen(window: QWidget, free: QSize | None = None) -> bool:
    if free is None:
        screen = window.screen()
        if screen is None:
            return False
        area = screen.availableGeometry()
        free = area.size()
    else:
        area = None
    most = (free - FRAME).expandedTo(QSize(320, 240))
    size = window.size().boundedTo(most)
    if size == window.size():
        return False
    if window.minimumSize() == window.maximumSize():
        window.setFixedSize(size)
    else:
        window.setMinimumSize(window.minimumSize().boundedTo(size))
        window.resize(size)
    if area is not None and window.isVisible():
        left = min(max(window.x(), area.left()), max(area.left(), area.right() - size.width()))
        top = min(max(window.y(), area.top()), max(area.top(), area.bottom() - size.height()))
        window.move(left, top)
    return True


def fit_height(window: QWidget, shrink: bool = False) -> None:
    """As dragging its edge would: Qt counts wrapped lines only then. Grows unless `shrink`."""
    layout = window.layout()
    if layout is None:
        return
    layout.activate()
    need = window.heightForWidth(window.width())
    if need < 0:
        if not shrink:
            return
        need = window.sizeHint().height()
    screen = window.screen()
    if screen is not None:
        need = min(need, screen.availableGeometry().height() - FRAME.height())
    if need > window.height() or (shrink and need < window.height()):
        window.resize(window.width(), need)


def kept_size(kept: object, default: tuple[int, int]) -> tuple[int, int]:
    if isinstance(kept, list) and len(kept) == 2:
        width, height = kept
        if all(type(n) is int and 200 <= n <= 20000 for n in (width, height)):
            return width, height
    return default


class ScreenFit(QObject):
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
