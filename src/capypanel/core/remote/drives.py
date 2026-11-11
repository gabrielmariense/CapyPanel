"""The network drives of the people signed in to a PC.

They're read from your PC over WMI's registry provider: each signed-in person's Network key,
the drives that come back at every sign-in, with nothing run on the PC."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from capypanel.core.remote import inventory
from capypanel.core.remote.access import Account, check_reachable


@dataclass(frozen=True)
class Drive:
    letter: str  # "S:"
    path: str  # \\FS01\Setores


@dataclass(frozen=True)
class Person:
    user: str
    domain: str
    drives: tuple[Drive, ...]


def saved_drives(host: str, account: Account | None = None) -> list[Person]:
    """Everyone signed in to `host` and the drives saved for them, by letter. A person with
    none is listed too. Raises RemoteError or TimeoutError."""
    from capypanel.core.remote import inventory  # its PowerShell parts load on first use

    check_reachable(host)
    found = inventory.run_cim(_SAVED, host, account)
    people = [
        Person(str(p.get("user") or ""), str(p.get("domain") or ""), _drives(p.get("drives")))
        for p in (found if isinstance(found, list) else [found])
        if isinstance(p, dict) and p.get("user")
    ]
    return sorted(people, key=lambda p: p.user.casefold())


def _drives(found: object) -> tuple[Drive, ...]:
    rows = found if isinstance(found, list) else [found] if isinstance(found, dict) else []
    listed = (Drive(_letter(d.get("letter")), str(d.get("path") or "")) for d in rows)
    return tuple(sorted((d for d in listed if d.letter), key=lambda d: d.letter))


def _letter(value: object) -> str:
    """The registry names a drive "S"; everything else says "S:"."""
    text = str(value or "").strip().rstrip(":").upper()
    return f"{text}:" if text else ""


# HKEY_USERS holds a hive for everyone signed in (and for services). A signed-in person's hive
# has Volatile Environment, with their name; their saved drives are under Network\<letter>.
_SAVED = r"""
$HKU = [uint32]2147483651
function UReg($method, $key, $name) {
  $a = @{hDefKey = $HKU; sSubKeyName = $key}
  if ($name) { $a.sValueName = $name }
  Invoke-CimMethod -CimSession $session -Namespace root/default -ClassName StdRegProv `
    -MethodName $method -Arguments $a
}
try {
  $found = New-Object System.Collections.ArrayList
  $sids = (UReg EnumKey '').sNames
  foreach ($sid in @($sids)) {
    if ($sid -notmatch '^S-1-5-21-[\d-]+$') { continue }
    $user = (UReg GetStringValue "$sid\Volatile Environment" USERNAME).sValue
    if (-not $user) { continue }
    $domain = (UReg GetStringValue "$sid\Volatile Environment" USERDOMAIN).sValue
    $drives = New-Object System.Collections.ArrayList
    $letters = (UReg EnumKey "$sid\Network").sNames
    foreach ($letter in @($letters)) {
      if (-not $letter) { continue }
      $path = (UReg GetStringValue "$sid\Network\$letter" RemotePath).sValue
      [void]$drives.Add(@{letter = $letter; path = $path})
    }
    [void]$found.Add(@{user = $user; domain = $domain; drives = @($drives)})
  }
  Send @($found)
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""


# ---- the person's session ----

_PERSON_HIVE = re.compile(r"S-1-5-21-[\d-]+")


@inventory.reads(_SAVED)
def _saved_direct(wmi: Any, _values: Mapping[str, str]) -> list[dict[str, Any]]:
    from capypanel.core.remote.wmi import HKU

    found = []
    for sid in wmi.subkeys(HKU, ""):
        if not _PERSON_HIVE.fullmatch(sid):
            continue
        user = wmi.string(HKU, f"{sid}\\Volatile Environment", "USERNAME")
        if not user:
            continue
        domain = wmi.string(HKU, f"{sid}\\Volatile Environment", "USERDOMAIN")
        drives = [
            {"letter": letter,
             "path": wmi.string(HKU, f"{sid}\\Network\\{letter}", "RemotePath")}
            for letter in wmi.subkeys(HKU, f"{sid}\\Network")
        ]  # fmt: skip
        found.append({"user": user, "domain": domain, "drives": drives})
    return found
