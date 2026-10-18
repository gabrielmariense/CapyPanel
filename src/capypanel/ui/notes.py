"""Short help under a control: a quieter line of text, or a few bullets in a smaller font, since
long paragraphs go unread."""

from PySide6.QtWidgets import QLabel


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
