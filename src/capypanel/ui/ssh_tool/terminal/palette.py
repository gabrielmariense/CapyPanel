"""The terminal's colours, built from the app theme's own roles, so a terminal follows the theme.

- The 16 colours as text: red the stopped colour, green online, yellow attention, blue working,
  magenta and cyan Printers' toner inks; the bright ones 25 % toward white in dark themes and
  toward black in light ones; black and white from the theme's three text colours.
- The 16 as backgrounds have shades of their own. Light themes: each hue 22 % over the card,
  black the text colour, white the window's background. Dark themes: each hue itself, except
  blue and magenta at 40 % over the card so text reads on them; black the window's background,
  white the second text colour. Bright backgrounds follow the same rules.
- A cell whose pair reads under 4.5:1 swaps its text for the theme's text or card colour,
  whichever reads, except where the two colours are the same, and only when both are among the
  16 or the defaults: a colour from the 256 table or 24-bit was picked on purpose. Where neither
  reads (magenta at full strength as a reversed cell's background, in three themes), black or
  white does: one of the two always reaches 4.58:1.

Cells keep palette numbers (core/ssh/screen.py), so switching the palette recolours everything
already printed, the scrollback too."""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from capypanel.ui.themes import engine

_CUBE = (0, 95, 135, 175, 215, 255)
READS = 4.5  # WCAG AA for text
LAST_RESORT = ("#000000", "#ffffff")  # one of them reads on any colour


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
    """`amount` of `color` laid over `base`, as the theme engine mixes."""
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
    """One of the 16 or a default: the colours the swap may judge."""
    return value == "default" or (isinstance(value, int) and value < 16)


@dataclass(frozen=True)
class TermPalette:
    name: str
    background: str  # the card colour
    foreground: str  # text
    cursor: str  # the accent
    selection: str
    ansi: tuple[str, ...]  # the 16 as text
    back: tuple[str, ...]  # the 16 as backgrounds
    swap_to: tuple[str, ...]  # what an unreadable cell's text may take

    def color(self, value: int | str, *, foreground: bool, bold: bool = False) -> str:
        """The colour a cell's fg or bg value draws in, as "#rrggbb"."""
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
        """A cell's text and background colours, the text swapped when it wouldn't read."""
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
    """The palette from a theme's roles: bg, card, text, text2, text3, accent, sel, the status
    colours (stopped, online, attention, working) and the inks (ink_magenta, ink_cyan)."""
    hues = [r[k] for k in ("stopped", "online", "attention", "working", "ink_magenta", "ink_cyan")]
    bright = [mix("#ffffff" if dark else "#000000", h, 0.25) for h in hues]
    if dark:
        ansi = [r["bg"], *hues, r["text2"], mix(r["text2"], r["text3"], 0.5), *bright, r["text"]]
        back = [
            r["bg"],
            *hues[:3],
            mix(hues[3], r["card"], 0.40),  # blue
            mix(hues[4], r["card"], 0.40),  # magenta
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
        cursor=r["accent"],
        selection=r["sel"],
        ansi=tuple(ansi),
        back=tuple(back),
        swap_to=(r["text"], r["card"]),
    )


def current() -> TermPalette:
    """The app's theme now, from the engine's live values: a custom theme's own colours; for a
    Windows theme, the dark or light it resolves to, with this PC's accent and the status
    colours fitted to it."""
    theme = engine.current()
    if theme.engine == "custom":
        roles = {**theme.colors, "sel": theme.colors["sel_solid"]}
        return from_roles(theme.id, roles, theme.scheme == "dark")
    scheme = engine.native_scheme()
    tokens = engine.native_tokens(QApplication.palette().color(QPalette.ColorRole.Accent))
    status = dict(engine.status_colors())
    roles = {**engine.TOKENS[scheme], **tokens, **status, "text3": status["offline"]}
    return from_roles(f"windows-{scheme}", roles, scheme == "dark")
