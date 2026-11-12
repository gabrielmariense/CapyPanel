"""What a printer's last Refresh says, in words and colours: the Status and Toner cells, and the
heading of its Details. One place, so the table, Details and Report always agree."""

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from PySide6.QtCore import QLocale

from capypanel.core import i18n
from capypanel.core.i18n import _
from capypanel.core.printers import doc360, snmp
from capypanel.core.printers.printer import PrinterInfo
from capypanel.core.printers.reading import Device, Problem, Reading, State, Supply, SupplyKind
from capypanel.ui.checks import clock_text
from capypanel.ui.themes import engine as themes

DEFAULT_LOW = 10  # %: a supply at or below this shows as low


# The current theme's colours, read at each call: a theme switch changes them.
def green() -> str:  # working
    return themes.status_color("online")


def amber() -> str:  # needs attention
    return themes.status_color("attention")


def red() -> str:  # stopped
    return themes.status_color("stopped")


def grey() -> str:  # offline
    return themes.status_color("offline")


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
# The table's Status column fits about 16 letters in either language; these say the longer
# ones shorter there. The full words stay in the tip, Details and notifications.
_SHORT = {
    Problem.OUTPUT_FULL: lambda: _("Output full"),
    Problem.OUTPUT_NEAR_FULL: lambda: _("Output nearly full"),
    Problem.OUTPUT_TRAY_MISSING: lambda: _("No output tray"),
    Problem.SERVICE_REQUESTED: lambda: _("Needs service"),
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
    refused: str = ""  # it refused the SNMP v3 account: snmp.Refused's reason


@dataclass(frozen=True)
class Counted:
    """The last Refresh's page counters from Doc360 MPS, by serial (doc360.key()), or why
    there are none. For every printer whose counters come from there."""

    when: datetime
    counters: Mapping[str, doc360.Counter] = field(default_factory=dict)
    error: str = ""
    account: str = ""  # NO_ACCOUNT or REFUSED: Details offers the account's window
    older: tuple[int, int] | None = None  # (year, month) when these aren't this month's


NO_ACCOUNT, REFUSED = "none", "refused"  # Counted.account


class Attention(Enum):
    """Why a printer needs attention, for the warnings: the rail's count, the strip above the
    table and Windows notifications."""

    STOPPED = "stopped"
    OFFLINE = "offline"
    LOW = "low"


@dataclass(frozen=True)
class Cell:
    text: str
    tip: str
    color: str  # the dot's or swatch's colour; "" for none
    quiet: bool = False  # greyed: not checked, offline
    warn: bool = False  # in amber: a low supply
    supply: Supply | None = None  # the Toner cell's supply, for its bar
    full: str = ""  # the whole words when `text` says them shorter (the table's Status)
    nothing: bool = False  # "Not checked": sorts last, and stays empty in a Report's file

    def said(self) -> str:
        """The words in full: Details' line and notifications have the room."""
        return self.full or self.text


def _worded(short: str, full: str, tip: str, color: str) -> Cell:
    """A Status cell whose words may be shortened; the tip then starts with the full words."""
    if short == full:
        return Cell(full, tip, color)
    return Cell(short, "\n".join((full, tip)), color, full=full)


def status(checked: Checked | None, low: int) -> Cell:
    """The Status cell, and the line under a printer's name in Details: a few words. The
    printer's own messages can be long, so they go in the tip and in Details, in full."""
    if checked is None:
        return Cell(_("Not checked"), _("Not checked: use Refresh"), "", quiet=True, nothing=True)
    when = clock_text(checked.when)
    if checked.offline:
        return Cell(_("Offline"), _("No answer at {when}.").format(when=when), grey(), quiet=True)
    if checked.refused:
        tip = _("Refused at {when}: {why}").format(when=when, why=refused_text(checked.refused))
        hint = _("Check the SNMP account in Settings › Printers › Connecting.")
        return Cell(_("Refused"), "\n".join((tip, hint)), amber(), quiet=True)
    if checked.reading is None:
        tip = _("Couldn't read the printer's answer at {when}.").format(when=when)
        return Cell(_("Unreadable"), f"{tip}\n{checked.error}".strip(), amber(), quiet=True)
    reading = checked.reading
    tip = "\n".join((_("Checked {when}.").format(when=when), *reading.messages))
    stops = [problem for problem in _STOPS if problem in reading.problems]
    if stops or reading.device is Device.DOWN:
        if stops:
            return _worded(*_problem_words(stops[0]), tip, red())
        return Cell(_("Stopped"), tip, red())
    warnings = [problem for problem in _WARNINGS if problem in reading.problems]
    lows = [s for s in reading.supplies if is_low(s, low)]
    if warnings or lows or reading.messages or reading.device is Device.WARNING:
        if warnings:
            return _worded(*_problem_words(warnings[0]), tip, amber())
        if lows:
            return _worded(short_low_text(lows[0]), low_text(lows[0]), tip, amber())
        return Cell(_("Needs attention"), tip, amber())
    words = _STATES[reading.state]() if reading.state in _STATES else _("Ready")
    return Cell(words, tip, green())


def attention(checked: Checked | None, low: int) -> Attention | None:
    """A stopped printer (the red Status), one that didn't answer, or one with a toner, ink,
    drum or box at the low level; None for the rest. "Needs attention" from the printer's own
    messages, a refused account or an unreadable answer don't count: they're not warnings."""
    if checked is None:
        return None
    if checked.offline:
        return Attention.OFFLINE
    if checked.reading is None:
        return None
    if status(checked, low).color == red():
        return Attention.STOPPED
    if any(is_low(s, low) for s in checked.reading.supplies):
        return Attention.LOW
    return None


def status_words() -> list[str]:
    """Every word the Status column can show, so its first width fits the longest."""
    problems = [_problem_words(p)[0] for p in (*_STOPS, *_WARNINGS)]
    states = [said() for said in _STATES.values()]
    others = (_("Not checked"), _("Offline"), _("Refused"), _("Unreadable"), _("Stopped"),
              _("Needs attention"), _("Ready"), _("Ink low"), _("Toner low"),
              _("Waste nearly full"), _("Supply low"))  # fmt: skip
    return [*problems, *states, *others]


def toner_words() -> list[str]:
    """The Toner column's longest words for each colour, so its first width fits them."""
    names = (_("Black"), _("Cyan"), _("Magenta"), _("Yellow"), _("Toner"), _("Ink"))
    words = []
    for colour in names:
        for level in (
            _("{colour} {percent} %").format(colour=colour, percent=100),
            _("{colour}: some left").format(colour=colour),
            _("{colour}: not reported").format(colour=colour),
        ):
            words += [level, _("{level} · low").format(level=level)]
    return words


def toner_models(reading: Reading) -> str:
    """The toners' and inks' names as the printer gives them, which often hold the cartridge's
    model ("Black Cartridge HP CF258A"), for the Report."""
    kinds = (SupplyKind.TONER, SupplyKind.INK)
    return "; ".join(s.name for s in reading.supplies if s.kind in kinds and s.name)


def refused_text(reason: str) -> str:
    """Why a printer refused the SNMP v3 account, in words."""
    texts = {
        snmp.USER: lambda: _("it doesn't know the SNMP v3 user name."),
        snmp.AUTH: lambda: _("wrong authentication password or type."),
        snmp.PRIVACY: lambda: _("wrong encryption password."),
        snmp.LEVEL: lambda: _("it wants authentication or encryption set differently."),
        snmp.TIME_WINDOW: lambda: _("its clock and CapyPanel's didn't agree."),
    }
    return texts.get(reason, lambda: _("it refused the SNMP v3 request."))()


def doc360_pages(
    info: PrinterInfo, reading: Reading | None, counted: Counted | None
) -> tuple[int | None, str]:
    """A Doc360 MPS printer's total pages, or why there's none; (None, "") before a Refresh.
    Doc360 lists printers by serial: the list's own, or else the one the printer reports."""
    if counted is None:
        return None, ""
    if counted.error:
        return None, counted.error
    serial = info.serial or (reading.serial if reading else "")
    if not serial:
        return None, _("Add the printer's serial number: Doc360 MPS lists printers by serial.")
    found = counted.counters.get(doc360.key(serial))
    if found is None:
        return None, _("Doc360 MPS doesn't list serial {serial}.").format(serial=serial)
    if found.life is None:
        return None, _("Doc360 MPS has no total for this printer.")
    return found.life, ""


def older_text(counted: Counted | None) -> str:
    """The month Doc360's counts are from, when it isn't this one ("October 2026"); "" when
    they're this month's, as they should be."""
    if counted is None or counted.older is None:
        return ""
    year, month = counted.older
    locale = QLocale(i18n.language())
    # i18n: a month and its year, "October 2026"
    return _("{month} {year}").format(month=locale.standaloneMonthName(month), year=year)


def doc360_tip(counted: Counted) -> str:
    """Where a Doc360 MPS total comes from, and why it can be behind the printer."""
    return _(
        "Fetched from Doc360 MPS at {when}. Doc360 reads printers on its own schedule, so this "
        "can be behind the printer."
    ).format(when=clock_text(counted.when))


def plain_tip(text: str) -> str:
    """A tooltip that shows `text` exactly: Qt takes anything that looks like HTML as HTML, and
    tips hold the printer's own words (its messages, its supplies' names)."""
    return f"<p style='white-space:pre-wrap'>{html.escape(text)}</p>" if text else ""


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


def short_low_text(supply: Supply) -> str:
    """low_text for the Status column: a supply's own name can be long, so it's left out."""
    if supply.receptacle:
        return _("Waste nearly full")
    if supply.kind in (SupplyKind.INK, SupplyKind.TONER):
        return low_text(supply)
    return _("Supply low")


def _problem_words(problem: Problem) -> tuple[str, str]:
    """(the table's words, the full words) for a problem the printer reports."""
    full = (_STOPS | _WARNINGS)[problem]()
    return (_SHORT[problem]() if problem in _SHORT else full), full


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
        text = _("{colour}: not reported").format(colour=colour)
    running_low = is_low(lowest, low)
    if running_low:
        text = _("{level} · low").format(level=text)
    lines = [f"{s.name}: {level_text(s)}" for s in found]
    if not all(reports_level(s) for s in found):
        lines.append(no_level_text())
    return Cell(text, "\n".join(lines), supply_color(lowest), warn=running_low, supply=lowest)


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
    """A supply's bar colour in the current theme, by the colour its name says; a toner or ink
    that names none is black, drums, boxes and the rest a grey-blue."""
    inks = themes.ink_colors()
    found = _COLOUR_WORDS.search(supply.name)
    if found:
        return inks[found[1].lower()]
    return inks["black"] if supply.kind in (SupplyKind.TONER, SupplyKind.INK) else inks["other"]


def supply_edge(supply: Supply) -> str:
    """The 1 px edge around a supply's bar or swatch: yellow's darker one, so it shows on a light
    pane; any other supply's own colour (no visible edge)."""
    color = supply_color(supply)
    inks = themes.ink_colors()
    return inks["yellow_edge"] if color == inks["yellow"] else color


def level_text(supply: Supply) -> str:
    if supply.percent is not None:
        return _("{percent} %").format(percent=supply.percent)
    return _("some left") if supply.some_left else _("not reported")


def reports_level(supply: Supply) -> bool:
    """Whether the printer gives this supply a level: a percent, or at least "some left"."""
    return supply.percent is not None or supply.some_left


def no_level_text() -> str:
    return _("This printer doesn't report a level for this supply.")
