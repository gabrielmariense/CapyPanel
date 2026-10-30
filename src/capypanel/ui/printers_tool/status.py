"""What a printer's last Refresh says, in words and colours: the Status and Toner cells, and the
heading of its Details. One place, so the table, Details and Report always agree."""

import re
from dataclasses import dataclass
from datetime import datetime

from capypanel.core.i18n import _
from capypanel.core.printers.reading import Device, Problem, Reading, State, Supply, SupplyKind
from capypanel.ui.checks import clock_text

GREEN, AMBER, RED, GREY = "#3fae4a", "#d29922", "#e5534b", "#8a8a8a"  # working ... offline
DEFAULT_LOW = 10  # %: a supply at or below this shows as low
# A supply's bar colour, by the colour its name says; drums, boxes and the rest are grey-blue.
INKS = {"black": "#9aa3b2", "cyan": "#22b8cf", "magenta": "#d6409f", "yellow": "#f2c94c"}
OTHER_SUPPLY = "#6b7a90"
_COLOUR_WORDS = re.compile(r"\b(black|cyan|magenta|yellow)\b", re.IGNORECASE)

# The printer's detected errors: those that stop it, then those that only need attention.
_STOPS = {
    Problem.JAMMED: lambda: _("Paper jam"),
    Problem.DOOR_OPEN: lambda: _("Door open"),
    Problem.NO_TONER: lambda: _("Out of toner"),
    Problem.NO_PAPER: lambda: _("Out of paper"),
    Problem.SUPPLY_MISSING: lambda: _("Supply missing"),
    Problem.INPUT_TRAY_MISSING: lambda: _("Tray missing"),
    Problem.OUTPUT_FULL: lambda: _("Output tray full"),
    Problem.OFFLINE: lambda: _("Paused"),
}
_WARNINGS = {
    Problem.LOW_TONER: lambda: _("Toner low"),
    Problem.LOW_PAPER: lambda: _("Paper low"),
    Problem.INPUT_TRAY_EMPTY: lambda: _("Tray empty"),
    Problem.OUTPUT_NEAR_FULL: lambda: _("Output tray nearly full"),
    Problem.OUTPUT_TRAY_MISSING: lambda: _("Output tray missing"),
    Problem.SERVICE_REQUESTED: lambda: _("Service requested"),
    Problem.MAINTENANCE_OVERDUE: lambda: _("Maintenance due"),
}
_STATES = {
    State.IDLE: lambda: _("Idle"),
    State.PRINTING: lambda: _("Printing"),
    State.WARMING_UP: lambda: _("Warming up"),
}


@dataclass(frozen=True)
class Checked:
    """One printer's last Refresh: what it read, or why it couldn't."""

    when: datetime
    reading: Reading | None = None
    offline: bool = False  # no answer
    error: str = ""  # it answered, but not in a way CapyPanel could read


@dataclass(frozen=True)
class Cell:
    text: str
    tip: str
    color: str  # the dot's or swatch's colour; "" for none
    quiet: bool = False  # greyed: not checked, offline
    warn: bool = False  # in amber: a low supply
    supply: Supply | None = None  # the Toner cell's supply, for its bar


def status(checked: Checked | None, low: int) -> Cell:
    """The Status cell, and the line under a printer's name in Details: a few words. The
    printer's own messages can be long, so they go in the tip and in Details, in full."""
    if checked is None:
        return Cell("", _("Not checked: use Refresh"), "", quiet=True)
    when = clock_text(checked.when)
    if checked.offline:
        return Cell(_("Offline"), _("No answer at {when}.").format(when=when), GREY, quiet=True)
    if checked.reading is None:
        tip = _("Couldn't read the printer's answer at {when}.").format(when=when)
        return Cell(_("Unreadable"), f"{tip}\n{checked.error}".strip(), AMBER, quiet=True)
    reading = checked.reading
    tip = "\n".join((_("Checked {when}.").format(when=when), *reading.messages))
    stops = [text() for problem, text in _STOPS.items() if problem in reading.problems]
    if stops or reading.device is Device.DOWN:
        return Cell(stops[0] if stops else _("Stopped"), tip, RED)
    warnings = [text() for problem, text in _WARNINGS.items() if problem in reading.problems]
    lows = [s for s in reading.supplies if is_low(s, low)]
    if warnings or lows or reading.messages or reading.device is Device.WARNING:
        if warnings:
            words = warnings[0]
        elif lows:
            words = low_text(lows[0])
        else:
            words = _("Needs attention")
        return Cell(words, tip, AMBER)
    words = _STATES[reading.state]() if reading.state in _STATES else _("Ready")
    return Cell(words, tip, GREEN)


def is_low(supply: Supply, low: int) -> bool:
    """A toner, ink, drum or waste box at or below the low level. Maintenance parts (fuser,
    rollers) show their level, but wearing down isn't something to warn about here."""
    return supply.kind is not SupplyKind.OTHER and supply.low(low)


def low_text(supply: Supply) -> str:
    if supply.receptacle:
        return _("{supply} nearly full").format(supply=supply.name)
    if supply.kind is SupplyKind.INK:
        return _("Ink low")
    if supply.kind is SupplyKind.TONER:
        return _("Toner low")
    return _("{supply} low").format(supply=supply.name)


def toner(checked: Checked | None, low: int) -> Cell:
    """The Toner cell: the lowest toner or ink, "Cyan 8 % · low"; empty when there's none."""
    if checked is None or checked.reading is None:
        return Cell("", "", "")
    found = [s for s in checked.reading.supplies if s.kind in (SupplyKind.TONER, SupplyKind.INK)]
    if not found:
        return Cell("", "", "")
    measured = [s for s in found if s.percent is not None]
    lowest = min(measured, key=lambda s: s.percent or 0) if measured else found[0]
    colour = colour_name(lowest)
    if lowest.percent is not None:
        text = _("{colour} {percent} %").format(colour=colour, percent=lowest.percent)
    elif lowest.some_left:
        text = _("{colour}: some left").format(colour=colour)
    else:
        text = _("{colour}: level unknown").format(colour=colour)
    running_low = is_low(lowest, low)
    if running_low:
        text = _("{level} · low").format(level=text)
    tip = "\n".join(f"{s.name}: {level_text(s)}" for s in found)
    return Cell(text, tip, supply_color(lowest), warn=running_low, supply=lowest)


def colour_name(supply: Supply) -> str:
    """The colour a toner or ink is, in words ("Cyan"), or "Toner" / "Ink" when its name says
    none (a black-only printer often just says "Toner Cartridge")."""
    found = _COLOUR_WORDS.search(supply.name)
    if found:
        return {
            "black": _("Black"), "cyan": _("Cyan"), "magenta": _("Magenta"), "yellow": _("Yellow"),
        }[found[1].lower()]  # fmt: skip
    return _("Ink") if supply.kind is SupplyKind.INK else _("Toner")


def supply_color(supply: Supply) -> str:
    found = _COLOUR_WORDS.search(supply.name)
    if found:
        return INKS[found[1].lower()]
    return INKS["black"] if supply.kind in (SupplyKind.TONER, SupplyKind.INK) else OTHER_SUPPLY


def level_text(supply: Supply) -> str:
    if supply.percent is not None:
        return _("{percent} %").format(percent=supply.percent)
    return _("some left") if supply.some_left else _("level unknown")
