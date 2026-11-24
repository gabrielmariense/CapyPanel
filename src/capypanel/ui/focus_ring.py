import contextlib
import math
from collections import Counter
from collections.abc import Callable
from enum import Enum

import shiboken6
from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    SignalInstance,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFocusEvent,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QTextDocument,
    QTextLine,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QRadioButton,
    QStyle,
    QStyleOptionButton,
    QTabBar,
    QTextEdit,
    QToolBar,
    QTreeView,
    QWidget,
)

from capypanel.ui.themes import engine

GAP = 2  # px between a control's edge and its ring
LINE = 2
OUT = GAP + LINE / 2  # the ring's middle, from the control's edge
CONTRAST = 3.0  # WCAG's least for a mark that isn't text
NAV_KEYS = frozenset({
    Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left,
    Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
})  # fmt: skip
BY_KEYBOARD = frozenset({
    Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
})  # fmt: skip
PRESSES = frozenset({QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick})
MOVES = frozenset({
    QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide,
    QEvent.Type.ParentChange,
})  # fmt: skip
INNER_FIELDS = frozenset({"tagInput"})


class Kind(Enum):
    ROW = "row"
    FIELD = "field"
    PRESS = "press"
    LINK = "link"
    TAB = "tab"
    BOX = "box"
    PANE = "pane"


ALWAYS = frozenset({Kind.FIELD, Kind.LINK})
INSIDE = frozenset({Kind.ROW, Kind.PANE})


class Ring(QWidget):
    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.paths: list[tuple[QRectF, float]] = []
        self.ink = QColor()
        self.rows: QAbstractItemView | None = None

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paths = self.paths if self.rows is None else row_paths(self.rows)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.ink, LINE))
        for rect, radius in paths:
            painter.drawRoundedRect(rect, radius, radius)


class FocusRing(QObject):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.by_keyboard = False
        self._keyed = False
        self.ring: Ring | None = None
        self._target: QWidget | None = None
        self._kind: Kind | None = None
        self._watched: list[QWidget] = []
        self._links: list[tuple[SignalInstance, Callable[..., object]]] = []
        self._fresh = True
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.place)
        engine.switches().switched.connect(self.restyle)

    def note(self, widget: QWidget, event: QEvent) -> None:
        kind = event.type()
        if kind in PRESSES:
            self.by_keyboard = self._keyed = False
        elif kind == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            self._keyed = True
            self.by_keyboard = self.by_keyboard or event.key() in NAV_KEYS
        elif kind == QEvent.Type.FocusIn and isinstance(event, QFocusEvent):
            # A dialog's first show sends a FocusIn marked Tab, with no key pressed.
            by_key = self._keyed and event.reason() in BY_KEYBOARD
            self.by_keyboard = self.by_keyboard or by_key
            # Qt's styles draw their own focus marks while this is set: the ring replaces them.
            widget.window().setAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange, False)
        self.later()

    def later(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def restyle(self) -> None:
        self._fresh = True
        self.later()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.Paint and self._kind is Kind.LINK and watched is self._target:
            return isinstance(watched, QLabel) and paint_without_box(watched)
        if kind in MOVES:
            self.later()
        return False

    def place(self) -> None:
        target, kind = _target(QApplication.focusWidget())
        if target is None or kind is None or not (self.by_keyboard or _always(target, kind)):
            self._hide()
            return
        if target is not self._target or kind is not self._kind:
            self._follow(target, kind)
        host = target if kind in INSIDE else _host(target)
        ring = self.ring
        if ring is None or not shiboken6.isValid(ring):
            ring = self.ring = Ring(host)
            self._fresh = True
        elif ring.parentWidget() is not host:
            ring.setParent(host)
            self._fresh = True
        if isinstance(target, QAbstractItemView) and kind is Kind.ROW:
            self._place_rows(ring, target)
        elif isinstance(target, QAbstractScrollArea) and kind is Kind.PANE:
            self._place_pane(ring, target)
        else:
            self._place_around(ring, target, kind, host)
        ring.show()
        ring.raise_()
        ring.update()

    def _place_rows(self, ring: Ring, view: QAbstractItemView) -> None:
        ring.rows, ring.paths = view, []
        ring.setGeometry(view.viewport().geometry())
        box = row_box(view)
        if self._fresh and not box.isEmpty():
            ring.ink = _ink(_pixel(view.viewport(), QPoint(box.left() + 1, box.center().y())))
            self._fresh = False

    def _place_pane(self, ring: Ring, pane: QAbstractScrollArea) -> None:
        viewport = pane.viewport()
        inner = QRectF(viewport.rect()).adjusted(OUT, OUT, -OUT, -OUT)
        ring.rows, ring.paths = None, [(inner, 0.0)]
        ring.setGeometry(viewport.geometry())
        if self._fresh:
            ring.ink = _ink(_surface(viewport, viewport.rect().adjusted(GAP, GAP, -GAP, -GAP)))
            self._fresh = False

    def _place_around(self, ring: Ring, target: QWidget, kind: Kind, host: QWidget) -> None:
        boxes = _boxes(target, kind, host)
        if not boxes:
            ring.hide()
            return
        paths = [(box.adjusted(-OUT, -OUT, OUT, OUT), radius + OUT) for box, radius in boxes]
        bounds = QRectF()
        for rect, _radius in paths:
            bounds = bounds.united(rect)
        area = bounds.toAlignedRect().adjusted(-LINE, -LINE, LINE, LINE)
        shift = QPointF(area.topLeft())
        ring.rows = None
        ring.setGeometry(area)
        ring.paths = [(rect.translated(-shift), radius) for rect, radius in paths]
        if self._fresh:
            ring.ink = _ink(_surface(host, boxes[0][0].toAlignedRect()))
            self._fresh = False

    def _follow(self, target: QWidget, kind: Kind) -> None:
        self._unfollow()
        self._target, self._kind, self._fresh = target, kind, True
        watched: list[QWidget] = [target]
        if isinstance(target, QAbstractScrollArea) and kind in INSIDE:
            watched.append(target.viewport())
        else:
            host, widget = _host(target), target.parentWidget()
            while widget is not None and widget is not host:
                watched.append(widget)
                widget = widget.parentWidget()
        if isinstance(target, QAbstractItemView):
            links: list[tuple[SignalInstance, Callable[..., object]]] = [
                (target.verticalScrollBar().valueChanged, self.later),
                (target.horizontalScrollBar().valueChanged, self.later),
            ]
            chosen = target.selectionModel()
            if chosen is not None:
                links += [(chosen.currentChanged, self._row_moved),
                          (chosen.selectionChanged, self._row_moved)]  # fmt: skip
            for signal, slot in links:
                signal.connect(slot)
            self._links = links
        for widget in watched:
            widget.installEventFilter(self)
        self._watched = watched
        if kind is Kind.LINK:
            target.update()

    def _row_moved(self, *_args: object) -> None:
        self._fresh = True
        self.later()

    def _unfollow(self) -> None:
        if self._kind is Kind.LINK and self._target is not None and shiboken6.isValid(self._target):
            self._target.update()
        for widget in self._watched:
            if shiboken6.isValid(widget):
                widget.removeEventFilter(self)
        for signal, slot in self._links:
            with contextlib.suppress(RuntimeError, TypeError):  # its object was deleted first
                signal.disconnect(slot)
        self._watched, self._links = [], []
        self._target = self._kind = None

    def _hide(self) -> None:
        self._unfollow()
        if self.ring is not None and shiboken6.isValid(self.ring):
            self.ring.hide()


def _target(focus: QWidget | None) -> tuple[QWidget | None, Kind | None]:
    if focus is None or focus.isWindow() or not focus.isVisible() or _in_menu(focus):
        return None, None
    if isinstance(focus, QAbstractItemView):
        return focus, Kind.ROW
    text_box = isinstance(focus, QPlainTextEdit | QTextEdit)
    if isinstance(focus, QAbstractScrollArea) and not text_box:
        return focus, Kind.PANE
    if isinstance(focus, QTabBar):
        return (focus, Kind.TAB) if focus.currentIndex() >= 0 else (None, None)
    if isinstance(focus, QLabel):
        return (focus, Kind.LINK) if focus.hasSelectedText() else (None, None)
    if isinstance(focus, QCheckBox | QRadioButton):
        return focus, Kind.BOX
    parent = focus.parentWidget()
    if parent is not None and (
        isinstance(parent, QAbstractSpinBox | QComboBox) or focus.objectName() in INNER_FIELDS
    ):
        return parent, Kind.FIELD
    if focus.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled):
        return focus, Kind.FIELD
    return focus, Kind.PRESS


def _always(target: QWidget, kind: Kind) -> bool:
    typed = target.testAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled)
    return kind in ALWAYS or (kind is Kind.PANE and typed)


def _in_menu(widget: QWidget) -> bool:
    if isinstance(widget, QMenu | QMenuBar):
        return True
    return widget.window().windowType() in (Qt.WindowType.Popup, Qt.WindowType.ToolTip)


def _host(target: QWidget) -> QWidget:
    """Qt clips a child to its parent: the ring sits in the scrolling area holding the control,
    clipped as the control is, or else in the window, so no tight parent cuts it off."""
    child, parent = target, target.parentWidget()
    while parent is not None and not child.isWindow():
        if isinstance(parent, QAbstractScrollArea) and parent.viewport() is child:
            return child
        child, parent = parent, parent.parentWidget()
    return target.window()


def _boxes(target: QWidget, kind: Kind, host: QWidget) -> list[tuple[QRectF, float]]:
    at = QPointF(target.mapTo(host, QPoint(0, 0)))
    if isinstance(target, QTabBar):
        tab = QRectF(target.tabRect(target.currentIndex()))
        return [(tab.translated(at), corner(target))]
    if isinstance(target, QCheckBox | QRadioButton):
        box, radius = _indicator(target)
        return [(box.translated(at), radius)]
    if isinstance(target, QLabel) and kind is Kind.LINK:
        return [(box.translated(at), 0.0) for box in link_boxes(target)]
    return [(QRectF(0, 0, target.width(), target.height()).translated(at), corner(target))]


def corner(widget: QWidget) -> float:
    theme = engine.current()
    name = widget.objectName()
    flat = _in_item_view(widget)
    if theme.engine == "native":
        if name == "homeTile":
            return 10.0
        toolbar = widget.parentWidget()
        on_toolbar = isinstance(toolbar, QToolBar) and toolbar.objectName() == "main"
        return 0.0 if flat or on_toolbar or name in ("commandButton", "paneSearch") else 4.0
    if name in ("homeTile", "paneSearch"):
        return float(theme.radius)
    return 0.0 if flat else float(theme.control)


def _in_item_view(widget: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractItemView):
            return True
        parent = parent.parentWidget()
    return False


def _indicator(button: QCheckBox | QRadioButton) -> tuple[QRectF, float]:
    option = QStyleOptionButton()
    option.initFrom(button)
    radio = isinstance(button, QRadioButton)
    element = (QStyle.SubElement.SE_RadioButtonIndicator if radio
               else QStyle.SubElement.SE_CheckBoxIndicator)  # fmt: skip
    box = QRectF(button.style().subElementRect(element, option, button))
    if radio:
        return box, box.width() / 2
    return box, 4.0 if engine.current().engine == "native" else 3.0


def row_box(view: QAbstractItemView) -> QRect:
    current = view.currentIndex()
    if not current.isValid():
        return QRect()
    cell = view.visualRect(current)
    if isinstance(view, QTreeView):
        header = view.header()
        cell = QRect(-header.offset(), cell.top(), header.length(), cell.height())
    return cell.intersected(view.viewport().rect())


def row_paths(view: QAbstractItemView) -> list[tuple[QRectF, float]]:
    box = row_box(view)
    if box.isEmpty():
        return []
    return [(QRectF(box).adjusted(OUT, OUT, -OUT, -OUT), 0.0)]


def paint_without_box(label: QLabel) -> bool:
    """Paints a label's text as Qt does, less the dotted box Qt draws around the link the
    keyboard is on (its style's focus mark, which no stylesheet turns off)."""
    doc = label.findChild(QTextDocument)
    if doc is None or label.frameShape() != QFrame.Shape.NoFrame:
        return False
    palette = QPalette(label.palette())
    role = label.foregroundRole()
    if role != QPalette.ColorRole.Text and label.isEnabled():
        palette.setColor(QPalette.ColorRole.Text, palette.color(role))
    context = QAbstractTextDocumentLayout.PaintContext()
    context.palette = palette
    text = _text_area(label, doc)
    painter = QPainter(label)
    painter.translate(text.topLeft())
    painter.setClipRect(QRect(QPoint(0, 0), text.size()))
    doc.documentLayout().draw(painter, context)
    painter.end()
    return True


def link_boxes(label: QLabel) -> list[QRectF]:
    doc = label.findChild(QTextDocument)
    start = label.selectionStart()
    if doc is None or start < 0:
        return []
    end = start + len(label.selectedText())
    origin = QPointF(_text_area(label, doc).topLeft())
    boxes: list[QRectF] = []
    block = doc.begin()
    while block.isValid():
        layout = block.layout()
        at = doc.documentLayout().blockBoundingRect(block).topLeft() + origin
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            first = block.position() + line.textStart()
            last = first + line.textLength()
            low, high = max(first, start), min(last, end)
            if low >= high:
                continue
            natural = line.naturalTextRect().translated(at)
            natural.setBottom(math.ceil(natural.bottom()))
            if start <= first and end >= last:
                boxes.append(natural)
                continue
            left = _x(line, low - block.position()) + at.x()
            right = _x(line, high - block.position()) + at.x()
            box = QRectF(left, natural.top(), right - left, line.height())
            boxes.append(QRectF(box.intersected(natural).toAlignedRect()))
        block = block.next()
    return boxes


def _x(line: QTextLine, position: int) -> float:
    found = line.cursorToX(position)
    if isinstance(found, tuple):
        found = found[0]
    assert isinstance(found, float | int)
    return float(found)


def _text_area(label: QLabel, doc: QTextDocument) -> QRect:
    area = label.contentsRect()
    margin = label.margin()
    area.adjust(margin, margin, -margin, -margin)
    align = label.alignment()
    indent = label.indent()
    if indent < 0 and label.frameWidth():
        indent = label.fontMetrics().horizontalAdvance("x") // 2 - margin
    if indent > 0:
        if align & Qt.AlignmentFlag.AlignLeft:
            area.setLeft(area.left() + indent)
        if align & Qt.AlignmentFlag.AlignRight:
            area.setRight(area.right() - indent)
        if align & Qt.AlignmentFlag.AlignTop:
            area.setTop(area.top() + indent)
        if align & Qt.AlignmentFlag.AlignBottom:
            area.setBottom(area.bottom() - indent)
    height = doc.documentLayout().documentSize().height()
    top = 0.0
    if align & Qt.AlignmentFlag.AlignVCenter:
        top = max((area.height() - height) / 2, 0.0)
    elif align & Qt.AlignmentFlag.AlignBottom:
        top = max(area.height() - height, 0.0)
    return QRectF(area.x(), area.y() + top, area.width(), area.height()).toAlignedRect()


def _surface(host: QWidget, box: QRect) -> QColor:
    middle = box.center()
    spots = [QPoint(middle.x(), box.top() - 1), QPoint(middle.x(), box.bottom() + 1),
             QPoint(box.left() - 1, middle.y()), QPoint(box.right() + 1, middle.y())]  # fmt: skip
    around = box.adjusted(-1, -1, 1, 1).intersected(host.rect())
    if around.isEmpty():
        return host.palette().color(QPalette.ColorRole.Window)
    image = host.grab(around).toImage()
    ratio = image.devicePixelRatio()
    seen: Counter[int] = Counter()
    for spot in spots:
        x, y = (spot - around.topLeft()).x() * ratio, (spot - around.topLeft()).y() * ratio
        if 0 <= x < image.width() and 0 <= y < image.height():
            color = image.pixelColor(int(x), int(y))
            if color.alpha():
                seen[color.rgb()] += 1
    if not seen:
        return host.palette().color(QPalette.ColorRole.Window)
    return QColor.fromRgb(seen.most_common(1)[0][0])


def _pixel(widget: QWidget, spot: QPoint) -> QColor:
    image = widget.grab(QRect(spot, QSize(1, 1))).toImage()
    if image.isNull():
        return widget.palette().color(QPalette.ColorRole.Base)
    return image.pixelColor(0, 0)


def _ink(surface: QColor) -> QColor:
    accent, text = engine.ring_inks()
    readable = engine.contrast_ratio(accent.name(), surface.name()) >= CONTRAST
    return accent if readable else text
