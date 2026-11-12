"""The Details panel: the selected item in sections, every value copied by a click. With nothing or
several items selected, a summary instead. A tool says what the sections are (build_page)."""

import html
from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QGuiApplication, QMouseEvent, QPalette
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QStackedLayout,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.ui.icons import tabler_icon
from capypanel.ui.menus import popup

LONG_WORD = 24  # longer runs of letters may break anywhere, so they never widen the panel
MARK = "rgba(255, 196, 0, 0.38)"  # the search's mark, as in the items table


def breakable(text: str) -> str:
    """Lets long words (an address, a path) wrap at any character: a word too wide for the panel
    would otherwise make it wider."""
    zero_width = "​"
    return " ".join(
        zero_width.join(word) if len(word) > LONG_WORD else word for word in text.split(" ")
    )


SIDE = 14  # px at each side of a panel's page
BUTTON_HEIGHT = 44  # px: a button on top of the panel, its icon over its word
BUTTON_ROOM = 16  # px beside the widest word: every button is that wide
COLUMNS = 4  # the buttons' grid: rows of four
GAP = 8  # px between buttons
BUTTON_ICON = 18


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

    def set_text(self, text: str) -> None:
        """Another value in the same place: what shows, and what a click copies."""
        self._text = text
        self.setText(breakable(text))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QGuiApplication.clipboard().setText(self._text)
            self.copied.emit(self._text)
        super().mousePressEvent(event)


class DetailsPanel(QWidget):
    """Details of the selected item, or a summary when none or several are selected."""

    copied = Signal(str)  # a value was copied: the window says so in its status bar
    customize_requested = Signal()  # the panel's right-click, or its hidden-parts line
    customizable = False  # a tool with parts that can be hidden sets it

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

    def item_id(self, shown: object) -> str:
        """Which item a page is about. The same item drawn again keeps its scroll position."""
        return ""

    # ---- showing ----

    def minimum_width(self) -> int:
        """The narrowest the panel may be dragged, when its own parts need more than the
        workspace's usual minimum; 0 when they don't."""
        return 0

    # ---- the buttons on top: an icon over one short word, in rows of four ----

    def word_button(self, icon: str, color: QColor, word: str, tip: str, *,
                    risky: bool = False) -> QToolButton:  # fmt: skip
        """One button of the grid; `tip` is its full name. Risky ones are amber."""
        button = QToolButton()
        button.setObjectName("commandButton")
        button.setProperty("risky", risky)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setText(word.replace("&", "&&"))
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(tabler_icon(icon, color, BUTTON_ICON))
        button.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
        return button

    def grid_width(self, words: Sequence[str]) -> int:
        """How wide every button is: what the widest of `words` needs in this font and language.
        Give it every word a button can have, so the grid never changes width."""
        metrics = self.fontMetrics()
        return max(metrics.horizontalAdvance(word) for word in words) + BUTTON_ROOM

    def grid_minimum(self, width: int) -> int:
        """Room for four columns of `width`, the page's sides and a scroll bar beside them."""
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        return COLUMNS * width + (COLUMNS - 1) * GAP + 2 * SIDE + bar + 4

    @staticmethod
    def button_rows(buttons: Sequence[QToolButton], width: int) -> QVBoxLayout:
        """`buttons` in rows of four, each `width` wide. A row that isn't full keeps its buttons
        on the left: nothing stretches."""
        rows = QVBoxLayout()
        rows.setSpacing(GAP)
        for start in range(0, len(buttons), COLUMNS):
            row = QHBoxLayout()
            row.setSpacing(GAP)
            for button in buttons[start : start + COLUMNS]:
                button.setFixedSize(width, BUTTON_HEIGHT)
                row.addWidget(button)
            row.addStretch(1)
            rows.addLayout(row)
        return rows

    # ---- parts the person chose to hide ----

    def hidden_line(self, layout: QVBoxLayout, hidden: int) -> None:
        """At the foot of the page, when parts are hidden: how many, and the way back."""
        if not hidden:
            return
        text = ngettext("{n} part hidden", "{n} parts hidden", hidden).format(n=hidden)
        line = QLabel(
            f'{html.escape(text)} · <a href="customize">{html.escape(_("Customize…"))}</a>'
        )
        line.setObjectName("hint")
        line.setTextFormat(Qt.TextFormat.RichText)
        line.linkActivated.connect(lambda _href: self.customize_requested.emit())
        layout.addSpacing(8)
        layout.addWidget(line)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if not self.customizable:
            return
        menu = QMenu(self)
        menu.addAction(_("&Customize the details panel…"), self.customize_requested.emit)
        popup(menu, event.globalPos())

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
        before = self.item_id(self._shown[0]) if self._shown else ""
        self._shown = (shown, needle)
        bar = self._scroll.verticalScrollBar()
        kept = bar.value() if before and before == self.item_id(shown) else 0
        self._build(shown, needle)
        self._pages.setCurrentIndex(1)
        if kept:  # after the new page is laid out, or the bar's range is still the old one's
            QTimer.singleShot(0, self, lambda: bar.setValue(kept))  # dropped if it goes

    def shown_value(self, key: str) -> str:
        """The text a section shows, one value per line: for tests and the window."""
        return "\n".join(v.copy_text() for v in self._values.get(key, []))

    def _build(self, shown: object, needle: str) -> None:
        self._values = {}
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(SIDE, 12, SIDE, 12)
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
