"""The Details panel: the selected item in sections, every value copied by a click. With nothing or
several items selected, a summary instead. A tool says what the sections are (build_page)."""

import html
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _

LONG_WORD = 24  # longer runs of letters may break anywhere, so they never widen the panel
MARK = "rgba(255, 196, 0, 0.38)"  # the search's mark, as in the items table


def breakable(text: str) -> str:
    """Lets long words (an address, a path) wrap at any character: a word too wide for the panel
    would otherwise make it wider."""
    zero_width = "​"
    return " ".join(
        zero_width.join(word) if len(word) > LONG_WORD else word for word in text.split(" ")
    )


class CopyValue(QLabel):
    """A value that highlights on hover and copies itself on a click."""

    copied = Signal(str)

    def __init__(self, text: str, shown: str | None = None) -> None:
        super().__init__(shown if shown is not None else breakable(text))
        self._text = text
        self.setObjectName("copyValue")
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # the stylesheet's :hover
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Click to copy"))

    def copy_text(self) -> str:
        return self._text

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QGuiApplication.clipboard().setText(self._text)
            self.copied.emit(self._text)
        super().mousePressEvent(event)


class DetailsPanel(QWidget):
    """Details of the selected item, or a summary when none or several are selected."""

    copied = Signal(str)  # a value was copied: the window says so in its status bar

    def __init__(self) -> None:
        super().__init__()
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._values: dict[str, list[CopyValue]] = {}
        self._shown: tuple[object, str] | None = None  # what's on show, and the search

        # A card with the lists' background, so the three panels read as a set in every theme.
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setBackgroundRole(QPalette.ColorRole.Base)
        card.setAutoFillBackground(True)
        self._pages = QStackedLayout(card)
        self._pages.addWidget(self._hint)
        self._pages.addWidget(self._scroll)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.show_item(None, 0)

    # ---- what a tool says ----

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        """The sections for one item, added to `layout` with the helpers below."""
        raise NotImplementedError

    def selected_text(self, selected: int) -> str:
        """With several items selected: "{n} hosts selected"."""
        raise NotImplementedError

    def pick_hint(self) -> str:
        """With none selected: "Select a host to see its details."."""
        raise NotImplementedError

    # ---- showing ----

    def retranslate(self) -> None:
        """The hint comes back with the next show_item(); an item on show is drawn again."""
        if self._shown is not None:
            self._build(*self._shown)

    def show_item(
        self, shown: object | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        """summary: what the table shows, above the hint when none is picked.
        needle: the search, marked where it's found in the notes."""
        if shown is None:
            self._shown = None
            if selected > 1:
                self._hint.setText(self.selected_text(selected))
            else:
                hint = self.pick_hint()
                self._hint.setText(f"{summary}\n\n{hint}" if summary else hint)
            self._pages.setCurrentIndex(0)
            return
        self._shown = (shown, needle)
        self._build(shown, needle)
        self._pages.setCurrentIndex(1)

    def shown_value(self, key: str) -> str:
        """The text a section shows, one value per line: for tests and the window."""
        return "\n".join(v.copy_text() for v in self._values.get(key, []))

    def _build(self, shown: object, needle: str) -> None:
        self._values = {}
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)
        self.build_page(layout, shown, needle)
        layout.addStretch(1)
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self._scroll.setWidget(page)

    # ---- the parts a page is built from ----

    def chips(self, tags: Sequence[str]) -> QWidget:
        row = QWidget()
        flow = QHBoxLayout(row)
        flow.setContentsMargins(0, 2, 0, 2)
        flow.setSpacing(6)
        for tag in tags:
            chip = self.value("tags", tag)
            chip.setObjectName("tagValue")
            chip.setWordWrap(False)
            flow.addWidget(chip)
        flow.addStretch(1)
        return row

    def notes(self, notes: str, needle: str) -> QWidget:
        box = QFrame()
        box.setObjectName("notesBox")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(4, 4, 4, 4)
        value = self.value("notes", notes, marked(notes, needle))
        value.setTextFormat(Qt.TextFormat.RichText)
        inner.addWidget(value)
        return box

    def value(self, key: str, text: str, shown: str | None = None) -> CopyValue:
        value = CopyValue(text, shown)
        value.copied.connect(self.copied)
        self._values.setdefault(key, []).append(value)
        return value

    @staticmethod
    def section(layout: QVBoxLayout, title: str) -> None:
        """A thin line across the panel, then the section's heading in the accent colour."""
        rule = QFrame()
        rule.setObjectName("detailsRule")
        layout.addSpacing(10)
        layout.addWidget(rule)
        layout.addSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("detailsSection")
        layout.addWidget(heading)

    @staticmethod
    def muted(text: str) -> QLabel:
        label = QLabel(breakable(text))
        label.setObjectName("hint")
        label.setWordWrap(True)
        return label


def marked(text: str, needle: str) -> str:
    """The text as rich text, line breaks kept, with every match of the search marked."""
    folded, needle = text.casefold(), needle.strip().casefold()
    pieces, start = [], 0
    while needle and (found := folded.find(needle, start)) != -1:
        pieces.append(_plain(text[start:found]))
        hit = _plain(text[found : found + len(needle)])
        pieces.append(f'<span style="background: {MARK};">{hit}</span>')
        start = found + len(needle)
    pieces.append(_plain(text[start:]))
    return "".join(pieces)


def _plain(text: str) -> str:
    return html.escape(breakable(text)).replace("\n", "<br>")
