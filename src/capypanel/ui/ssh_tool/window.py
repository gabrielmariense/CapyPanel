from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from capypanel.ui.themes import engine as themes

if TYPE_CHECKING:
    from capypanel.ui.ssh_tool.terminal.tab import TerminalTab


class ConnectionWindow(QWidget):
    def __init__(self, tab: "TerminalTab", may_close: Callable[[], bool]) -> None:
        super().__init__()
        self.tab = tab
        self._may_close = may_close
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tab)
        tab.set_in_window(True)
        tab.show()
        QShortcut(QKeySequence("Ctrl+Shift+W"), self, self.close)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._may_close():
            super().closeEvent(event)
        else:
            event.ignore()
