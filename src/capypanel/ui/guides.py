from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui import branding, spacing
from capypanel.ui.themes import engine as themes

CARD_WIDTH = 360
GAP = 12
MARGIN = 8
OUTLINE = 4
DIM = {"dark": 150, "light": 110}  # the shade's alpha


Targets = QWidget | Sequence[QWidget] | None


@dataclass(frozen=True)
class Step:
    title: str
    text: str
    target: Callable[[], Targets]
    near: Callable[[], QWidget | None] = lambda: None
    action: tuple[str, Callable[[], None]] | None = None
    click: bool = False
    join: bool = False
    keep_clear: Callable[[], QWidget | None] = lambda: None
    area: Callable[[], QRect | None] = lambda: None
    enter: Callable[[], None] = lambda: None


@dataclass(frozen=True)
class Guide:
    guide_id: str
    steps: Callable[[], Sequence[Step]]
    docs: str = ""
    mascot: bool = False
    setup: Callable[[], None] = lambda: None
    cleanup: Callable[[], None] = lambda: None


GUIDES_KEY = "guides"
FIRST_STEPS = ("home", "hosts", "printers", "profiles")  # the guides that came with 0.26


def on_screen(window: QWidget) -> bool:
    """Never off screen (tests, screenshot scripts): a guide there would wait for nobody."""
    if QGuiApplication.platformName() == "offscreen":
        return False
    return window.isVisible() and not window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)


def seen_from(prefs: dict[str, object]) -> list[str]:
    """Someone who used CapyPanel before guides (a window place saved) sees only the newer ones."""
    seen = prefs.get(GUIDES_KEY)
    if not isinstance(seen, list):
        seen = list(FIRST_STEPS) if "window_geometry" in prefs else []
        prefs[GUIDES_KEY] = seen
    return seen  # type: ignore[return-value]


def _visible(widget: QWidget | None, window: QWidget) -> bool:
    return widget is not None and widget.isVisibleTo(window) and widget.width() > 0


def _rect_of(widget: QWidget, window: QWidget) -> QRect:
    return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())


def _shown(targets: Targets, window: QWidget) -> list[QWidget]:
    if targets is None:
        return []
    many = [targets] if isinstance(targets, QWidget) else list(targets)
    return [widget for widget in many if _visible(widget, window)]


class _Shade(QWidget):
    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.holes: list[QRect] = []
        self.hide()

    def set_holes(self, holes: list[QRect], passes: bool) -> None:
        self.holes = holes
        if passes:
            region = QRegion(self.rect())
            for hole in holes:
                region -= QRegion(hole)
            self.setMask(region)
        else:
            self.clearMask()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        corner = themes.current().radius + 2
        cut = QPainterPath()
        for hole in self.holes:
            cut.addRoundedRect(hole.adjusted(-OUTLINE, -OUTLINE, OUTLINE, OUTLINE), corner, corner)
        dim = QPainterPath()
        dim.addRect(self.rect())
        light = self.palette().color(QPalette.ColorRole.Window).lightness() >= 128
        painter.fillPath(dim.subtracted(cut), QColor(0, 0, 0, DIM["light" if light else "dark"]))
        painter.setPen(QPen(QColor(self.palette().color(QPalette.ColorRole.Accent)), 2))
        for hole in self.holes:
            painter.drawRoundedRect(hole.adjusted(-OUTLINE + 1, -OUTLINE + 1, OUTLINE - 1,
                                                  OUTLINE - 1), corner, corner)  # fmt: skip

    def event(self, event: QEvent) -> bool:
        if event.type() in _POINTER:
            event.accept()
            return True
        return super().event(event)


_POINTER = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.Wheel,
    QEvent.Type.ContextMenu,
}


class GuideCard(QFrame):
    back = Signal()
    next = Signal()
    skip = Signal()

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setObjectName("guideCard")
        self.setFixedWidth(CARD_WIDTH)
        self.mascot = QLabel()
        self.mascot.setPixmap(branding.app_icon().pixmap(40, 40))
        self.title = QLabel()
        self.title.setObjectName("sectionTitle")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.text.setOpenExternalLinks(True)
        self.action = QPushButton()
        self.action.setAutoDefault(False)
        self.dots = QLabel()
        self.dots.setObjectName("hint")
        self.skip_button = QPushButton()
        self.skip_button.setObjectName("quietDefault")
        self.back_button = QPushButton()
        self.next_button = QPushButton()
        for button in (self.skip_button, self.back_button, self.next_button):
            button.setAutoDefault(False)
        self.next_button.setDefault(True)
        self.skip_button.clicked.connect(self.skip)
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.next)
        head = QHBoxLayout()
        head.setSpacing(spacing.CONTROLS)
        head.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignTop)
        head.addWidget(self.title, 1)
        head.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignTop)
        foot = QHBoxLayout()
        foot.setSpacing(spacing.CONTROLS)
        foot.addWidget(self.skip_button)
        foot.addStretch(1)
        foot.addWidget(self.back_button)
        foot.addWidget(self.next_button)
        column = QVBoxLayout(self)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(spacing.CONTROLS)
        column.addLayout(head)
        column.addWidget(self.text)
        column.addWidget(self.action, 0, Qt.AlignmentFlag.AlignLeft)
        column.addLayout(foot)
        self.hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.skip.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next.emit()
            return
        super().keyPressEvent(event)


class GuideRunner(QObject):
    finished = Signal(str)

    def __init__(
        self,
        window: QWidget,
        seen: list[str],
        save: Callable[[], None],
        docs_url: Callable[[str], str],
    ) -> None:
        super().__init__(window)
        self._window, self._seen, self._save, self._docs_url = window, seen, save, docs_url
        self._guide: Guide | None = None
        self._steps: list[Step] = []
        self._at = 0
        self._clickable: list[QWidget] = []
        self.shade = _Shade(window)
        self.card = GuideCard(window)
        self.card.back.connect(lambda: self._go(self._at - 1))
        self.card.next.connect(self._next)
        self.card.skip.connect(self._end)
        self._action: Callable[[], None] | None = None
        self.card.action.clicked.connect(lambda: self._action() if self._action else None)
        window.installEventFilter(self)
        themes.switches().switched.connect(self._place)

    @property
    def running(self) -> str:
        return self._guide.guide_id if self._guide is not None else ""

    def seen(self, guide_id: str) -> bool:
        return guide_id in self._seen

    def forget_all(self) -> None:
        self._seen.clear()
        self._save()

    def offer(self, guide: Guide | None) -> None:
        if guide is not None and not self._guide and guide.guide_id not in self._seen:
            self.show(guide)

    def show(self, guide: Guide) -> None:
        if self._guide is not None:
            self._guide.cleanup()
        guide.setup()
        steps = list(guide.steps())
        if not steps:
            guide.cleanup()
            if self._guide is not None:
                self._close()
            return
        if self._guide is None:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
        self._guide, self._steps = guide, steps
        self._go(0)

    def _next(self) -> None:
        if self._at + 1 < len(self._steps):
            self._go(self._at + 1)
        else:
            self._end()

    def _go(self, at: int) -> None:
        guide = self._guide
        if guide is None or not 0 <= at < len(self._steps):
            return
        self._at = at
        step, last = self._steps[at], at == len(self._steps) - 1
        step.enter()
        card = self.card
        card.mascot.setVisible(guide.mascot and at == 0)
        card.title.setText(step.title)
        text = step.text
        if last and guide.docs:
            link = self._docs_url(guide.docs)
            text += f'<br><br><a href="{link}">{_("More in the documentation")}</a>'
        card.text.setText(text)
        card.action.setVisible(step.action is not None)
        self._action = step.action[1] if step.action is not None else None
        if step.action is not None:
            card.action.setText(step.action[0])
        card.dots.setText(" ".join("●" if n == at else "○" for n in range(len(self._steps))))
        card.dots.setToolTip(_("Step {n} of {total}").format(n=at + 1, total=len(self._steps)))
        card.back_button.setText(_("Back"))
        card.back_button.setVisible(at > 0)
        card.skip_button.setText(_("Skip"))
        card.skip_button.setVisible(not last)
        card.next_button.setText(_("Done") if last else _("Next"))
        self._fit_card()
        self._place()
        self.shade.show()
        card.show()
        card.raise_()
        card.next_button.setFocus()
        QTimer.singleShot(0, self, self._place)

    def _fit_card(self) -> None:
        card, layout = self.card, self.card.layout()
        if layout is not None:
            layout.activate()
            card.setFixedHeight(layout.totalHeightForWidth(CARD_WIDTH))

    def _end(self) -> None:
        guide = self._guide
        self._close()
        if guide is not None:
            if guide.guide_id not in self._seen:
                self._seen.append(guide.guide_id)
                self._save()
            self.finished.emit(guide.guide_id)

    def stop(self) -> None:
        self._close()

    def _close(self) -> None:
        guide = self._guide
        self._guide, self._steps, self._clickable = None, [], []
        if guide is not None:
            guide.cleanup()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.card.hide()
        self.shade.hide()

    def _place(self) -> None:
        if self._guide is None or not self._steps:
            return
        window, step = self._window, self._steps[self._at]
        shown = _shown(step.target(), window)
        spots = [_rect_of(widget, window) for widget in shown]
        if spots and step.join:
            spots = [_united(spots)]
        area = step.area()
        if area is not None and area.isValid():
            spots.append(area)
        self._clickable = shown if step.click else []
        if self.shade.geometry() != window.rect():
            self.shade.setGeometry(window.rect())
        if spots != self.shade.holes or self.shade.mask().isEmpty() == step.click:
            self.shade.set_holes(spots, passes=step.click)
        near = step.near()
        if spots:
            spot = _united(spots)
        elif near is not None and _visible(near, window):
            spot = _rect_of(near, window)
        else:
            spot = QRect(window.rect().center(), window.rect().center())
        avoid = [hole.adjusted(-OUTLINE, -OUTLINE, OUTLINE, OUTLINE) for hole in spots]
        clear = step.keep_clear()
        if clear is not None and _visible(clear, window):
            avoid.append(_rect_of(clear, window))
        size = self.card.size()
        if not spots and (near is None or not _visible(near, window)):
            where = window.rect().center() - QPoint(size.width() // 2, size.height() // 2)
        else:
            parts = spots if len(spots) > 1 else []
            where = _card_spot(spot, size.width(), size.height(), window.rect(), avoid, parts)
        if self.card.pos() != where:
            self.card.move(where)
        self._on_top()

    def _on_top(self) -> None:
        siblings = [w for w in self._window.children() if isinstance(w, QWidget) and
                    w.isVisible()]  # fmt: skip
        if siblings[-2:] != [self.shade, self.card]:
            self.shade.raise_()
            self.card.raise_()

    def _inside(self, obj: QObject) -> bool:
        if not isinstance(obj, QWidget):
            return False
        return any(w is obj or w.isAncestorOf(obj) for w in (self.card, *self._clickable))

    def _ours(self, obj: QObject) -> bool:
        if isinstance(obj, QWidget):
            return obj.window() is self._window
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if watched is self._window and kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
            return False
        if self._guide is None:
            return False
        blocked = self._ours(watched) and not self._inside(watched)
        if kind == QEvent.Type.Shortcut:
            return blocked
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return blocked and isinstance(watched, QWidget)
        if kind == QEvent.Type.FocusIn and self._left_the_card(watched):
            QTimer.singleShot(0, self.card.next_button.setFocus)
        return False

    def _left_the_card(self, watched: QObject) -> bool:
        """Not while a mouse button is down: a pressed button losing the focus loses its click."""
        return (
            isinstance(watched, QWidget)
            and watched is not self.shade
            and watched is not self._window
            and QApplication.mouseButtons() == Qt.MouseButton.NoButton
            and self._ours(watched)
            and not self._inside(watched)
        )


def _united(spots: Sequence[QRect]) -> QRect:
    whole = QRect(spots[0])
    for spot in spots[1:]:
        whole = whole.united(spot)
    return whole


def _covered(card: QRect, avoid: Sequence[QRect]) -> int:
    return sum(card.intersected(a).width() * card.intersected(a).height() for a in avoid)


def _card_spot(
    spot: QRect,
    width: int,
    height: int,
    room: QRect,
    avoid: Sequence[QRect] = (),
    parts: Sequence[QRect] = (),
) -> QPoint:
    gap = GAP + OUTLINE
    inner = room.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def beside(box: QRect) -> list[QPoint]:
        return [
            QPoint(box.right() + gap, box.top()),
            QPoint(box.left(), box.bottom() + gap),
            QPoint(box.left() - gap - width, box.top()),
            QPoint(box.left(), box.top() - gap - height),
        ]

    tries = (
        *(point for part in parts for point in beside(part)),
        *beside(spot),
        QPoint(inner.right() - width, inner.bottom() - height),
        QPoint(inner.left(), inner.bottom() - height),
        QPoint(inner.right() - width, inner.top()),
        QPoint(inner.left(), inner.top()),
    )
    inside = [p for p in tries if inner.contains(QRect(p.x(), p.y(), width, height))]
    for point in inside:
        card = QRect(point.x(), point.y(), width, height)
        if not any(card.intersects(a) for a in avoid):
            return point
    if inside and avoid:
        return min(inside, key=lambda p: _covered(QRect(p.x(), p.y(), width, height), avoid))
    x = min(max(tries[0].x(), inner.left()), inner.right() - width)
    y = min(max(spot.top(), inner.top()), inner.bottom() - height)
    return QPoint(max(x, inner.left()), max(y, inner.top()))
