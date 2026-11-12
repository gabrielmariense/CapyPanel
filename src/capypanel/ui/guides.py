"""First-run guides: a few small cards, each beside the real control it talks about, with a
soft outline on that control; step dots, Back, Next, Skip. Home's guide on the very first
start, each tool's the first time it's shown, never two at once; Help shows the one for the
screen you're on again, and Settings › About all of them. Each guide's last card links to its
docs page: nothing is said only in a guide.

While a guide runs the rest of the window is dimmed and takes no clicks or keys: only the
card's buttons, and the control a step asks you to click. A card whose control is out of sight
(a hidden panel, a narrow window) still shows, beside the part of the screen it belongs to."""

import contextlib
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
GAP = 12  # px between the outline and the card
MARGIN = 8  # px a card keeps from the window's edges
OUTLINE = 4  # px the outline sits outside its control
FOLLOW_MS = 250  # how often the card and the outline follow what moved under them
DIM = {"dark": 150, "light": 110}  # the shade's alpha over the rest of the window


Targets = QWidget | Sequence[QWidget] | None


@dataclass(frozen=True)
class Step:
    title: str
    text: str
    target: Callable[[], Targets]  # what it talks about, outlined; none shown: `near` instead
    near: Callable[[], QWidget | None] = lambda: None  # the part of the screen it belongs to
    action: tuple[str, Callable[[], None]] | None = None  # a button on the card: (words, does)
    click: bool = False  # the step asks you to click its target: only then it takes clicks
    join: bool = False  # several targets outlined as one box (a row of buttons)
    keep_clear: Callable[[], QWidget | None] = lambda: None  # what the card must not cover
    area: Callable[[], QRect | None] = lambda: None  # a box of its own, in the window's terms


@dataclass(frozen=True)
class Guide:
    guide_id: str  # "home", "hosts"…: kept in the settings once seen
    steps: Callable[[], Sequence[Step]]  # built when shown, in the language of the moment
    docs: str = ""  # its docs page, after the website's address: "hosts/host-lists/"
    mascot: bool = False  # the capybara on its first card: Home's only


GUIDES_KEY = "guides"  # the shell's settings: the ids of the guides seen
FIRST_STEPS = ("home", "hosts", "printers", "profiles")  # the guides that came with 0.26


def on_screen(window: QWidget) -> bool:
    """Whether a person can see `window`: never for tests (no screen) or screenshot scripts
    (drawn off screen), where a guide or a question would wait for nobody."""
    if QGuiApplication.platformName() == "offscreen":
        return False
    return window.isVisible() and not window.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)


def seen_from(prefs: dict[str, object]) -> list[str]:
    """The guides this person has seen, kept in `prefs`. Someone who used CapyPanel before
    guides existed (their window's place is saved) only sees guides that are new to them."""
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
    """Dims the window round the steps's controls and outlines them. It takes every click and
    wheel turn on the window, except on a control the step asks you to click."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.holes: list[QRect] = []  # the outlined controls, in the window's coordinates
        self.hide()

    def set_holes(self, holes: list[QRect], passes: bool) -> None:
        self.holes = holes
        if passes:  # those controls take clicks; the shade takes the rest
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
            return True  # eaten: nothing under the shade is clicked
        return super().event(event)


_POINTER = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick,
    QEvent.Type.Wheel,
    QEvent.Type.ContextMenu,
}


class GuideCard(QFrame):
    """One step: its title and words, an optional button, the step dots, Skip, Back and Next."""

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
        self.skip_button = QPushButton(_("Skip"))
        self.skip_button.setObjectName("quietDefault")
        self.back_button = QPushButton(_("Back"))
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
        head.addWidget(
            self.dots, 0, Qt.AlignmentFlag.AlignTop
        )  # where it is, out of the buttons' way
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
    """Shows one guide at a time over `window` and keeps which ones were seen."""

    finished = Signal(str)  # a guide's id, once done or skipped

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
        self._clickable: list[QWidget] = []  # the step's targets, when it asks for a click
        self.shade = _Shade(window)
        self.card = GuideCard(window)
        self.card.back.connect(lambda: self._go(self._at - 1))
        self.card.next.connect(self._next)
        self.card.skip.connect(self._end)
        self._follow = QTimer(self)  # a scrolled table, a panel that filled in: follow them
        self._follow.setInterval(FOLLOW_MS)
        self._follow.timeout.connect(self._place)
        window.installEventFilter(self)
        themes.switches().switched.connect(self._place)

    @property
    def running(self) -> str:
        """The guide on screen's id, or ""."""
        return self._guide.guide_id if self._guide is not None else ""

    def seen(self, guide_id: str) -> bool:
        return guide_id in self._seen

    def forget_all(self) -> None:
        """Every guide shows again, each when its screen is next shown."""
        self._seen.clear()
        self._save()

    def offer(self, guide: Guide | None) -> None:
        """Shows `guide` if it was never seen and nothing else is showing."""
        if guide is not None and not self._guide and guide.guide_id not in self._seen:
            self.show(guide)

    def show(self, guide: Guide) -> None:
        """Shows `guide` from its first step, seen or not (Help)."""
        steps = list(guide.steps())
        if not steps:
            return
        if self._guide is None:
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)  # keys and shortcuts, while it runs
            self._follow.start()
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
        card = self.card
        card.mascot.setVisible(guide.mascot and at == 0)
        card.title.setText(step.title)
        text = step.text
        if last and guide.docs:
            link = self._docs_url(guide.docs)
            text += f'<br><br><a href="{link}">{_("More in the documentation")}</a>'
        card.text.setText(text)
        card.action.setVisible(step.action is not None)
        if step.action is not None:
            words, does = step.action
            card.action.setText(words)
            with contextlib.suppress(RuntimeError, TypeError):  # nothing connected yet
                card.action.clicked.disconnect()
            card.action.clicked.connect(does)
        card.dots.setText(" ".join("●" if n == at else "○" for n in range(len(self._steps))))
        card.dots.setToolTip(_("Step {n} of {total}").format(n=at + 1, total=len(self._steps)))
        card.back_button.setVisible(at > 0)
        card.skip_button.setVisible(not last)
        card.next_button.setText(_("Done") if last else _("Next"))
        self._fit_card()
        self._place()
        self.shade.show()
        card.show()
        card.raise_()
        card.next_button.setFocus()

    def _fit_card(self) -> None:
        """As tall as its words wrapped at its width: the size hint alone left the last line
        of a wrapped text cut off."""
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
        """Hidden without counting as seen (its screen was left): it shows again next time."""
        self._close()

    def _close(self) -> None:
        self._guide, self._steps, self._clickable = None, [], []
        self._follow.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.card.hide()
        self.shade.hide()

    # ---- where the card goes ----

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
            spots.append(area)  # a menu's title, say: no widget of its own
        self._clickable = shown if step.click else []
        self.shade.setGeometry(window.rect())
        self.shade.set_holes(spots, passes=step.click)
        self.shade.raise_()
        near = step.near()
        if spots:
            spot = _united(spots)
        elif near is not None and _visible(near, window):
            spot = _rect_of(near, window)
        else:  # nothing to point at: the middle of the window
            spot = QRect(window.rect().center(), window.rect().center())
        avoid = [hole.adjusted(-OUTLINE, -OUTLINE, OUTLINE, OUTLINE) for hole in spots]
        clear = step.keep_clear()
        if clear is not None and _visible(clear, window):
            avoid.append(_rect_of(clear, window))
        size = self.card.size()
        self.card.move(_card_spot(spot, size.width(), size.height(), window.rect(), avoid))
        self.card.raise_()

    # ---- what the guide lets through ----

    def _inside(self, obj: QObject) -> bool:
        """Whether `obj` is the card, in it, or a control the step asks you to click."""
        if not isinstance(obj, QWidget):
            return False
        return any(w is obj or w.isAncestorOf(obj) for w in (self.card, *self._clickable))

    def _ours(self, obj: QObject) -> bool:
        """Whether `obj` is in the guided window, not a dialog a click on the step opened."""
        if isinstance(obj, QWidget):
            return obj.window() is self._window
        return True  # an action's shortcut: the window's menus and buttons

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if watched is self._window and kind in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
            return False
        if self._guide is None:
            return False
        blocked = self._ours(watched) and not self._inside(watched)
        if kind == QEvent.Type.Shortcut:  # Ctrl+, for Settings, a menu's letter…
            return blocked
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return blocked and isinstance(watched, QWidget)
        if kind == QEvent.Type.FocusIn and blocked and watched is not self.shade:
            QTimer.singleShot(0, self.card.next_button.setFocus)  # Tab left the card
        return False


def _united(spots: Sequence[QRect]) -> QRect:
    whole = QRect(spots[0])
    for spot in spots[1:]:
        whole = whole.united(spot)
    return whole


def _covered(card: QRect, avoid: Sequence[QRect]) -> int:
    """How much of `avoid` the card would hide, in square pixels."""
    return sum(card.intersected(a).width() * card.intersected(a).height() for a in avoid)


def _card_spot(
    spot: QRect, width: int, height: int, room: QRect, avoid: Sequence[QRect] = ()
) -> QPoint:
    """Where a card of this size goes beside `spot`: on its right, else under it, on its left,
    over it, then a corner of the window; always inside `room` and off everything in `avoid`
    (what it points at, a panel it talks about)."""
    gap = GAP + OUTLINE
    inner = room.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
    tries = (
        QPoint(spot.right() + gap, spot.top()),
        QPoint(spot.left(), spot.bottom() + gap),
        QPoint(spot.left() - gap - width, spot.top()),
        QPoint(spot.left(), spot.top() - gap - height),
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
    if inside and avoid:  # nowhere free: where it covers the least of what it mustn't
        return min(inside, key=lambda p: _covered(QRect(p.x(), p.y(), width, height), avoid))
    # Nowhere fits whole: as close as the window allows, over the spot if need be.
    x = min(max(tries[0].x(), inner.left()), inner.right() - width)
    y = min(max(spot.top(), inner.top()), inner.bottom() - height)
    return QPoint(max(x, inner.left()), max(y, inner.top()))
