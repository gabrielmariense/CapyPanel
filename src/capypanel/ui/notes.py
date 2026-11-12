"""Small pieces every screen uses: short help under a control (a quieter line of text, or a few
bullets in a smaller font, since long paragraphs go unread), a thin line between parts, and text
made safe to show as rich text."""

import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy


def escape(text: str) -> str:
    """Text shown as rich text: <, > and & escaped; quotes stay as they are."""
    return html.escape(text, quote=False)


def divider() -> QFrame:
    """A thin line across, between two parts of a panel."""
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


class Elided(QLabel):
    """One line that takes the width it's given and puts "…" where its text doesn't fit: at
    the end, or in the middle for a path (both ends stay). Cut, its tooltip says it in full."""

    def __init__(
        self, text: str = "", mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight
    ) -> None:
        super().__init__(text)
        self.full, self._mode = text, mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full(self, text: str) -> None:
        self.full = text
        self._fit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = self.fontMetrics().elidedText(self.full, self._mode, self.width())
        if shown != self.text():
            self.setText(shown)
        self.setToolTip(self.full if shown != self.full else "")


def hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def notes(*lines: str) -> QLabel:
    """A few lines as bullets; a single line needs none."""
    kept = [line for line in lines if line]
    label = hint("\n".join(f"• {line}" for line in kept) if len(kept) > 1 else "".join(kept))
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.9)
    label.setFont(font)
    return label
