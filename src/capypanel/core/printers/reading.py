"""What Refresh reads from a printer over SNMP: its status and the printer's own error
messages, each supply's level, the page counter, and its brand, model and serial number.

All of it comes from the standard printer objects (Host Resources and Printer MIB), which
printers of every brand answer, so nothing here is tuned to one maker. What a printer doesn't
answer is left empty."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from urllib.parse import urlsplit

from capypanel.core.printers import snmp

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
HR_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3"  # .<device index>
HR_PRINTER_STATUS = "1.3.6.1.2.1.25.3.5.1.1"
HR_PRINTER_ERRORS = "1.3.6.1.2.1.25.3.5.1.2"
SERIAL_NUMBER = "1.3.6.1.2.1.43.5.1.1.17"  # prtGeneralSerialNumber
LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4"  # prtMarkerLifeCount: pages printed, per marker
SUPPLIES = "1.3.6.1.2.1.43.11.1.1"  # prtMarkerSuppliesTable
ALERTS = "1.3.6.1.2.1.43.18.1.1"  # prtAlertTable

# Columns of the supplies table, and of the alerts table.
_CLASS, _TYPE, _DESCRIPTION, _MAX, _LEVEL = 4, 5, 6, 8, 9
_SEVERITY, _ALERT_TEXT = 2, 8
_RECEPTACLE = 4  # prtMarkerSuppliesClass: a box that fills up (waste toner), not one that empties
_SOME_LEFT = -3  # a level the printer can't measure, but it says there's some left
_SERIOUS = {3, 4}  # alert severities: critical, warning (others are just information)

# Brands by the maker's number in the printer's sysObjectID (1.3.6.1.4.1.<number>...).
_MAKERS = {
    11: "HP", 236: "SAMSUNG", 253: "XEROX", 367: "RICOH", 641: "LEXMARK", 1248: "EPSON",
    1347: "KYOCERA", 1602: "CANON", 2435: "BROTHER", 10642: "ZEBRA",
}  # fmt: skip
_ENTERPRISES = "1.3.6.1.4.1."


class State(StrEnum):
    """What the printer says it's doing (hrPrinterStatus)."""

    IDLE = "idle"
    PRINTING = "printing"
    WARMING_UP = "warming-up"
    OTHER = "other"  # a state it doesn't name, often an error shown on its panel
    UNKNOWN = "unknown"


_STATES = {1: State.OTHER, 2: State.UNKNOWN, 3: State.IDLE, 4: State.PRINTING, 5: State.WARMING_UP}


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
    host: str, community: str, *, port: int = snmp.PORT, timeout: float = snmp.TIMEOUT
) -> Reading:
    """Everything Refresh shows. Raises snmp.NoAnswer when the printer doesn't answer."""
    with snmp.Session(host, community, port=port, timeout=timeout) as session:
        top = session.get([SYS_DESCR, SYS_OBJECT_ID])
        printers = session.walk(HR_PRINTER_STATUS)
        device = printers[0][0].rsplit(".", 1)[1] if printers else "1"
        status = _number(printers[0][1]) if printers else None
        details = session.get([
            f"{HR_DEVICE_DESCR}.{device}",
            f"{HR_PRINTER_ERRORS}.{device}",
        ])  # fmt: skip
        serials = session.walk(SERIAL_NUMBER)
        supplies = session.walk(SUPPLIES)
        counters = session.walk(LIFE_COUNT)
        alerts = session.walk(ALERTS)
    description = _text(details[f"{HR_DEVICE_DESCR}.{device}"]) or _text(top[SYS_DESCR])
    brand = _brand(top[SYS_OBJECT_ID], description)
    pages = [n for _oid, value in counters if (n := _number(value)) is not None and n >= 0]
    return Reading(
        state=_STATES.get(status, State.UNKNOWN) if status is not None else State.UNKNOWN,
        problems=_problems(details[f"{HR_PRINTER_ERRORS}.{device}"]),
        messages=_messages(alerts),
        supplies=_supplies(supplies),
        pages=max(pages) if pages else None,
        brand=brand,
        model=_model(description, brand),
        serial=next((t for _oid, v in serials if (t := _text(v))), ""),
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


def _supplies(rows: list[tuple[str, snmp.Value]]) -> tuple[Supply, ...]:
    found = []
    for row in _table(rows, SUPPLIES).values():
        kind_number = _number(row.get(_TYPE))
        kind = _KINDS.get(kind_number, SupplyKind.OTHER) if kind_number else SupplyKind.OTHER
        level, most = _number(row.get(_LEVEL)), _number(row.get(_MAX))
        percent = None
        if level is not None and most and most > 0 and level >= 0:
            percent = max(0, min(100, round(level * 100 / most)))
        name = _text(row.get(_DESCRIPTION)) or kind.value
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


def _messages(rows: list[tuple[str, snmp.Value]]) -> tuple[str, ...]:
    """The printer's own words for its current warnings and errors, each once."""
    seen: dict[str, None] = {}
    for row in _table(rows, ALERTS).values():
        if _number(row.get(_SEVERITY)) in _SERIOUS and (text := _text(row.get(_ALERT_TEXT))):
            seen[text] = None
    return tuple(seen)
