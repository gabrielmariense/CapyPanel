"""What Refresh reads from a printer over SNMP: its status and the printer's own error
messages, each supply's level, the page counter, and its brand, model and serial number.

It comes from the standard printer objects (Host Resources, Printer MIB and Entity MIB), which
printers of every brand answer. Only where those leave a gap (a level with no %, an empty
serial) does it also read a brand's own data, for the brands in _BRAND_DATA, each checked
against a real printer's web page first. What a printer doesn't answer is left empty."""

import dataclasses
import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from urllib.parse import urlsplit

from capypanel.core.printers import snmp

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3"  # .<device index>
HR_DEVICE_STATUS = "1.3.6.1.2.1.25.3.2.1.5"
HR_PRINTER_STATUS = "1.3.6.1.2.1.25.3.5.1.1"
HR_PRINTER_ERRORS = "1.3.6.1.2.1.25.3.5.1.2"
SERIAL_NUMBER = "1.3.6.1.2.1.43.5.1.1.17"  # prtGeneralSerialNumber
ENTITY_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"  # entPhysicalSerialNum: where some brands put it
MARKERS = "1.3.6.1.2.1.43.10.2.1"  # prtMarkerTable: what each marker counts, and in what unit
LIFE_COUNT = f"{MARKERS}.4"  # prtMarkerLifeCount
SUPPLIES = "1.3.6.1.2.1.43.11.1.1"  # prtMarkerSuppliesTable
ALERTS = "1.3.6.1.2.1.43.18.1.1"  # prtAlertTable

# Columns of the supplies table, and of the alerts table.
_CLASS, _TYPE, _DESCRIPTION, _MAX, _LEVEL = 4, 5, 6, 8, 9
_SEVERITY, _ALERT_TEXT = 2, 8
_COUNTER_UNIT, _LIFE_COUNT = 3, 4
_PAGE_UNITS = {7, 8}  # impressions, sheets (others count distance or time, not pages)
_RECEPTACLE = 4  # prtMarkerSuppliesClass: a box that fills up (waste toner), not one that empties
_SOME_LEFT = -3  # a level the printer can't measure, but it says there's some left
_SERIOUS = {3, 4}  # alert severities: critical, warning (others are just information)

# Brands by the maker's number in the printer's sysObjectID (1.3.6.1.4.1.<number>...).
_MAKERS = {
    11: "HP", 236: "SAMSUNG", 253: "XEROX", 367: "RICOH", 641: "LEXMARK", 1248: "EPSON",
    1347: "KYOCERA", 1602: "CANON", 2435: "BROTHER", 10642: "ZEBRA",
}  # fmt: skip
_ENTERPRISES = "1.3.6.1.4.1."

# Brands' own data, read only to fill a gap the standard objects leave.
RICOH_SERIAL = "1.3.6.1.4.1.367.3.2.1.2.1.4.0"  # ricohEngSerialNumber
RICOH_TONER = "1.3.6.1.4.1.367.3.2.1.2.24.1.1"  # ricohEngTonerEntry
_RICOH_COLOUR, _RICOH_LEVEL = 2, 5  # its level: a %, or below 0 for "some left", "unknown"...
BROTHER_MAINTENANCE = "1.3.6.1.4.1.2435.2.3.9.4.2.1.5.5.8.0"  # brInfoMaintenance
# brInfoMaintenance is 7-byte records: a code, two bytes, then the value in hundredths of a %.
_BROTHER_LEVELS = {0x6F: "black", 0x70: "cyan", 0x71: "magenta", 0x72: "yellow", 0x41: "drum"}
_BRAND_DATA = {"RICOH", "BROTHER"}
_COLOURS = re.compile(r"\b(black|cyan|magenta|yellow)\b", re.IGNORECASE)


class State(StrEnum):
    """What the printer says it's doing (hrPrinterStatus)."""

    IDLE = "idle"
    PRINTING = "printing"
    WARMING_UP = "warming-up"
    OTHER = "other"  # a state it doesn't name, often an error shown on its panel
    UNKNOWN = "unknown"


_STATES = {1: State.OTHER, 2: State.UNKNOWN, 3: State.IDLE, 4: State.PRINTING, 5: State.WARMING_UP}


class Device(StrEnum):
    """How the printer rates itself as a device (hrDeviceStatus). Many printers say "other"
    as their state while running fine: this tells that apart from a stopped one."""

    RUNNING = "running"
    WARNING = "warning"
    TESTING = "testing"
    DOWN = "down"
    UNKNOWN = "unknown"


_DEVICES = {1: Device.UNKNOWN, 2: Device.RUNNING, 3: Device.WARNING, 4: Device.TESTING,
            5: Device.DOWN}  # fmt: skip


class Problem(IntEnum):
    """The printer's detected errors (hrPrinterDetectedErrorState), by bit number."""

    LOW_PAPER = 0
    NO_PAPER = 1
    LOW_TONER = 2
    NO_TONER = 3
    DOOR_OPEN = 4
    JAMMED = 5
    OFFLINE = 6
    SERVICE_REQUESTED = 7
    INPUT_TRAY_MISSING = 8
    OUTPUT_TRAY_MISSING = 9
    SUPPLY_MISSING = 10
    OUTPUT_NEAR_FULL = 11
    OUTPUT_FULL = 12
    INPUT_TRAY_EMPTY = 13
    MAINTENANCE_OVERDUE = 14


class SupplyKind(StrEnum):
    TONER = "toner"
    INK = "ink"
    DRUM = "drum"
    WASTE = "waste"  # a waste toner or ink box
    OTHER = "other"  # fuser, transfer unit, staples...


_KINDS = {
    3: SupplyKind.TONER, 21: SupplyKind.TONER, 5: SupplyKind.INK, 6: SupplyKind.INK,
    9: SupplyKind.DRUM, 4: SupplyKind.WASTE, 8: SupplyKind.WASTE, 14: SupplyKind.WASTE,
    24: SupplyKind.WASTE,
}  # fmt: skip


@dataclass(frozen=True)
class Supply:
    name: str  # as the printer calls it, e.g. "Black Toner Cartridge"
    kind: SupplyKind
    percent: int | None  # what's left, 0 to 100; for a waste box, the room left; None: unknown
    some_left: bool = False  # no percent, but the printer says it isn't empty
    receptacle: bool = False  # it fills up (a waste box) instead of running out

    def low(self, at_or_below: int) -> bool:
        """Running low (or, for a waste box, nearly full)."""
        return self.percent is not None and self.percent <= at_or_below


@dataclass(frozen=True)
class Reading:
    state: State = State.UNKNOWN
    device: Device = Device.UNKNOWN
    problems: frozenset[Problem] = frozenset()
    messages: tuple[str, ...] = ()  # the printer's own words for what's wrong, e.g. "Paper jam"
    supplies: tuple[Supply, ...] = ()
    pages: int | None = None  # the total page counter
    brand: str = ""
    model: str = ""
    serial: str = ""


def snmp_host(address: str) -> str:
    """The host part of a printer's address: no https://, port, path or IPv6 brackets."""
    text = address.strip()
    bare = text.split("://", 1)[-1]
    if bare.count(":") > 1 and not bare.startswith("["):  # a bare IPv6 address
        return bare.split("/", 1)[0]
    try:
        host = urlsplit(text if "://" in text else f"//{text}").hostname
    except ValueError:
        host = None
    return host or bare.split("/", 1)[0]


def read(
    host: str, secret: snmp.Secret, *, port: int = snmp.PORT, timeout: float = snmp.TIMEOUT
) -> Reading:
    """Everything Refresh shows. Raises snmp.NoAnswer when the printer doesn't answer, and
    snmp.Refused when it refuses a v3 account."""
    with snmp.Session(host, secret, port=port, timeout=timeout) as session:
        top = session.get([SYS_DESCR, SYS_OBJECT_ID])
        printers = session.walk(HR_PRINTER_STATUS)
        device = printers[0][0].rsplit(".", 1)[1] if printers else "1"
        status = _number(printers[0][1]) if printers else None
        details = session.get([
            f"{HR_DEVICE_DESCR}.{device}",
            f"{HR_DEVICE_STATUS}.{device}",
            f"{HR_PRINTER_ERRORS}.{device}",
        ])  # fmt: skip
        description = _text(details[f"{HR_DEVICE_DESCR}.{device}"]) or _text(top[SYS_DESCR])
        brand = _brand(top[SYS_OBJECT_ID], description)
        serial = _first_text(session.walk(SERIAL_NUMBER))
        if not serial:
            serial = _first_text(session.walk(ENTITY_SERIAL))
        if not serial and brand == "RICOH":
            serial = _text(session.get([RICOH_SERIAL])[RICOH_SERIAL])
        supplies = _supplies(session.walk(SUPPLIES))
        if brand in _BRAND_DATA and any(_key(s) and s.percent is None for s in supplies):
            supplies = _filled(supplies, _brand_levels(session, brand))
        markers = session.walk(MARKERS)
        alerts = session.walk(ALERTS)
    device_status = _number(details[f"{HR_DEVICE_STATUS}.{device}"])
    return Reading(
        state=_STATES.get(status, State.UNKNOWN) if status is not None else State.UNKNOWN,
        device=_DEVICES.get(device_status, Device.UNKNOWN) if device_status else Device.UNKNOWN,
        problems=_problems(details[f"{HR_PRINTER_ERRORS}.{device}"]),
        messages=_messages(alerts),
        supplies=supplies,
        pages=_pages(markers),
        brand=brand,
        model=_model(description, brand),
        serial=serial,
    )


def _number(value: snmp.Value) -> int | None:
    return value if isinstance(value, int) else None


def _text(value: snmp.Value) -> str:
    """An OCTET STRING as text: UTF-8 when it is, else Latin-1 (older printers); no NULs."""
    if not isinstance(value, bytes):
        return ""
    try:
        text = value.decode()
    except UnicodeDecodeError:
        text = value.decode("latin-1")
    return " ".join(text.replace("\x00", " ").split())


def _first_text(rows: list[tuple[str, snmp.Value]]) -> str:
    return next((t for _oid, v in rows if (t := _text(v))), "")


def _brand(object_id: snmp.Value, description: str) -> str:
    if isinstance(object_id, str) and object_id.startswith(_ENTERPRISES):
        maker = object_id[len(_ENTERPRISES) :].split(".", 1)[0]
        if maker.isdigit() and int(maker) in _MAKERS:
            return _MAKERS[int(maker)]
    first = description.split(" ", 1)[0].upper()
    return first if first in _MAKERS.values() else ""


def _model(description: str, brand: str) -> str:
    """The device's description without the brand at its start ("HP LaserJet M404" → the rest)."""
    if brand and description.upper().startswith(brand + " "):
        description = description[len(brand) + 1 :]
    return description.split(";", 1)[0].strip()  # some add ";" and firmware details


def _problems(value: snmp.Value) -> frozenset[Problem]:
    if not isinstance(value, bytes):
        return frozenset()
    found = set()
    for problem in Problem:
        byte, bit = divmod(problem.value, 8)
        if byte < len(value) and value[byte] & (0x80 >> bit):
            found.add(problem)
    return frozenset(found)


def _table(rows: list[tuple[str, snmp.Value]], base: str) -> dict[str, dict[int, snmp.Value]]:
    """A table's rows by index (what follows the column number), each a {column: value}."""
    table: dict[str, dict[int, snmp.Value]] = {}
    for oid, value in rows:
        column, _, index = oid[len(base) + 1 :].partition(".")
        if column.isdigit() and index:
            table.setdefault(index, {})[int(column)] = value
    return table


def _pages(rows: list[tuple[str, snmp.Value]]) -> int | None:
    """The page counter: the highest marker counting pages. A marker that says it counts
    something else (distance, hours) is left out; one that doesn't say counts."""
    counted = []
    for row in _table(rows, MARKERS).values():
        count, unit = _number(row.get(_LIFE_COUNT)), _number(row.get(_COUNTER_UNIT))
        if count is not None and count >= 0 and (unit is None or unit in _PAGE_UNITS):
            counted.append(count)
    return max(counted) if counted else None


# A supply's own chip serial some printers add to its name ("Black Toner S/N:CRUM-...").
_CHIP_SERIAL = re.compile(r"\s*\bS/?N\s*:\s*\S+", re.IGNORECASE)


def _supplies(rows: list[tuple[str, snmp.Value]]) -> tuple[Supply, ...]:
    found = []
    for row in _table(rows, SUPPLIES).values():
        kind_number = _number(row.get(_TYPE))
        kind = _KINDS.get(kind_number, SupplyKind.OTHER) if kind_number else SupplyKind.OTHER
        level, most = _number(row.get(_LEVEL)), _number(row.get(_MAX))
        percent = None
        if level is not None and most and most > 0 and level >= 0:
            percent = max(0, min(100, round(level * 100 / most)))
        name = _CHIP_SERIAL.sub("", _text(row.get(_DESCRIPTION))).strip() or kind.value
        found.append(
            Supply(
                name=name,
                kind=kind,
                percent=percent,
                some_left=level == _SOME_LEFT,
                receptacle=_number(row.get(_CLASS)) == _RECEPTACLE,
            )
        )
    return tuple(found)


def _key(supply: Supply) -> str:
    """What a brand's own data calls this supply: its colour, or "drum"; "" for others. A toner
    whose name says no colour is black (a black-only printer's "Toner Cartridge")."""
    if supply.kind is SupplyKind.DRUM:
        return "drum"
    if supply.kind in (SupplyKind.TONER, SupplyKind.INK):
        found = _COLOURS.search(supply.name)
        return found[1].lower() if found else "black"
    return ""


def _filled(supplies: tuple[Supply, ...], levels: dict[str, int]) -> tuple[Supply, ...]:
    """Each supply with no % given the brand's own level for it, when there is one."""
    return tuple(
        dataclasses.replace(s, percent=levels[key])
        if s.percent is None and (key := _key(s)) in levels
        else s
        for s in supplies
    )


def _brand_levels(session: snmp.Session, brand: str) -> dict[str, int]:
    """The % left of each toner (by colour) and the drum, from the brand's own data."""
    levels: dict[str, int] = {}
    if brand == "RICOH":
        for row in _table(session.walk(RICOH_TONER), RICOH_TONER).values():
            colour, level = _text(row.get(_RICOH_COLOUR)).lower(), _number(row.get(_RICOH_LEVEL))
            if _COLOURS.fullmatch(colour) and level is not None and 0 <= level <= 100:
                levels[colour] = level
    elif brand == "BROTHER":
        data = session.get([BROTHER_MAINTENANCE])[BROTHER_MAINTENANCE]
        if isinstance(data, bytes):
            for start in range(0, len(data) - 6, 7):
                key = _BROTHER_LEVELS.get(data[start])
                hundredths = int.from_bytes(data[start + 3 : start + 7], "big")
                if key and hundredths <= 10_000:
                    levels[key] = round(hundredths / 100)
    return levels


def _messages(rows: list[tuple[str, snmp.Value]]) -> tuple[str, ...]:
    """The printer's own words for its current warnings and errors, each once."""
    seen: dict[str, None] = {}
    for row in _table(rows, ALERTS).values():
        if _number(row.get(_SEVERITY)) in _SERIOUS and (text := _text(row.get(_ALERT_TEXT))):
            seen[text] = None
    return tuple(seen)
