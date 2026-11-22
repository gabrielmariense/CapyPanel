import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from capypanel.core.i18n import _

EXTRA = "bar_marks"  # [{"percent": 50, "color": "#ffffff"}, …]: the marks the user added
LOW_COLOR = "low_mark_color"
LOWEST, HIGHEST = 1, 99  # % a mark can sit at
MOST = 8
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class Mark:
    percent: int
    color: str = ""
    low: bool = False


def load(prefs: Mapping[str, Any], low: int) -> tuple[Mark, ...]:
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
    parts = []
    for mark in marks:
        text = _("{percent} %").format(percent=mark.percent)
        parts.append(_("{level} (low)").format(level=text) if mark.low else text)
    return ", ".join(parts)


def hint(marks: tuple[Mark, ...]) -> str:
    if len(marks) == 1:
        return _("The mark shows the low level, {low} %.").format(low=marks[0].percent)
    return _("The marks show {marks}.").format(marks=percents_text(marks))
