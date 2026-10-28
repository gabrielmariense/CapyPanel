"""Try Refresh's reading on one real printer, from a terminal, before the window shows it:

    uv run python scripts/read_printer.py 192.0.2.5
    uv run python scripts/read_printer.py --public 192.0.2.5

It asks for the community string without showing it (--public uses "public" without asking,
for printers left on the default), reads the printer over SNMP (reading only, it never changes
anything) and prints what CapyPanel understood. The serial number is shown only as its length,
so the output can be shared without it."""

import getpass
import sys

from capypanel.core.printers import reading, snmp


def main() -> int:
    args = sys.argv[1:]
    public = "--public" in args
    args = [a for a in args if a != "--public"]
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
