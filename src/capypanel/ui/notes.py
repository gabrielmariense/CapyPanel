"""Short help under a control: a few bullets in a smaller, quieter font, since long paragraphs
go unread."""

from PySide6.QtWidgets import QLabel


def notes(*lines: str) -> QLabel:
    label = QLabel("\n".join(f"• {line}" for line in lines if line))
    label.setObjectName("hint")
    label.setWordWrap(True)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.9)
    label.setFont(font)
    return label
