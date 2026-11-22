from PySide6.QtCore import QEvent, QMargins, QPoint, QSize, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QStyle,
    QStyleOptionToolButton,
    QToolBar,
    QToolButton,
    QWidget,
)

BAR_GAP = 6


class ToolBar(QToolBar):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("main")
        self.setMovable(False)
        self.setFloatable(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setIconSize(QSize(16, 16))
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._row = QHBoxLayout(row)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(0)
        self._row.addStretch(1)
        self._groups = 0
        self.addWidget(row)

    def add_group(self, buttons: list[QToolButton]) -> None:
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        if self._groups:
            row.addSpacing(4)
            divider = QFrame()
            divider.setObjectName("toolDivider")
            divider.setFixedWidth(1)
            row.addWidget(divider)
            row.setContentsMargins(4, 0, 0, 0)
        self._groups += 1
        for button in buttons:
            row.addWidget(button)
        self._row.insertWidget(self._row.count() - 1, group)

    def retranslate(self) -> None:
        pass

    def restyle(self) -> None:
        pass

    def align(self, left: int) -> None:
        row = self._row.parentWidget()
        if row is None:
            return
        start = row.mapTo(self, QPoint(0, 0)).x()
        # 6 px around the buttons, less the theme's own margin: the Windows style ignores padding.
        layout = self.layout()
        style_margin = layout.contentsMargins().top() if layout is not None else 0
        wanted = QMargins(max(0, left - start), max(0, BAR_GAP - style_margin), 0, 0)
        wanted.setBottom(wanted.top())
        if self._row.contentsMargins() != wanted:
            self._row.setContentsMargins(wanted)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.restyle()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self.restyle()


class ToolButton(QToolButton):
    """Sized to what it draws: Qt adds an icon gap and margins the theme doesn't draw."""

    def sizeHint(self) -> QSize:
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        metrics = self.fontMetrics()
        icon = option.iconSize if not self.icon().isNull() else QSize(0, 0)
        content = QSize(
            icon.width() + 4 + metrics.horizontalAdvance(self.text()),  # Qt draws a 4 px gap
            max(icon.height(), metrics.height()),
        )
        return self.style().sizeFromContents(
            QStyle.ContentsType.CT_ToolButton, option, content, self
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


def tool_button(*, dropdown: bool = False) -> QToolButton:
    button = ToolButton()
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    if dropdown:
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return button
