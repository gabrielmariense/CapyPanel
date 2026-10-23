"""A tool's toolbar: outlined buttons in groups split by thin lines (set by the tool, not by users),
the first button lined up with the panels below it."""

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

BAR_GAP = 6  # space above and below the toolbar's buttons


class ToolBar(QToolBar):
    """A tool adds its groups of buttons (add_group) and gives them icons in restyle()."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("main")
        self.setMovable(False)
        self.setFloatable(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)  # no hide-me menu
        self.setIconSize(QSize(16, 16))  # icons at the text's height, not 24 px
        # One row in a plain layout, its left edge lined up with the panels by align().
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._row = QHBoxLayout(row)
        self._row.setContentsMargins(0, 0, 0, 0)  # set by align(), once the theme is known
        self._row.setSpacing(0)
        self._row.addStretch(1)
        self._groups = 0
        self.addWidget(row)

    def add_group(self, buttons: list[QToolButton]) -> None:
        """Buttons that belong together; a thin line sets each group apart from the one before."""
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)  # between buttons
        if self._groups:  # 10 px on each side of the line
            row.addSpacing(4)
            divider = QFrame()
            divider.setObjectName("toolDivider")
            divider.setFixedWidth(1)
            row.addWidget(divider)
            row.setContentsMargins(4, 0, 0, 0)
        self._groups += 1
        for button in buttons:
            row.addWidget(button)
        self._row.insertWidget(self._row.count() - 1, group)  # before the stretch

    def retranslate(self) -> None:
        """The buttons' texts and tooltips."""

    def restyle(self) -> None:
        """Icons in the theme's colours."""

    def align(self, left: int) -> None:
        """Lines the first button up with the panels: it starts at `left`, in this toolbar's
        coordinates. Measured, so it holds in every theme."""
        row = self._row.parentWidget()  # the row of groups, not a group
        if row is None:
            return
        start = row.mapTo(self, QPoint(0, 0)).x()  # the margins move what's inside, not the row
        # 6 px above and below the buttons, less the margin the theme's style already adds
        # (it differs per theme, and the Windows style ignores padding).
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
    """Sized to exactly what it draws: icon, text and the theme's padding. Qt's own size also
    reserves an icon gap and margins the theme doesn't draw, which left buttons ~12 px wider."""

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
    """A toolbar button; a dropdown opens its menu on a click."""
    button = ToolButton()
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setAutoRaise(True)
    if dropdown:
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return button
