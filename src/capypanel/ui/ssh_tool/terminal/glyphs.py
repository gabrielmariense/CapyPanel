"""Drawn by our code, so they join across cells in any font."""

import unicodedata
from functools import cache
from typing import Literal

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

L, R, U, D = "left", "right", "up", "down"
WEIGHTS = {"LIGHT": 1, "SINGLE": 1, "HEAVY": 2, "DOUBLE": 3}
DIRS = {
    "LEFT": (L,),
    "RIGHT": (R,),
    "UP": (U,),
    "DOWN": (D,),
    "HORIZONTAL": (L, R),
    "VERTICAL": (U, D),
}
DASHES = {"DOUBLE": 2, "TRIPLE": 3, "QUADRUPLE": 4}

BLOCKS: dict[int, tuple[tuple[int, int, int, int], ...] | float] = {
    0x2580: ((0, 0, 8, 4),), 0x2581: ((0, 7, 8, 8),), 0x2582: ((0, 6, 8, 8),),
    0x2583: ((0, 5, 8, 8),), 0x2584: ((0, 4, 8, 8),), 0x2585: ((0, 3, 8, 8),),
    0x2586: ((0, 2, 8, 8),), 0x2587: ((0, 1, 8, 8),), 0x2588: ((0, 0, 8, 8),),
    0x2589: ((0, 0, 7, 8),), 0x258A: ((0, 0, 6, 8),), 0x258B: ((0, 0, 5, 8),),
    0x258C: ((0, 0, 4, 8),), 0x258D: ((0, 0, 3, 8),), 0x258E: ((0, 0, 2, 8),),
    0x258F: ((0, 0, 1, 8),), 0x2590: ((4, 0, 8, 8),), 0x2591: 0.25, 0x2592: 0.5, 0x2593: 0.75,
    0x2594: ((0, 0, 8, 1),), 0x2595: ((7, 0, 8, 8),), 0x2596: ((0, 4, 4, 8),),
    0x2597: ((4, 4, 8, 8),), 0x2598: ((0, 0, 4, 4),), 0x2599: ((0, 0, 4, 4), (0, 4, 8, 8)),
    0x259A: ((0, 0, 4, 4), (4, 4, 8, 8)), 0x259B: ((0, 0, 8, 4), (0, 4, 4, 8)),
    0x259C: ((0, 0, 8, 4), (4, 4, 8, 8)), 0x259D: ((4, 0, 8, 4),),
    0x259E: ((4, 0, 8, 4), (0, 4, 4, 8)), 0x259F: ((4, 0, 8, 4), (0, 4, 8, 8)),
}  # fmt: skip

Arms = dict[str, int]  # each arm of a line character and its weight: 1 light, 2 heavy, 3 double
Shape = (
    tuple[Literal["arms"], Arms]
    | tuple[Literal["dash"], tuple[int, int, bool]]
    | tuple[Literal["arc"], tuple[str, str]]
    | tuple[Literal["diagonal"], tuple[str, ...]]
)


def is_builtin(ch: str) -> bool:
    if len(ch) != 1:
        return False
    o = ord(ch)
    return 0x2500 <= o <= 0x259F or 0xE0A0 <= o <= 0xE0A3 or 0xE0B0 <= o <= 0xE0BF


@cache
def box_shape(ch: str) -> Shape:
    name = unicodedata.name(ch, "")
    assert name.startswith("BOX DRAWINGS "), name
    words = name.removeprefix("BOX DRAWINGS ").split()
    if "DASH" in words:
        return "dash", (WEIGHTS[words[0]], DASHES[words[1]], words[-1] == "HORIZONTAL")
    if "ARC" in words:
        ends = [DIRS[w][0] for w in words if w in DIRS]
        return "arc", (ends[0], ends[1])
    if "DIAGONAL" in words:
        if words[-1] == "CROSS":
            return "diagonal", ("\\", "/")
        return "diagonal", ("/",) if "UPPER RIGHT TO LOWER LEFT" in name else ("\\",)
    arms: Arms = {}
    parts = " ".join(words).split(" AND ")
    weights = [next((WEIGHTS[w] for w in p.split() if w in WEIGHTS), 0) for p in parts]
    for i, part in enumerate(parts):
        weight = (
            weights[i]
            or next((x for x in reversed(weights[:i]) if x), 0)
            or next((x for x in weights[i + 1 :] if x), 1)
        )
        for word in part.split():
            for d in DIRS.get(word, ()):
                arms[d] = weight
    return "arms", arms


class Metrics:
    def __init__(self, cw: int, ch: int) -> None:
        self.cw, self.ch = cw, ch
        self.light = max(1, round(ch / 16))
        self.heavy = self.light * 2
        self.cx = (cw - self.light) // 2
        self.cy = (ch - self.light) // 2
        self.double = max(
            self.light, min(2 * self.light, self.cx - self.light, cw - self.cx - 2 * self.light)
        )

    def line(self, w: int, horizontal: bool) -> tuple[int, int]:
        t = self.light if w == 1 else self.heavy
        mid = (self.cy if horizontal else self.cx) + self.light // 2
        return mid - t // 2, t


def _arms(p: QPainter, x: int, y: int, m: Metrics, arms: Arms, color: QColor) -> None:
    cw, ch, lw = m.cw, m.ch, m.light
    a = {k: arms.get(k, 0) for k in (L, R, U, D)}
    d = m.double
    xs = {-1: m.cx - d, 1: m.cx + d}
    ys = {-1: m.cy - d, 1: m.cy + d}
    v_lines = [m.line(a[k], False) for k in (U, D) if a[k] in (1, 2)]
    h_lines = [m.line(a[k], True) for k in (L, R) if a[k] in (1, 2)]
    v_lo, v_hi = (min(s for s, _ in v_lines), max(s + t for s, t in v_lines)) if v_lines else (0, 0)
    h_lo, h_hi = (min(s for s, _ in h_lines), max(s + t for s, t in h_lines)) if h_lines else (0, 0)
    v_double, h_double = 3 in (a[U], a[D]), 3 in (a[L], a[R])
    for arm, w in arms.items():
        horizontal = arm in (L, R)
        first = arm in (L, U)
        cross_lines = v_lines if horizontal else h_lines
        lo, hi = (v_lo, v_hi) if horizontal else (h_lo, h_hi)
        strokes = xs if horizontal else ys
        other = a[R if arm == L else L] if horizontal else a[D if arm == U else U]
        if w in (1, 2):
            s, t = m.line(w, horizontal)
            cross_double = v_double if horizontal else h_double
            c0, ct = m.line(w, not horizontal)
            through = (a[U] == 3 and a[D] == 3) if horizontal else (a[L] == 3 and a[R] == 3)
            if cross_double and other:
                end = c0 + ct if first else c0
            elif cross_double and through:
                end = strokes[-1] + lw if first else strokes[1]
            elif cross_double:
                end = strokes[1] + lw if first else strokes[-1]
            elif cross_lines:
                end = hi if first else lo
            else:
                end = c0 + ct if first else c0
            span = (0, end) if first else (end, cw if horizontal else ch)
            if horizontal:
                p.fillRect(QRect(x + span[0], y + s, span[1] - span[0], t), color)
            else:
                p.fillRect(QRect(x + s, y + span[0], t, span[1] - span[0]), color)
            continue
        across = (U, D) if horizontal else (L, R)
        for side in (-1, 1):
            near, far = (across[0], across[1]) if side < 0 else (across[1], across[0])
            if a[near] == 3:
                end = strokes[-1] + lw if first else strokes[1]
            elif a[far] == 3:
                end = strokes[1] + lw if first else strokes[-1]
            elif cross_lines:
                end = hi if first else lo
            elif other == 3:
                end = (cw if horizontal else ch) if first else 0
            else:
                end = strokes[1] + lw if first else strokes[-1]
            span = (0, end) if first else (end, cw if horizontal else ch)
            pos = (ys if horizontal else xs)[side]
            if horizontal:
                p.fillRect(QRect(x + span[0], y + pos, max(0, span[1] - span[0]), lw), color)
            else:
                p.fillRect(QRect(x + pos, y + span[0], lw, max(0, span[1] - span[0])), color)


def _dash(
    p: QPainter, x: int, y: int, m: Metrics, dash: tuple[int, int, bool], color: QColor
) -> None:
    w, count, horizontal = dash
    a, t = m.line(w, horizontal)
    length = m.cw if horizontal else m.ch
    for i in range(count):
        s0 = round(length * i / count)
        s1 = round(length * (i + 0.6) / count)
        if horizontal:
            p.fillRect(QRect(x + s0, y + a, max(1, s1 - s0), t), color)
        else:
            p.fillRect(QRect(x + a, y + s0, t, max(1, s1 - s0)), color)


def _stroke(p: QPainter, x: int, y: int, m: Metrics, color: QColor) -> None:
    """Kept inside the cell: a stroke reaching the next one is cut by the cursor's redraw."""
    p.setClipRect(QRectF(x, y, m.cw, m.ch))
    pen = QPen(color, m.light)
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)


def _arc(p: QPainter, x: int, y: int, m: Metrics, dirs: tuple[str, str], color: QColor) -> None:
    p.save()
    _stroke(p, x, y, m, color)
    cxm, cym = x + m.cx + m.light / 2, y + m.cy + m.light / 2
    r = min(m.cw, m.ch) / 2
    ends = {
        L: QPointF(x, cym),
        R: QPointF(x + m.cw, cym),
        U: QPointF(cxm, y),
        D: QPointF(cxm, y + m.ch),
    }
    a, b = dirs
    path = QPainterPath(ends[a])
    sx = r if R in dirs else -r
    sy = r if D in dirs else -r
    corner_h = QPointF(cxm + sx, cym)
    corner_v = QPointF(cxm, cym + sy)
    if a in (L, R):
        path.lineTo(corner_h)
        path.quadTo(QPointF(cxm, cym), corner_v)
    else:
        path.lineTo(corner_v)
        path.quadTo(QPointF(cxm, cym), corner_h)
    path.lineTo(ends[b])
    p.drawPath(path)
    p.restore()


def _diagonal(
    p: QPainter, x: int, y: int, m: Metrics, kinds: tuple[str, ...], color: QColor
) -> None:
    p.save()
    _stroke(p, x, y, m, color)
    for kind in kinds:
        if kind == "/":
            p.drawLine(QPointF(x + m.cw, y), QPointF(x, y + m.ch))
        else:
            p.drawLine(QPointF(x, y), QPointF(x + m.cw, y + m.ch))
    p.restore()


def _blocks(p: QPainter, x: int, y: int, m: Metrics, o: int, color: QColor) -> None:
    spec = BLOCKS[o]
    if not isinstance(spec, tuple):
        shade = QColor(color)
        shade.setAlphaF(spec)
        p.fillRect(QRect(x, y, m.cw, m.ch), shade)
        return
    for x0, y0, x1, y1 in spec:
        ax, bx = round(m.cw * x0 / 8), round(m.cw * x1 / 8)
        ay, by = round(m.ch * y0 / 8), round(m.ch * y1 / 8)
        p.fillRect(QRect(x + ax, y + ay, bx - ax, by - ay), color)


def _powerline(p: QPainter, x: int, y: int, m: Metrics, o: int, color: QColor) -> None:
    w, h = float(m.cw), float(m.ch)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(x, y)
    p.setClipRect(QRectF(0, 0, w, h))
    solid = {
        0xE0B0: [(0, 0), (w, h / 2), (0, h)],
        0xE0B2: [(w, 0), (0, h / 2), (w, h)],
        0xE0B8: [(0, 0), (0, h), (w, h)],
        0xE0BA: [(w, 0), (w, h), (0, h)],
        0xE0BC: [(0, 0), (w, 0), (0, h)],
        0xE0BE: [(0, 0), (w, 0), (w, h)],
    }
    thin = {
        0xE0B1: [(0, 0), (w, h / 2), (0, h)],
        0xE0B3: [(w, 0), (0, h / 2), (w, h)],
        0xE0B9: [(0, 0), (w, h)],
        0xE0BF: [(0, 0), (w, h)],
        0xE0BB: [(w, 0), (0, h)],
        0xE0BD: [(w, 0), (0, h)],
    }
    if o in solid:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(QPolygonF([QPointF(a, b) for a, b in solid[o]]))
    elif o in thin:
        _stroke(p, 0, 0, m, color)
        p.drawPolyline(QPolygonF([QPointF(a, b) for a, b in thin[o]]))
    elif o in (0xE0B4, 0xE0B6):  # solid half circles, right and left
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(-w if o == 0xE0B4 else 0, 0, 2 * w, h))
    elif o in (0xE0B5, 0xE0B7):  # their outlines
        _stroke(p, 0, 0, m, color)
        left = -w if o == 0xE0B5 else 0
        p.drawEllipse(QRectF(left, m.light / 2, 2 * w - m.light / 2, h - m.light))
    elif o == 0xE0A0:  # version-control branch: a stem and a branch off it
        _stroke(p, 0, 0, m, color)
        p.drawLine(QPointF(w * 0.3, h * 0.15), QPointF(w * 0.3, h * 0.85))
        p.drawLine(QPointF(w * 0.3, h * 0.6), QPointF(w * 0.75, h * 0.35))
        p.drawLine(QPointF(w * 0.75, h * 0.35), QPointF(w * 0.75, h * 0.15))
    elif o in (0xE0A1, 0xE0A3):  # line number and column number: "LN" / "CN" in small caps
        f = p.font()
        f.setPixelSize(max(4, int(h * 0.4)))
        f.setLetterSpacing(f.SpacingType.AbsoluteSpacing, 0)
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, "LN" if o == 0xE0A1 else "CN")
    elif o == 0xE0A2:  # padlock: a shackle over a body
        _stroke(p, 0, 0, m, color)
        p.drawArc(QRectF(w * 0.25, h * 0.2, w * 0.5, h * 0.4), 0, 180 * 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawRect(QRectF(w * 0.15, h * 0.42, w * 0.7, h * 0.43))
    p.restore()


def draw(p: QPainter, ch: str, x: int, y: int, m: Metrics, color: QColor) -> None:
    o = ord(ch)
    if 0x2580 <= o <= 0x259F:
        _blocks(p, x, y, m, o, color)
    elif 0x2500 <= o <= 0x257F:
        match box_shape(ch):
            case ("arms", arms):
                _arms(p, x, y, m, arms, color)
            case ("dash", dash):
                _dash(p, x, y, m, dash, color)
            case ("arc", ends):
                _arc(p, x, y, m, ends, color)
            case ("diagonal", kinds):
                _diagonal(p, x, y, m, kinds, color)
    else:
        _powerline(p, x, y, m, o, color)
