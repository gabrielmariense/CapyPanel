"""The marks on the supply bars (Details and the Toner column): one at the low level, always,
plus any the user adds in Settings › Printers › Warnings and supplies, each with its own colour
or the theme's text colour. Kept in the tool's settings."""

import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from capypanel.core.i18n import _

EXTRA = "bar_marks"  # [{"percent": 50, "color": "#ffffff"}, …]: the marks the user added
LOW_COLOR = "low_mark_color"  # the low mark's colour; "" or missing: the theme's text colour
LOWEST, HIGHEST = 1, 99  # % a mark can sit at
MOST = 8  # marks the user can add
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class Mark:
    percent: int
    color: str = ""  # "#rrggbb", or "" for the theme's text colour
    low: bool = False  # the low level's mark: it follows that setting and can't be removed


def load(prefs: Mapping[str, Any], low: int) -> tuple[Mark, ...]:
    """The low mark first, then the user's own, by %; odd entries are skipped."""
    found: dict[int, Mark] = {}
    saved = prefs.get(EXTRA)
    for entry in saved if isinstance(saved, list) else ():
        if not isinstance(entry, Mapping):
            continue
        percent = entry.get("percent")
        if isinstance(percent, bool) or not isinstance(percent, int):
            continue
        if LOWEST <= percent <= HIGHEST and percent != low:
            found.setdefault(percent, Mark(percent, _color(entry.get("color"))))
    extra = sorted(found.values(), key=lambda m: m.percent)[:MOST]
    return (Mark(low, _color(prefs.get(LOW_COLOR)), low=True), *extra)


def save(prefs: MutableMapping[str, Any], marks: tuple[Mark, ...]) -> None:
    low = next((m for m in marks if m.low), None)
    if low is not None and low.color:
        prefs[LOW_COLOR] = low.color
    else:
        prefs.pop(LOW_COLOR, None)
    extra = [{"percent": m.percent, "color": m.color} for m in marks if not m.low]
    if extra:
        prefs[EXTRA] = extra
    else:
        prefs.pop(EXTRA, None)


def _color(value: object) -> str:
    return value.lower() if isinstance(value, str) and _HEX.fullmatch(value) else ""


def percents_text(marks: tuple[Mark, ...]) -> str:
    """ "10 % (low), 50 %": what the marks show, for Details' hint and Settings' row."""
    parts = []
    for mark in marks:
        text = _("{percent} %").format(percent=mark.percent)
        parts.append(_("{level} (low)").format(level=text) if mark.low else text)
    return ", ".join(parts)


def hint(marks: tuple[Mark, ...]) -> str:
    """The line under Details' bars."""
    if len(marks) == 1:
        return _("The mark shows the low level, {low} %.").format(low=marks[0].percent)
    return _("The marks show {marks}.").format(marks=percents_text(marks))
