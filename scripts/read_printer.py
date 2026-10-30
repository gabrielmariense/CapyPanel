"""Try Refresh's reading on one real printer, from a terminal, before the window shows it:

    uv run python scripts/read_printer.py 192.0.2.5
    uv run python scripts/read_printer.py --public 192.0.2.5
    uv run python scripts/read_printer.py --brand-data 192.0.2.5

It asks for the community string without showing it (--public uses "public" without asking,
for printers left on the default), reads the printer over SNMP (reading only, it never changes
anything) and prints what CapyPanel understood. The serial number is shown only as its length,
so the output can be shared without it.

--brand-data also prints what a Ricoh or Brother keeps in its own data area, as raw numbers,
to compare with the printer's web page before Refresh uses them."""

import getpass
import re
import sys

from capypanel.core.printers import reading, snmp

# Brand data areas checked by --brand-data (the brand's own objects, outside the standard ones).
RICOH_TONER = "1.3.6.1.4.1.367.3.2.1.2.24.1"  # ricohEngTonerTable, every column
RICOH_SERIAL = reading.RICOH_SERIAL
BROTHER_MAINTENANCE = reading.BROTHER_MAINTENANCE.removesuffix(".0")  # and anything beside it
# Brother record codes seen in published readers; the rest print as their code.
BROTHER_CODES = {0x41: "drum life", 0x6F: "black toner", 0x70: "cyan toner",
                 0x71: "magenta toner", 0x72: "yellow toner"}  # fmt: skip
# A word with digits in it might be a serial number: hidden like the printer's own.
_SERIAL_LIKE = re.compile(r"\b(?=\w*\d)\w{6,}\b")


def main() -> int:
    args = sys.argv[1:]
    public, brand_data = "--public" in args, "--brand-data" in args
    args = [a for a in args if a not in ("--public", "--brand-data")]
    if len(args) != 1:
        print(__doc__)
        return 2
    host = reading.snmp_host(args[0])
    community = "public" if public else getpass.getpass("Community string (not shown): ")
    community = community or "public"
    try:
        found = reading.read(host, community)
    except snmp.NoAnswer:
        print("No answer: the printer is off or unreachable, or the community string is wrong.")
        return 1
    except snmp.SnmpError as e:
        print(f"The printer's answer couldn't be read: {e}")
        return 1
    print(f"State:     {found.state.value} (device: {found.device.value})")
    print(f"Problems:  {', '.join(p.name.lower() for p in sorted(found.problems)) or 'none'}")
    print(f"Messages:  {' | '.join(found.messages) or 'none'}")
    print(f"Brand:     {found.brand or '?'}")
    print(f"Model:     {found.model or '?'}")
    print(f"Serial:    {f'{len(found.serial)} characters' if found.serial else '?'}")
    print(f"Pages:     {found.pages if found.pages is not None else '?'}")
    print(f"Supplies:  {len(found.supplies)}")
    for supply in found.supplies:
        level = (
            f"{supply.percent} %"
            if supply.percent is not None
            else ("some left" if supply.some_left else "unknown")
        )
        box = ", fills up" if supply.receptacle else ""
        print(f"  - {supply.kind.value:<6} {level:<10} {supply.name}{box}")
    if brand_data:
        try:
            show_brand_data(host, community, found.brand)
        except snmp.SnmpError as e:
            print(f"Brand data couldn't be read: {e}")
    return 0


def show_brand_data(host: str, community: str, brand: str) -> None:
    with snmp.Session(host, community) as session:
        if brand == "RICOH":
            serial = session.get([RICOH_SERIAL])[RICOH_SERIAL]
            length = len(serial) if isinstance(serial, bytes) else 0
            print(f"Ricoh serial:  {f'{length} characters' if length else '?'}")
            rows = session.walk(RICOH_TONER)
            print(f"Ricoh toner table: {len(rows)} values")
            for oid, value in rows:
                print(f"  {oid[len(RICOH_TONER) + 1 :]:<8} {shown(value)}")
        elif brand == "BROTHER":
            rows = session.walk(BROTHER_MAINTENANCE)
            print(f"Brother maintenance: {len(rows)} values")
            for _oid, value in rows:
                if not isinstance(value, bytes):
                    print(f"  {shown(value)}")
                    continue
                print(f"  raw: {value.hex(' ')}")
                for start in range(0, len(value) - 6, 7):
                    record = value[start : start + 7]
                    code, number = record[0], int.from_bytes(record[3:7], "big")
                    name = BROTHER_CODES.get(code, f"code {code:#04x}")
                    print(f"  {name:<14} {number:>8}  ({number / 100:g} if a %)")
        else:
            print(f"Brand data: nothing checked for {brand or 'this brand'}.")


def shown(value: snmp.Value) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode()
        except UnicodeDecodeError:
            return f"<{len(value)} bytes> {value.hex(' ')}"
    if isinstance(value, str):
        return repr(_SERIAL_LIKE.sub("<hidden>", value))
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
