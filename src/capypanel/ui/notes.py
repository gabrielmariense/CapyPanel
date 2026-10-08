"""Short help under a control: a quieter line of text, or a few bullets in a smaller font, since
long paragraphs go unread."""

from PySide6.QtWidgets import QLabel


def hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def notes(*lines: str) -> QLabel:
    label = hint("\n".join(f"• {line}" for line in lines if line))
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.9)
    label.setFont(font)
    return label
