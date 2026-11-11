"""Which PCs let CapyPanel start a program on them, from a terminal, one PC after another:

    uv run python scripts/probe_remote_start.py hosts.txt
    uv run python scripts/probe_remote_start.py --wrapper hosts.txt

hosts.txt has one PC name or address per line (blank lines and lines starting with # are
skipped). Each PC is tried in turn, with a pause between them, as your own Windows account:

1. Can it be reached (file sharing's port)?
2. Does it start a plain program over WMI? It asks Windows on the PC to start ipconfig.exe
   with no arguments, which only prints the network settings and ends. Windows' answer is the
   column "wmi": 0 started, 2 access denied, 3 not allowed, 9 path not found.
3. With --wrapper, and only on a PC that answered 0: does CapyPanel's own wrapper run there?
   It runs the built-in "Refresh DNS" (ipconfig /flushdns and /registerdns) over WMI only. An
   antivirus that blocks the wrapper raises an alert for each PC where it does, so use it on a
   few PCs, not the whole list.

Nothing here starts PowerShell on your own PC. Each line is printed as it's done and the
results go to a CSV file beside hosts.txt (--out to name another), which holds host names:
keep it on this PC."""

import argparse
import csv
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from capypanel.core.remote import builtin, inventory, run, wmi
from capypanel.core.remote.access import RemoteError, check_reachable

PAUSE = 3.0  # seconds between PCs, so a long list never loads the network
WMI_TIMEOUT = 60.0
COLUMNS = ["host", "reachable", "wmi", "wrapper", "seconds", "detail"]


def start_plain(host: str) -> int:
    """Windows' answer to starting ipconfig.exe on `host` over WMI."""

    def reader(pc: wmi.Wmi, _values: Mapping[str, str]) -> Any:
        return int(pc.call("Win32_Process", "Create", CommandLine="ipconfig.exe").ReturnValue)

    return int(wmi.read(reader, host, None, {}, WMI_TIMEOUT))


def run_wrapper(host: str) -> tuple[str, str]:
    """("worked" or the problem, what each way said) for Refresh DNS through WMI only."""
    only_wmi = {run.Engine.WMI: lambda h, c, a, _j: run._start_cim(h, c, a, "Dcom")}
    runner = run.Runner(lambda: None, starters=only_wmi)
    try:
        result = runner.run(host, builtin.BUILT_IN["dns"].script)
    except run.RunError as e:
        return str(e.problem), "; ".join(e.tried) or e.detail
    except (RemoteError, OSError) as e:
        return "error", str(e)
    return ("worked" if result.worked else f"exit {result.exit_code}"), result.errors.strip()


def probe(host: str, wrapper: bool) -> dict[str, str]:
    began = time.monotonic()
    row = {"host": host, "reachable": "", "wmi": "", "wrapper": "", "detail": ""}
    try:
        check_reachable(host)
        row["reachable"] = "yes"
    except RemoteError:
        row["reachable"] = "no"
        row["seconds"] = f"{time.monotonic() - began:.1f}"
        return row
    try:
        row["wmi"] = str(start_plain(host))
    except (RemoteError, wmi.Unavailable, TimeoutError, OSError) as e:
        row["wmi"], row["detail"] = "error", str(e)
    if wrapper and row["wmi"] == "0":
        row["wrapper"], said = run_wrapper(host)
        row["detail"] = said[:300]
    row["seconds"] = f"{time.monotonic() - began:.1f}"
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("hosts", type=Path, help="a text file, one PC per line")
    parser.add_argument("--wrapper", action="store_true", help="also run CapyPanel's wrapper")
    parser.add_argument("--out", type=Path, help="where the CSV goes")
    given = parser.parse_args()
    hosts = [
        line.strip()
        for line in given.hosts.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    out = given.out or given.hosts.with_name(given.hosts.stem + "-results.csv")
    inventory.transport = inventory.DIRECT  # reads and starts from Python: no PowerShell here
    print(f"{len(hosts)} PCs, results in {out}")
    with out.open("w", newline="", encoding="utf-8-sig") as kept:
        writer = csv.DictWriter(kept, COLUMNS, delimiter=";")
        writer.writeheader()
        for n, host in enumerate(hosts):
            if n:
                time.sleep(PAUSE)
            row = probe(host, given.wrapper)
            writer.writerow(row)
            kept.flush()
            print(" | ".join(row.get(c, "") for c in COLUMNS), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
