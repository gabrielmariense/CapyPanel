from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from capypanel.ui.themes import engine

_CUBE = (0, 95, 135, 175, 215, 255)
READS = 4.5  # WCAG AA for text
SHOWS = 3.0  # WCAG AA for a graphic: the cursor
LAST_RESORT = ("#000000", "#ffffff")


def _xterm_256(index: int) -> str:
    if index < 232:
        i = index - 16
        r, g, b = _CUBE[i // 36], _CUBE[(i // 6) % 6], _CUBE[i % 6]
    else:
        r = g = b = 8 + 10 * (index - 232)
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")[-6:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(color: str, base: str, amount: float) -> str:
    a, b = _rgb(color), _rgb(base)
    r, g, bl = (round(b[i] + (a[i] - b[i]) * amount) for i in range(3))
    return f"#{r:02x}{g:02x}{bl:02x}"


@cache
def _luminance(value: str) -> float:
    def linear(c: int) -> float:
        x = c / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


@cache
def contrast(a: str, b: str) -> float:
    x, y = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def _among_ours(value: int | str) -> bool:
    return value == "default" or (isinstance(value, int) and value < 16)


@dataclass(frozen=True)
class TermPalette:
    name: str
    background: str
    foreground: str
    cursor: str
    selection: str
    match: str
    ansi: tuple[str, ...]
    back: tuple[str, ...]
    swap_to: tuple[str, ...]

    def color(self, value: int | str, *, foreground: bool, bold: bool = False) -> str:
        if value == "default":
            return self.foreground if foreground else self.background
        if isinstance(value, int):
            if foreground and bold and value < 8:
                value += 8  # bold as bright, as Windows Terminal does by default
            if value < 16:
                return self.ansi[value] if foreground else self.back[value]
            return _xterm_256(value)
        if value.startswith("#") and len(value) == 7:
            return value
        return self.foreground if foreground else self.background

    def cell_colors(
        self, fg: int | str, bg: int | str, *, bold: bool = False, reverse: bool = False
    ) -> tuple[str, str]:
        """Text swapped when unreadable; never a 256-table or 24-bit colour, picked on purpose."""
        f = self.color(fg, foreground=True, bold=bold)
        b = self.color(bg, foreground=False)
        if reverse:
            f, b = b, f
        if f == b or not (_among_ours(fg) and _among_ours(bg)) or contrast(f, b) >= READS:
            return f, b
        swapped = max(self.swap_to, key=lambda c: contrast(c, b))
        if contrast(swapped, b) < READS:
            swapped = max(LAST_RESORT, key=lambda c: contrast(c, b))
        return swapped, b


def from_roles(name: str, r: Mapping[str, str], dark: bool) -> TermPalette:
    hues = [r[k] for k in ("stopped", "online", "attention", "working", "ink_magenta", "ink_cyan")]
    bright = [mix("#ffffff" if dark else "#000000", h, 0.25) for h in hues]
    if dark:
        ansi = [r["bg"], *hues, r["text2"], mix(r["text2"], r["text3"], 0.5), *bright, r["text"]]
        back = [
            r["bg"],
            *hues[:3],
            mix(
                hues[3], r["card"], 0.40
            ),  # blue and magenta: 40 % over the card, so text reads on them
            mix(hues[4], r["card"], 0.40),
            hues[5],
            r["text2"],
            ansi[8],
            *bright[:3],
            mix(bright[3], r["card"], 0.40),
            *bright[4:],
            r["text"],
        ]
    else:
        ansi = [r["text"], *hues, r["text2"], r["text3"], *bright, mix(r["text"], r["text2"], 0.5)]
        back = [
            r["text"],
            *(mix(h, r["card"], 0.22) for h in hues),
            r["bg"],
            r["text3"],
            *(mix(h, r["card"], 0.22) for h in bright),
            r["card"],
        ]
    return TermPalette(
        name=name,
        background=r["card"],
        foreground=r["text"],
        cursor=r["accent"] if contrast(r["accent"], r["card"]) >= SHOWS else r["text"],
        selection=r["sel"],
        match=mix(r["attention"], r["card"], 0.30),
        ansi=tuple(ansi),
        back=tuple(back),
        swap_to=(r["text"], r["card"]),
    )


def current() -> TermPalette:
    theme = engine.current()
    if theme.engine == "custom":
        roles = {**theme.colors, "sel": theme.colors["sel_solid"]}
        return from_roles(theme.id, roles, theme.scheme == "dark")
    scheme = engine.native_scheme()
    tokens = engine.native_tokens(QApplication.palette().color(QPalette.ColorRole.Accent))
    status = dict(engine.status_colors())
    roles = {**engine.TOKENS[scheme], **tokens, **status, "text3": status["offline"]}
    return from_roles(f"windows-{scheme}", roles, scheme == "dark")
