"""Try Refresh's reading on one real printer, from a terminal, before the window shows it:

    uv run python scripts/read_printer.py 192.0.2.5
    uv run python scripts/read_printer.py --public 192.0.2.5
    uv run python scripts/read_printer.py --brand-data 192.0.2.5
    uv run python scripts/read_printer.py --v3 192.0.2.5

It asks for the community string without showing it (--public uses "public" without asking,
for printers left on the default), reads the printer over SNMP (reading only, it never changes
anything) and prints what CapyPanel understood. The serial number is shown only as its length,
and the MAC address only as its maker's half, so the output can be shared without them.

--v3 reads over SNMP v3 instead: it asks for the user, the authentication and encryption
types and their passwords (passwords not shown).

--brand-data also prints what a Ricoh or Brother keeps in its own data area, as raw numbers,
to compare with the printer's web page before Refresh uses them."""

import getpass
import re
import sys

from capypanel.core.printers import reading, snmp, usm

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
    public, brand_data, v3 = "--public" in args, "--brand-data" in args, "--v3" in args
    args = [a for a in args if a not in ("--public", "--brand-data", "--v3")]
    if len(args) != 1:
        print(__doc__)
        return 2
    host = reading.snmp_host(args[0])
    secret: snmp.Secret
    if v3:
        try:
            secret = ask_account()
        except ValueError as e:
            print(f"That account can't be used: {e}")
            return 2
    else:
        community = "public" if public else getpass.getpass("Community string (not shown): ")
        secret = community or "public"
    try:
        found = reading.read(host, secret)
    except snmp.NoAnswer:
        print("No answer: the printer is off or unreachable, or the community string is wrong.")
        return 1
    except snmp.Refused as e:
        print(f"The printer refused the SNMP v3 account ({e.reason}).")
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
    # The MAC's first half names the maker; the rest, like the serial, stays out of shared output.
    print(f"MAC:       {found.mac[:8] + ':xx:xx:xx' if found.mac else '?'}")
    print(f"Firmware:  {found.firmware or '?'}")
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
            show_brand_data(host, secret, found.brand)
        except snmp.SnmpError as e:
            print(f"Brand data couldn't be read: {e}")
    return 0


def ask_account() -> usm.Account:
    """The v3 account, typed in the terminal; passwords aren't shown."""
    user = input("User name: ").strip()
    auths = {a.label.upper(): a for a in usm.Auth}
    named = input(f"Authentication ({', '.join(a.label for a in usm.Auth)}, or none): ")
    auth = auths.get(named.strip().upper())
    if named.strip() and named.strip().lower() != "none" and auth is None:
        raise ValueError(f"unknown authentication {named.strip()!r}")
    auth_password = getpass.getpass("Authentication password (not shown): ") if auth else ""
    privacy = None
    if auth and input("Encryption (AES-128, or none): ").strip().upper() == "AES-128":
        privacy = usm.Privacy.AES128
    privacy_password = getpass.getpass("Encryption password (not shown): ") if privacy else ""
    return usm.Account(user, auth, auth_password, privacy, privacy_password)


def show_brand_data(host: str, secret: snmp.Secret, brand: str) -> None:
    with snmp.Session(host, secret) as session:
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
