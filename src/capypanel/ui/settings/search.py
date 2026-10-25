"""The Settings search: which sections mention what's typed, at the start of a word, and marks on
every match, in the host table search's see-through yellow."""

import html
import re

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QPainter, QPaintEvent, QTextDocumentFragment
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QLabel,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionHeader,
    QTreeWidget,
    QWidget,
)

from capypanel.ui.list_workspace.panels import MatchMarker

MARK = MatchMarker.COLOR


def spans(text: str, needle: str) -> list[tuple[int, int]]:
    """Where `needle` starts a word in `text`, ignoring case: "tem" finds "Theme"'s "Tema", not
    the "tem" inside "System32"."""
    if not needle:
        return []
    found = re.finditer(r"(?<!\w)" + re.escape(needle), text, re.IGNORECASE)
    return [(m.start(), m.end()) for m in found]


def shown(text: str) -> str:
    """A button's text as shown: "&Save" reads "Save", "&&" reads "&"."""
    return re.sub(r"&(.)", r"\1", text)


def own_texts(widget: QWidget) -> list[str]:
    """What one widget says: a label's or button's text, a dropdown's items, a table's headers.
    Not a table's rows: those are data, like a tool's path, not settings."""
    if isinstance(widget, QLabel):
        return [visible_text(widget)]
    if isinstance(widget, QAbstractButton):
        return [shown(widget.text())]
    if isinstance(widget, QComboBox):
        return [widget.itemText(i) for i in range(widget.count())]
    if isinstance(widget, QTreeWidget):
        header = widget.headerItem()
        return [header.text(c) for c in range(header.columnCount())]
    return []


def mentions(widget: QWidget, needle: str) -> bool:
    """Whether a widget or anything in it says `needle`."""
    return any(
        spans(text, needle)
        for part in (widget, *widget.findChildren(QWidget))
        for text in own_texts(part)
    )


class SearchMarks(QWidget):
    """Over the results page: labels get their matching words marked in their text; buttons,
    ticks, dropdowns and table headers get a mark painted over the words. A dropdown whose
    match is in its list, not the item shown, gets the mark on its arrow."""

    def __init__(self, page: QWidget) -> None:
        super().__init__(page)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._needle = ""
        self._labels: list[tuple[QLabel, str, Qt.TextFormat]] = []
        self._controls: list[QWidget] = []
        page.installEventFilter(self)
        self.hide()

    def mark(self, widgets: list[QWidget], needle: str) -> None:
        self.clear()
        self._needle = needle
        for root in widgets:
            labels = [root] if isinstance(root, QLabel) else root.findChildren(QLabel)
            for label in labels:
                if type(label) is QLabel and spans(visible_text(label), needle):  # not custom
                    self._labels.append((label, label.text(), label.textFormat()))
                    marked = (
                        _marked_rich(label.text(), needle)
                        if _is_rich(label)
                        else _marked_html(label.text(), needle)
                    )
                    label.setTextFormat(Qt.TextFormat.RichText)
                    label.setText(marked)
            for control in root.findChildren(QWidget):
                if isinstance(control, (QAbstractButton, QComboBox, QTreeWidget)) and any(
                    spans(text, needle) for text in own_texts(control)
                ):
                    self._controls.append(control)
                    control.installEventFilter(self)  # repainted as it moves or changes
        page = self.parentWidget()
        if page is not None:
            self.resize(page.size())
        self.raise_()
        self.show()

    def clear(self) -> None:
        for label, text, text_format in self._labels:
            label.setTextFormat(text_format)
            label.setText(text)
        for control in self._controls:
            control.removeEventFilter(self)
        self._labels.clear()
        self._controls.clear()
        self.hide()

    def marked_labels(self) -> list[QLabel]:
        return [label for label, _text, _format in self._labels]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.resize(self.parentWidget().size())  # type: ignore[union-attr]
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show,
                            QEvent.Type.Hide, QEvent.Type.LayoutRequest):  # fmt: skip
            self.update()
        return False

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        for control in self._controls:
            if not control.isVisible():
                continue
            for widget, rect in _marks(control, self._needle):
                painter.fillRect(rect.translated(widget.mapTo(self.parentWidget(), QPoint())), MARK)  # type: ignore[arg-type]
        painter.end()


_TAG = re.compile(r"<[A-Za-z/]")  # rich text, as Qt guesses it: it has a tag


def _is_rich(label: QLabel) -> bool:
    text_format = label.textFormat()
    return text_format == Qt.TextFormat.RichText or (
        text_format == Qt.TextFormat.AutoText and _TAG.search(label.text()) is not None
    )


def visible_text(label: QLabel) -> str:
    """What a label shows: a link's words, not its address or tags."""
    if not _is_rich(label):
        return label.text()
    return QTextDocumentFragment.fromHtml(label.text()).toPlainText()


_MARK_STYLE = (
    f"background-color: rgba({MARK.red()}, {MARK.green()}, {MARK.blue()}, {MARK.alphaF():.2f})"
)


def _marked_html(text: str, needle: str) -> str:
    """Plain text, its matches marked, as rich text."""
    parts, last = [], 0
    for start, end in spans(text, needle):
        parts += [html.escape(text[last:start]), f'<span style="{_MARK_STYLE}">']
        parts += [html.escape(text[start:end]), "</span>"]
        last = end
    parts.append(html.escape(text[last:]))
    return "".join(parts).replace("\n", "<br>")


def _marked_rich(text: str, needle: str) -> str:
    """Rich text (a link, say), its matches marked only in what it shows: tags and the
    addresses inside them stay as they are."""
    marked = []
    for part in re.split(r"(<[^>]*>)", text):
        if part.startswith("<"):
            marked.append(part)
            continue
        last = 0
        for start, end in spans(part, needle):
            marked += [
                part[last:start],
                f'<span style="{_MARK_STYLE}">',
                part[start:end],
                "</span>",
            ]
            last = end
        marked.append(part[last:])
    return "".join(marked)


def _word_rects(text: str, needle: str, left: int, area: QRect, widget: QWidget) -> list[QRect]:
    """The matches in a line of `text` drawn from `left`, centred in `area`'s height."""
    metrics = widget.fontMetrics()
    height = metrics.height()
    top = area.top() + (area.height() - height) // 2
    return [
        QRect(left + metrics.horizontalAdvance(text[:start]), top,
              metrics.horizontalAdvance(text[start:end]), height)
        for start, end in spans(text, needle)
    ]  # fmt: skip


def _marks(control: QWidget, needle: str) -> list[tuple[QWidget, QRect]]:
    """Each mark on a control, in the coordinates of the widget it's drawn on."""
    style = control.style()
    if isinstance(control, (QCheckBox, QRadioButton)):
        option = QStyleOptionButton()
        control.initStyleOption(option)
        element = (
            QStyle.SubElement.SE_CheckBoxContents
            if isinstance(control, QCheckBox)
            else QStyle.SubElement.SE_RadioButtonContents
        )
        area = style.subElementRect(element, option, control)
        text = shown(control.text())
        return [(control, r) for r in _word_rects(text, needle, area.left(), area, control)]
    if isinstance(control, QAbstractButton):  # a push button: its text is centred
        text = shown(control.text())
        left = (control.width() - control.fontMetrics().horizontalAdvance(text)) // 2
        return [(control, r) for r in _word_rects(text, needle, left, control.rect(), control)]
    if isinstance(control, QComboBox):
        option = QStyleOptionComboBox()
        control.initStyleOption(option)
        complex_ = QStyle.ComplexControl.CC_ComboBox
        edit = style.subControlRect(
            complex_, option, QStyle.SubControl.SC_ComboBoxEditField, control
        )
        shown_marks = _word_rects(control.currentText(), needle, edit.left() + 1, edit, control)
        if shown_marks:
            return [(control, r) for r in shown_marks]
        if any(spans(control.itemText(i), needle) for i in range(control.count())):
            arrow = style.subControlRect(
                complex_, option, QStyle.SubControl.SC_ComboBoxArrow, control
            )
            return [(control, arrow)]
        return []
    if isinstance(control, QTreeWidget):
        header, item = control.header(), control.headerItem()
        marks: list[tuple[QWidget, QRect]] = []
        for column in range(item.columnCount()):
            if header.isSectionHidden(column):
                continue
            section = QRect(header.sectionViewportPosition(column), 0,
                            header.sectionSize(column), header.height())  # fmt: skip
            option = QStyleOptionHeader()
            option.initFrom(header)
            option.rect, option.section, option.text = section, column, item.text(column)
            area = style.subElementRect(QStyle.SubElement.SE_HeaderLabel, option, header)
            for rect in _word_rects(item.text(column), needle, area.left(), area, header):
                marks.append((header, rect))
        return marks
    return []
