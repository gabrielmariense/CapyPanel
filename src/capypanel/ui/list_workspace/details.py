import html
from collections.abc import Sequence

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QGuiApplication,
    QMouseEvent,
    QPaintEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QStackedLayout,
    QStyle,
    QStyleOptionToolButton,
    QStylePainter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.ui import keyboard
from capypanel.ui.icons import tabler_icon
from capypanel.ui.menus import popup

LONG_WORD = 24  # longer runs of letters may break anywhere, so they never widen the panel
MARK = "rgba(255, 196, 0, 0.38)"


def breakable(text: str) -> str:
    zero_width = "\u200b"
    return " ".join(
        zero_width.join(word) if len(word) > LONG_WORD else word for word in text.split(" ")
    )


SIDE = 14
BUTTON_HEIGHT = 44
BUTTON_ROOM = 16
COLUMNS = 4
GAP = 8
BUTTON_ICON = 18
MENU_ICON = 14
MENU_GAP = 2


class MenuWordButton(QToolButton):
    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        word, option.text = option.text, " "  # an empty word would centre the icon
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        style = self.style()
        flags = Qt.TextFlag.TextShowMnemonic
        if not style.styleHint(QStyle.StyleHint.SH_UnderlineShortcut, option, self):
            flags |= Qt.TextFlag.TextHideMnemonic
        # Qt's common style puts the word in the rest under an icon box 4 px taller than the icon.
        line = self.rect().adjusted(0, self.iconSize().height() + 3, 0, -1)
        if option.state & (QStyle.StateFlag.State_Sunken | QStyle.StateFlag.State_On):
            line.translate(
                style.pixelMetric(QStyle.PixelMetric.PM_ButtonShiftHorizontal, option, self),
                style.pixelMetric(QStyle.PixelMetric.PM_ButtonShiftVertical, option, self),
            )
        metrics = self.fontMetrics()
        width = metrics.size(flags, word).width()
        left = line.left() + (line.width() - width - MENU_GAP - MENU_ICON) // 2
        spot = QRect(left, line.top(), width, line.height())
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        style.drawItemText(painter, spot, int(align) | int(flags), option.palette,
                           self.isEnabled(), word, QPalette.ColorRole.ButtonText)  # fmt: skip
        baseline = spot.top() + (spot.height() - metrics.height()) / 2 + metrics.ascent()
        middle = baseline - metrics.capHeight() / 2
        top = round(middle - MENU_ICON / 2)
        mark = QRect(spot.right() + 1 + MENU_GAP, top, MENU_ICON, MENU_ICON)
        color = option.palette.color(QPalette.ColorRole.ButtonText)
        tabler_icon("chevron-down", color, MENU_ICON).paint(painter, mark)


class CopyValue(QLabel):
    copied = Signal(str)

    def __init__(self, text: str, shown: str | None = None) -> None:
        super().__init__(shown if shown is not None else breakable(text))
        self._text = text
        self.setObjectName("copyValue")
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(_("Click to copy"))

    def copy_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        self.setText(breakable(text))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            QGuiApplication.clipboard().setText(self._text)
            self.copied.emit(self._text)
        super().mousePressEvent(event)


class DetailsPanel(QWidget):
    copied = Signal(str)
    customize_requested = Signal()
    customizable = False

    def __init__(self) -> None:
        super().__init__()
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        keyboard.tab_stop_while_it_scrolls(self._scroll)
        self._values: dict[str, list[CopyValue]] = {}
        self._shown: tuple[object, str] | None = None

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

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        raise NotImplementedError

    def selected_text(self, selected: int) -> str:
        raise NotImplementedError

    def pick_hint(self) -> str:
        raise NotImplementedError

    def item_id(self, shown: object) -> str:
        return ""

    def minimum_width(self) -> int:
        return 0

    def word_button(self, icon: str, color: QColor, word: str, tip: str, *,
                    risky: bool = False, menu: QMenu | None = None) -> QToolButton:  # fmt: skip
        button = QToolButton() if menu is None else MenuWordButton()
        button.setObjectName("commandButton")
        button.setProperty("risky", risky)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setText(word.replace("&", "&&"))
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(tabler_icon(icon, color, BUTTON_ICON))
        button.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
        if menu is not None:
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setProperty("arrow", False)
        return button

    def grid_width(self, words: Sequence[str], menu_words: Sequence[str] = ()) -> int:
        advance = self.fontMetrics().horizontalAdvance
        menus = [advance(word) + MENU_GAP + MENU_ICON for word in menu_words]
        return max([*map(advance, words), *menus]) + BUTTON_ROOM

    def grid_minimum(self, width: int) -> int:
        bar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        return COLUMNS * width + (COLUMNS - 1) * GAP + 2 * SIDE + bar + 4

    @staticmethod
    def button_rows(buttons: Sequence[QToolButton], width: int) -> QVBoxLayout:
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

    def hidden_line(self, layout: QVBoxLayout, hidden: int) -> None:
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
        if self._shown is not None:
            self._build(*self._shown)

    def show_item(
        self, shown: object | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
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
        if kept:
            QTimer.singleShot(0, self, lambda: bar.setValue(kept))

    def shown_value(self, key: str) -> str:
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
