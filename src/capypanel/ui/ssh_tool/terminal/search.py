from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton, QWidget

from capypanel.core.i18n import _
from capypanel.ui import spacing
from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes import engine as themes

TYPING_MS = 150  # a search waits this long after the last key: the scrollback holds 10,000 rows
FIELD_WIDTH = 200
ENTER = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class _Field(QLineEdit):
    def __init__(self, bar: "SearchBar") -> None:
        super().__init__(bar)
        self._bar = bar

    def event(self, e: QEvent) -> bool:
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and (e.key() in ENTER or e.key() == Qt.Key.Key_Escape)
        ):
            e.accept()  # ours here, never a window's
            return True
        return super().event(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in ENTER:
            shift = e.modifiers() & Qt.KeyboardModifier.ShiftModifier
            (self._bar.newer if shift else self._bar.older).emit()
        elif e.key() == Qt.Key.Key_Escape:
            self._bar.close_asked.emit()
        else:
            super().keyPressEvent(e)


class SearchBar(QFrame):
    """Floats over the terminal's top right, so opening it never resizes the terminal."""

    words_changed = Signal()
    older = Signal()
    newer = Signal()
    close_asked = Signal()
    resized = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        self.field = _Field(self)
        self.field.setFixedWidth(FIELD_WIDTH)
        self.count = QLabel()
        self.case = QToolButton()
        self.case.setCheckable(True)
        self.case.setText("Aa")
        self.up = QToolButton()
        self.down = QToolButton()
        self.close_button = QToolButton()
        for button in (self.case, self.up, self.down, self.close_button):
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(spacing.CONTROLS, spacing.ICON, spacing.ICON, spacing.ICON)
        row.setSpacing(spacing.ICON)
        row.addWidget(self.field)
        row.addWidget(self.count)
        row.addWidget(self.case)
        row.addWidget(self.up)
        row.addWidget(self.down)
        row.addWidget(self.close_button)
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(TYPING_MS)
        self._typing.timeout.connect(self.words_changed)
        self.field.textChanged.connect(lambda _text: self._typing.start())
        self.case.toggled.connect(lambda _on: self.words_changed.emit())
        self.up.clicked.connect(self.older)
        self.down.clicked.connect(self.newer)
        self.close_button.clicked.connect(self.close_asked)
        themes.switches().switched.connect(self._restyle)
        self.retranslate()
        self._restyle()
        self.hide()

    @property
    def words(self) -> str:
        return self.field.text()

    @property
    def match_case(self) -> bool:
        return self.case.isChecked()

    def retranslate(self) -> None:
        self.field.setPlaceholderText(_("Find"))
        self.case.setToolTip(_("Match case"))
        self.up.setToolTip(_("Older match (Enter)"))
        self.down.setToolTip(_("Newer match (Shift+Enter)"))
        self.close_button.setToolTip(_("Close (Esc)"))
        widest = (_("No matches"), _("{n} of {total}").format(n=999, total=999))
        metrics = self.count.fontMetrics()
        self.count.setMinimumWidth(max(metrics.horizontalAdvance(text) for text in widest))

    def show_count(self, current: int | None, total: int) -> None:
        if not self.words:
            self.count.setText("")
        elif not total or current is None:
            self.count.setText(_("No matches"))
        else:
            self.count.setText(_("{n} of {total}").format(n=current + 1, total=total))
        if self.width() < self.sizeHint().width():
            self.adjustSize()
            self.resized.emit()

    def flush(self) -> bool:
        if not self._typing.isActive():
            return False
        self._typing.stop()
        self.words_changed.emit()
        return True

    def _restyle(self) -> None:
        self.ensurePolished()
        ink = self.palette().color(QPalette.ColorRole.WindowText)
        self.up.setIcon(tabler_icon("chevron-up", ink, 16))
        self.down.setIcon(tabler_icon("chevron-down", ink, 16))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        self.close_button.setIcon(tabler_icon("x", muted, 14))
