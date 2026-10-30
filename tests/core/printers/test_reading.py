import pytest
from snmp_agent import Objects, running

from capypanel.core.printers import reading, snmp
from capypanel.core.printers.reading import Device, Problem, State, SupplyKind

S = reading.SUPPLIES
A = reading.ALERTS


def _supply(index: str, cls: int, kind: int, name: bytes, most: int, level: int) -> Objects:
    return {
        f"{S}.4.{index}": cls,
        f"{S}.5.{index}": kind,
        f"{S}.6.{index}": name,
        f"{S}.8.{index}": most,
        f"{S}.9.{index}": level,
    }


# An invented colour laser printer: four toners, a drum, a waste box, a jam and an open door.
COLOUR: Objects = {
    reading.SYS_DESCR: b"SAMPLE Color LaserJet; firmware 1.0",
    reading.SYS_OBJECT_ID: "1.3.6.1.4.1.11.2.3.9.1",
    f"{reading.HR_DEVICE_DESCR}.1": b"HP Color LaserJet SAMPLE-M479",
    f"{reading.HR_PRINTER_STATUS}.1": 1,  # other: stopped by an error
    f"{reading.HR_DEVICE_STATUS}.1": 5,  # down
    f"{reading.HR_PRINTER_ERRORS}.1": bytes([0b00001100, 0x00]),  # door open, jammed
    f"{reading.SERIAL_NUMBER}.1": b"SAMPLE0001",
    f"{reading.MARKERS}.3.1.1": 7,  # impressions
    f"{reading.LIFE_COUNT}.1.1": snmp.counter(48_213),
    f"{reading.MARKERS}.3.1.2": 3,  # ten-thousandths of an inch: not pages
    f"{reading.LIFE_COUNT}.1.2": snmp.counter(990_000_000),
    **_supply("1.1", 3, 21, b"Black Cartridge S/N:CRUM-SAMPLE0001", 7500, 3000),
    **_supply("1.2", 3, 21, b"Cyan Cartridge", 6000, 600),
    **_supply("1.3", 3, 21, b"Magenta Cartridge", 6000, -3),
    **_supply("1.4", 3, 21, b"Yellow Cartridge\x00\x00", 6000, -2),
    **_supply("1.5", 3, 9, b"Imaging Drum", 100, 80),
    **_supply("1.6", 4, 4, b"Toner Collection Unit", 100, 5),
    f"{A}.2.1.1": 3,
    f"{A}.8.1.1": b"Paper  jam in tray 2",
    f"{A}.2.1.2": 4,
    f"{A}.8.1.2": b"Front door open",
    f"{A}.2.1.3": 1,  # just information: not shown
    f"{A}.8.1.3": b"Sleep mode on",
    f"{A}.2.1.4": 3,
    f"{A}.8.1.4": b"Paper jam in tray 2",  # said twice: shown once
}


def _read(objects: Objects) -> reading.Reading:
    with running(objects) as agent:
        return reading.read("127.0.0.1", "public", port=agent.port)


def test_a_colour_printer_with_problems() -> None:
    found = _read(COLOUR)
    assert found.state is State.OTHER and found.device is Device.DOWN
    assert found.problems == {Problem.DOOR_OPEN, Problem.JAMMED}
    assert found.messages == ("Paper jam in tray 2", "Front door open")
    assert (found.brand, found.model, found.serial) == (
        "HP",
        "Color LaserJet SAMPLE-M479",
        "SAMPLE0001",
    )
    assert found.pages == 48_213  # the marker counting impressions, not the one in inches
    by_name = {s.name: s for s in found.supplies}
    assert list(by_name) == [
        "Black Cartridge",
        "Cyan Cartridge",
        "Magenta Cartridge",
        "Yellow Cartridge",
        "Imaging Drum",
        "Toner Collection Unit",
    ]  # fmt: skip  (the toner chip's serial is left out of its name)
    assert by_name["Black Cartridge"].percent == 40
    assert by_name["Cyan Cartridge"].low(10) and not by_name["Black Cartridge"].low(10)
    magenta, yellow = by_name["Magenta Cartridge"], by_name["Yellow Cartridge"]
    assert magenta.percent is None and magenta.some_left and not magenta.low(10)
    assert yellow.percent is None and not yellow.some_left
    assert by_name["Imaging Drum"].kind is SupplyKind.DRUM
    waste = by_name["Toner Collection Unit"]
    assert waste.kind is SupplyKind.WASTE and waste.receptacle and waste.low(10)  # nearly full


def test_a_printer_that_answers_little_still_reads() -> None:
    found = _read(
        {reading.SYS_DESCR: b"Brother HL-SAMPLE series", f"{reading.HR_PRINTER_STATUS}.1": 3}
    )
    assert found.state is State.IDLE
    assert (found.brand, found.model) == ("BROTHER", "HL-SAMPLE series")  # from the description
    assert found.supplies == () and found.pages is None and found.serial == ""
    assert found.device is Device.UNKNOWN


def test_a_running_printer_that_calls_its_state_other_and_keeps_its_serial_elsewhere() -> None:
    found = _read({
        reading.SYS_OBJECT_ID: "1.3.6.1.4.1.367.1.1",
        f"{reading.HR_DEVICE_DESCR}.1": b"SAMPLE 3700",
        f"{reading.HR_PRINTER_STATUS}.1": 1,
        f"{reading.HR_DEVICE_STATUS}.1": 2,
        f"{reading.ENTITY_SERIAL}.1": b"SAMPLE0002",
        f"{reading.LIFE_COUNT}.1.1": snmp.counter(1_234),  # no unit given: counted as pages
    })  # fmt: skip
    assert (found.state, found.device) == (State.OTHER, Device.RUNNING)
    assert (found.brand, found.serial, found.pages) == ("RICOH", "SAMPLE0002", 1_234)


RT = reading.RICOH_TONER


def test_a_ricoh_fills_its_toner_level_and_serial_from_its_own_data() -> None:
    found = _read({
        reading.SYS_OBJECT_ID: "1.3.6.1.4.1.367.1.1",
        f"{reading.HR_PRINTER_STATUS}.1": 3,
        **_supply("1.1", 3, 21, b"Black Cartridge", -2, -2),  # the standard level: unknown
        reading.RICOH_SERIAL: b"SAMPLE0004",
        f"{RT}.2.1": b"Black",
        f"{RT}.5.1": 70,
    })  # fmt: skip
    assert found.serial == "SAMPLE0004"
    assert [(s.name, s.percent) for s in found.supplies] == [("Black Cartridge", 70)]


def test_a_brother_fills_only_the_levels_the_standard_objects_leave_out() -> None:
    records = bytes.fromhex("63010400000001 41010400002328 6f010400002454 81010400000064")
    found = _read({
        reading.SYS_OBJECT_ID: "1.3.6.1.4.1.2435.2.3.9.1",
        f"{reading.HR_PRINTER_STATUS}.1": 3,
        **_supply("1.1", 3, 3, b"Black Toner Cartridge", 100, -3),  # some left, no %
        **_supply("1.2", 3, 9, b"Drum Unit", 100, 98),
        reading.BROTHER_MAINTENANCE: records,  # drum 90 %, black toner 93 %
    })  # fmt: skip
    levels = {s.name: (s.percent, s.some_left) for s in found.supplies}
    assert levels == {"Black Toner Cartridge": (93, True), "Drum Unit": (98, False)}


def test_brand_data_is_left_alone_when_the_standard_levels_are_there() -> None:
    found = _read({
        reading.SYS_OBJECT_ID: "1.3.6.1.4.1.367.1.1",
        **_supply("1.1", 3, 21, b"Black Cartridge", 100, 55),
        f"{RT}.2.1": b"Black",
        f"{RT}.5.1": 70,
    })  # fmt: skip
    assert found.supplies[0].percent == 55


def test_a_printer_that_does_not_answer_raises_no_answer() -> None:
    with running(COLOUR, community=b"other") as agent, pytest.raises(snmp.NoAnswer):
        reading.read("127.0.0.1", "public", port=agent.port, timeout=0.2)


@pytest.mark.parametrize(
    ("address", "host"),
    [
        ("192.0.2.5", "192.0.2.5"),
        ("https://192.0.2.5", "192.0.2.5"),
        ("HTTPS://prn-01.example.com:8443/hp/device", "prn-01.example.com"),
        ("prn-01", "prn-01"),
        ("2001:db8::5", "2001:db8::5"),
        ("[2001:db8::5]", "2001:db8::5"),
        ("https://[2001:db8::5]:443", "2001:db8::5"),
    ],
)
def test_snmp_uses_only_the_host_of_an_address(address: str, host: str) -> None:
    assert reading.snmp_host(address) == host
