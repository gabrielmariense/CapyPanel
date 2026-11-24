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


def green() -> str:
    return themes.status_color("online")


def amber() -> str:
    return themes.status_color("attention")


def red() -> str:
    return themes.status_color("stopped")


def grey() -> str:
    return themes.status_color("offline")


_COLOUR_WORDS = re.compile(r"\b(black|cyan|magenta|yellow)\b", re.IGNORECASE)

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
    when: datetime
    reading: Reading | None = None
    offline: bool = False
    error: str = ""
    refused: str = ""


@dataclass(frozen=True)
class Counted:
    when: datetime
    counters: Mapping[str, doc360.Counter] = field(default_factory=dict)
    error: str = ""
    account: str = ""
    older: tuple[int, int] | None = None
    place: str = ""


NO_ACCOUNT, REFUSED = "none", "refused"


class Attention(Enum):
    STOPPED = "stopped"
    OFFLINE = "offline"
    LOW = "low"


class Reason(Enum):
    JAMMED = "jammed"
    NO_PAPER = "no_paper"
    NO_TONER = "no_toner"
    STOPPED = "stopped"
    OFFLINE = "offline"
    LOW = "low"

    @property
    def kind(self) -> Attention:
        return {Reason.OFFLINE: Attention.OFFLINE, Reason.LOW: Attention.LOW}.get(
            self, Attention.STOPPED
        )

    def words(self) -> str:
        return {
            Reason.JAMMED: lambda: _("Paper jam"),
            Reason.NO_PAPER: lambda: _("Out of paper"),
            Reason.NO_TONER: lambda: _("Out of toner"),
            Reason.STOPPED: lambda: _("Stopped"),
            Reason.OFFLINE: lambda: _("Offline"),
            Reason.LOW: lambda: _("Supply low"),
        }[self]()


DEFAULT_REASONS = frozenset({Reason.OFFLINE, Reason.JAMMED, Reason.NO_TONER, Reason.LOW})
_STOP_REASONS = {
    Problem.JAMMED: Reason.JAMMED,
    Problem.NO_PAPER: Reason.NO_PAPER,
    Problem.NO_TONER: Reason.NO_TONER,
}


@dataclass(frozen=True)
class Cell:
    text: str
    tip: str
    color: str
    quiet: bool = False
    warn: bool = False
    supply: Supply | None = None
    full: str = ""
    nothing: bool = False
    why: str = ""

    def said(self) -> str:
        return self.full or self.text


def _worded(short: str, full: str, tip: str, color: str) -> Cell:
    if short == full:
        return Cell(full, tip, color)
    return Cell(short, "\n".join((full, tip)), color, full=full)


def status(checked: Checked | None, low: int) -> Cell:
    if checked is None:
        return Cell(_("Not checked"), _("Not checked: use Refresh"), "", quiet=True, nothing=True)
    when = clock_text(checked.when)
    if checked.offline:
        return Cell(_("Offline"), _("No answer at {when}.").format(when=when), grey(), quiet=True)
    if checked.refused:
        why = refused_text(checked.refused)
        tip = _("Refused at {when}: {why}").format(when=when, why=why)
        hint = _("Check the SNMP account in Settings › Printers › Connecting.")
        said = "\n".join((why[:1].upper() + why[1:], hint))
        return Cell(_("Refused"), "\n".join((tip, hint)), amber(), quiet=True, why=said)
    if checked.reading is None:
        tip = _("Couldn't read the printer's answer at {when}.").format(when=when)
        return Cell(_("Unreadable"), f"{tip}\n{checked.error}".strip(), amber(), quiet=True,
                    why=checked.error.strip())  # fmt: skip
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


def reasons(checked: Checked | None, low: int) -> list[Reason]:
    if checked is None:
        return []
    if checked.offline:
        return [Reason.OFFLINE]
    reading = checked.reading
    if reading is None:
        return []
    stops = [problem for problem in _STOPS if problem in reading.problems]
    found = [_STOP_REASONS[p] for p in stops if p in _STOP_REASONS]
    if not stops and reading.device is Device.DOWN:
        found.append(Reason.STOPPED)
    if any(is_low(s, low) for s in reading.supplies):
        found.append(Reason.LOW)
    return found


def attention(
    checked: Checked | None, low: int, wanted: frozenset[Reason] = DEFAULT_REASONS
) -> Reason | None:
    return next((reason for reason in reasons(checked, low) if reason in wanted), None)


def status_words() -> list[str]:
    problems = [_problem_words(p)[0] for p in (*_STOPS, *_WARNINGS)]
    states = [said() for said in _STATES.values()]
    others = (_("Not checked"), _("Offline"), _("Refused"), _("Unreadable"), _("Stopped"),
              _("Needs attention"), _("Ready"), _("Ink low"), _("Toner low"),
              _("Waste nearly full"), _("Supply low"))  # fmt: skip
    return [*problems, *states, *others]


def toner_words() -> list[str]:
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
    kinds = (SupplyKind.TONER, SupplyKind.INK)
    return "; ".join(s.name for s in reading.supplies if s.kind in kinds and s.name)


def refused_text(reason: str) -> str:
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
    pages, error, _place = _doc360(info, reading, counted)
    return pages, error


def doc360_place(info: PrinterInfo, reading: Reading | None, counted: Counted | None) -> str:
    return _doc360(info, reading, counted)[2]


def _doc360(
    info: PrinterInfo, reading: Reading | None, counted: Counted | None
) -> tuple[int | None, str, str]:
    if counted is None:
        return None, "", ""
    if counted.error:
        return None, counted.error, counted.place
    serial = info.serial or (reading.serial if reading else "")
    if not serial:
        words = _("Add the printer's serial number: Doc360 MPS lists printers by serial.")
        return None, words, "doc360-serial-missing"
    found = counted.counters.get(doc360.key(serial))
    if found is None:
        words = _("Doc360 MPS doesn't list serial {serial}.").format(serial=serial)
        return None, words, "doc360-serial-not-listed"
    if found.life is None:
        return None, _("Doc360 MPS has no total for this printer."), "doc360-no-total"
    return found.life, "", ""


def status_place(checked: Checked | None) -> str:
    if checked is None:
        return ""
    if checked.offline:
        return "printer-offline"
    if checked.refused:
        return "printer-refused"
    if checked.reading is None:
        return "printer-unreadable"
    return ""


def older_text(counted: Counted | None) -> str:
    if counted is None or counted.older is None:
        return ""
    year, month = counted.older
    locale = QLocale(i18n.language())
    # i18n: a month and its year, "October 2026"
    return _("{month} {year}").format(month=locale.standaloneMonthName(month), year=year)


def doc360_behind() -> str:
    return _("Doc360 MPS reads printers on its own schedule, so this count can be behind the "
             "printer.")  # fmt: skip


def plain_tip(text: str) -> str:
    """A tooltip that shows `text` exactly: Qt takes anything that looks like HTML as HTML, and
    tips hold the printer's own words (its messages, its supplies' names)."""
    return f"<p style='white-space:pre-wrap'>{html.escape(text)}</p>" if text else ""


def is_low(supply: Supply, low: int) -> bool:
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
    if supply.receptacle:
        return _("Waste nearly full")
    if supply.kind in (SupplyKind.INK, SupplyKind.TONER):
        return low_text(supply)
    return _("Supply low")


def _problem_words(problem: Problem) -> tuple[str, str]:
    full = (_STOPS | _WARNINGS)[problem]()
    return (_SHORT[problem]() if problem in _SHORT else full), full


def toner(checked: Checked | None, low: int) -> Cell:
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
    found = _COLOUR_WORDS.search(supply.name)
    if found:
        return {
            "black": _("Black"), "cyan": _("Cyan"), "magenta": _("Magenta"), "yellow": _("Yellow"),
        }[found[1].lower()]  # fmt: skip
    return _("Ink") if supply.kind is SupplyKind.INK else _("Toner")


def supply_color(supply: Supply) -> str:
    inks = themes.ink_colors()
    found = _COLOUR_WORDS.search(supply.name)
    if found:
        return inks[found[1].lower()]
    return inks["black"] if supply.kind in (SupplyKind.TONER, SupplyKind.INK) else inks["other"]


def supply_edge(supply: Supply) -> str:
    color = supply_color(supply)
    inks = themes.ink_colors()
    return inks["yellow_edge"] if color == inks["yellow"] else color


def level_text(supply: Supply) -> str:
    if supply.percent is not None:
        return _("{percent} %").format(percent=supply.percent)
    return _("some left") if supply.some_left else _("not reported")


def reports_level(supply: Supply) -> bool:
    return supply.percent is not None or supply.some_left


def no_level_text() -> str:
    return _("This printer doesn't report a level for this supply.")
