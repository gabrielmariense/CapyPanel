"""The splitter between the panes: a double-click on the edge between two panes says which."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QSplitter, QSplitterHandle


class _Handle(QSplitterHandle):
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        splitter = self.splitter()
        if isinstance(splitter, PaneSplitter) and event.button() == Qt.MouseButton.LeftButton:
            splitter.edge_double_clicked.emit(splitter.indexOf(self))
        super().mouseDoubleClickEvent(event)


class PaneSplitter(QSplitter):
    edge_double_clicked = Signal(int)  # the edge on the left of this pane's index

    def createHandle(self) -> QSplitterHandle:
        return _Handle(self.orientation(), self)
