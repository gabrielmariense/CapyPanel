"""First-run guides: a few small cards, each beside the real control it talks about, with a
soft outline on that control; step dots, Back, Next, Skip. Home's guide on the very first
start, each tool's the first time it's shown, never two at once; Help shows the one for the
screen you're on again, and Settings › About all of them. Each guide's last card links to its
docs page: nothing is said only in a guide.

A card whose control is out of sight (a hidden panel, a narrow window) still shows, beside the
part of the screen it belongs to."""

import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
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


@dataclass(frozen=True)
class Step:
    title: str
    text: str
    target: Callable[[], QWidget | None]  # the control; None or hidden: `near` instead
    near: Callable[[], QWidget | None] = lambda: None  # the part of the screen it belongs to
    action: tuple[str, Callable[[], None]] | None = None  # a button on the card: (words, does)


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


class _Outline(QWidget):
    """The soft outline round the control a card talks about; clicks go through it."""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.palette().color(QPalette.ColorRole.Accent))
        painter.setPen(QPen(color, 2))
        corner = themes.current().radius + 2
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), corner, corner)


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
        self.outline = _Outline(window)
        self.card = GuideCard(window)
        self.card.back.connect(lambda: self._go(self._at - 1))
        self.card.next.connect(self._next)
        self.card.skip.connect(self._end)
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
        card.adjustSize()
        self._place()
        card.show()
        card.raise_()
        card.next_button.setFocus()

    def _end(self) -> None:
        guide = self._guide
        self._guide, self._steps = None, []
        self.card.hide()
        self.outline.hide()
        if guide is not None:
            if guide.guide_id not in self._seen:
                self._seen.append(guide.guide_id)
                self._save()
            self.finished.emit(guide.guide_id)

    def stop(self) -> None:
        """Hidden without counting as seen (its screen was left): it shows again next time."""
        self._guide, self._steps = None, []
        self.card.hide()
        self.outline.hide()

    # ---- where the card goes ----

    def _place(self) -> None:
        if self._guide is None or not self._steps:
            return
        window, step = self._window, self._steps[self._at]
        target = step.target()
        if not _visible(target, window):
            target, outlined = step.near(), False
        else:
            outlined = True
        if _visible(target, window):
            assert target is not None
            spot = QRect(target.mapTo(window, QPoint(0, 0)), target.size())
        else:  # nothing to point at: the middle of the window
            spot, outlined = QRect(window.rect().center(), window.rect().center()), False
        self.outline.setVisible(outlined)
        if outlined:
            self.outline.setGeometry(spot.adjusted(-OUTLINE, -OUTLINE, OUTLINE, OUTLINE))
            self.outline.raise_()
        self.card.move(_card_spot(spot, self.card.size().width(), self.card.sizeHint().height(),
                                  window.rect()))  # fmt: skip
        self.card.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._place()
        return False


def _card_spot(spot: QRect, width: int, height: int, room: QRect) -> QPoint:
    """Where a card of this size goes beside `spot`: on its right, else under it, on its left,
    over it; always inside `room`."""
    gap = GAP + OUTLINE
    tries = (
        QPoint(spot.right() + gap, spot.top()),
        QPoint(spot.left(), spot.bottom() + gap),
        QPoint(spot.left() - gap - width, spot.top()),
        QPoint(spot.left(), spot.top() - gap - height),
    )
    inner = room.adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
    for point in tries:
        if inner.contains(QRect(point.x(), point.y(), width, height)):
            return point
    # Nowhere fits whole: as close as the window allows, over the spot if need be.
    x = min(max(tries[0].x(), inner.left()), inner.right() - width)
    y = min(max(spot.top(), inner.top()), inner.bottom() - height)
    return QPoint(max(x, inner.left()), max(y, inner.top()))
