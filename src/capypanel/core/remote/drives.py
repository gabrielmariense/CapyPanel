"""The network drives of the people signed in to a PC, mapping one for them, and clearing their
Teams and browser caches.

Two lists answer "which drives does ana have". The saved one is read from your PC over WMI's
registry provider: each signed-in person's Network key, the drives that come back at every
sign-in, with nothing run on the PC. The live one comes from the person's own session (a script
run as them, core.remote.run's RunAs.USER): every drive they have now, mapped only for this
session too, and whether it's connected. Mapping runs as the person for the same reason: a drive
mapped as the admin lands in the admin's session, where they never see it."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from capypanel.core.remote.access import Account, check_reachable
from capypanel.core.remote.run import TIMEOUT, Language, RunAs, RunError, Script

if TYPE_CHECKING:
    from capypanel.core.remote.run import Runner


@dataclass(frozen=True)
class Drive:
    letter: str  # "S:"
    path: str  # \\FS01\Setores
    status: str = ""  # from the session only: "OK", "Unavailable", "Disconnected"…


@dataclass(frozen=True)
class Person:
    user: str
    domain: str
    drives: tuple[Drive, ...]

    @property
    def account(self) -> str:
        """ "EXAMPLE\\ana", as Run as the person needs it."""
        return f"{self.domain}\\{self.user}" if self.domain else self.user


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

_LIVE = r"""
$ErrorActionPreference = 'Stop'
try {
  foreach ($m in @(Get-SmbMapping)) {
    if ($m.LocalPath) { "CAPYPANEL-DRIVE`t$($m.LocalPath)`t$($m.RemotePath)`t$($m.Status)" }
  }
} catch {
  foreach ($d in @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 4')) {
    $state = if (Test-Path -LiteralPath "$($d.DeviceID)\") { 'OK' } else { 'Unavailable' }
    "CAPYPANEL-DRIVE`t$($d.DeviceID)`t$($d.ProviderName)`t$state"
  }
}
"""

LIVE_SCRIPT = Script("Mapped drives (session)", Language.POWERSHELL, _LIVE.lstrip("\n").encode())

_FIELD = r"\t([^\t\n]*)"
_DRIVE_LINE = re.compile(rf"^CAPYPANEL-DRIVE{_FIELD}{_FIELD}{_FIELD}$", re.MULTILINE)


def live_drives(output: str) -> list[Drive]:
    """The drives the session check found, by letter."""
    found = [Drive(_letter(m[1]), m[2].strip(), m[3].strip()) for m in _DRIVE_LINE.finditer(output)]
    return sorted((d for d in found if d.letter), key=lambda d: d.letter)


def connected(drive: Drive) -> bool:
    return drive.status == "OK"


@dataclass(frozen=True)
class Checked:
    """What each person's session said: their drives now, or why it couldn't be asked."""

    live: dict[str, tuple[Drive, ...]]  # by Person.account, case-folded
    failed: dict[str, BaseException]


def check_sessions(
    runs: "Runner", host: str, people: Sequence[Person], account: Account | None = None
) -> Checked:
    """Runs the session check as each person in turn. Raises RemoteError when the PC can't be
    reached or the account isn't accepted; a run that fails for one person is kept in
    `failed` and the others still go."""
    live: dict[str, tuple[Drive, ...]] = {}
    failed: dict[str, BaseException] = {}
    for person in people:
        key = person.account.casefold()
        try:
            result = runs.run(host, LIVE_SCRIPT, account, TIMEOUT, RunAs.USER, person.account)
        except (RunError, OSError) as e:  # a RemoteError goes up: no one could be asked
            failed[key] = e
            continue
        live[key] = tuple(live_drives(result.output))
    return Checked(live, failed)


# ---- mapping one ----

LETTERS = tuple(f"{chr(c)}:" for c in range(ord("D"), ord("Z") + 1))
_SHARE = re.compile(r'^\\\\[^\\/:*?"<>|\s][^\\/:*?"<>|]*\\[^/:*?"<>|]+$')


def valid_share(path: str) -> bool:
    """ "\\\\server\\share" or deeper; never a local path or a URL."""
    return bool(_SHARE.match(path.strip().rstrip("\\")))


# net use, as the person: the drive is theirs and comes back at every sign-in.
_MAP = r"""
param([string]$letter, [string]$path)
$said = & net.exe use $letter $path /persistent:yes 2>&1
$said | ForEach-Object { "$_" }
exit $LASTEXITCODE
"""


def map_script(letter: str, path: str) -> Script:
    """Maps `path` to `letter` ("S:") for whoever it runs as. Raises ValueError for a letter
    or path that isn't one."""
    if letter not in LETTERS or not valid_share(path):
        raise ValueError(f"not a drive letter and share: {letter} {path}")
    code = _MAP.lstrip("\n").encode()
    return Script("Map a drive", Language.POWERSHELL, code, (letter, path.strip().rstrip("\\")))


# ---- caches ----


class App(StrEnum):  # in the order the window lists them
    TEAMS = "teams"
    EDGE = "edge"
    CHROME = "chrome"
    FIREFOX = "firefox"


APP_NAMES = {App.TEAMS: "Teams", App.EDGE: "Edge", App.CHROME: "Chrome", App.FIREFOX: "Firefox"}


class CacheState(StrEnum):
    CLEARED = "cleared"
    OPEN = "open"  # the app was open, so its cache stayed
    NONE = "none"  # nothing to clear: the app isn't used there


@dataclass(frozen=True)
class Cleared:
    app: App
    state: CacheState
    freed: int = 0  # bytes
    left: int = 0  # files in use, left where they were


# Run as CapyPanel's account (an admin of the PC), for one person's profile. An app open for
# that person is left alone: deleting a running app's cache can break it. Only cache folders go;
# Teams' whole cache, as Microsoft's own steps clear it. Never through a link.
_CLEAR = r"""
param([string]$user, [string]$domain, [string]$apps, [string]$profile)
$ErrorActionPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'
if (-not $profile) { try {
  $account = if ($domain) { New-Object Security.Principal.NTAccount($domain, $user) }
             else { New-Object Security.Principal.NTAccount($user) }
  $sid = $account.Translate([Security.Principal.SecurityIdentifier]).Value
} catch { 'CAPYPANEL-CACHE-NOPROFILE'; exit 3 }
$profile = (Get-CimInstance Win32_UserProfile -Filter "SID = '$sid'").LocalPath }
if (-not $profile) { 'CAPYPANEL-CACHE-NOPROFILE'; exit 3 }
$open = @()
$names = "Name = 'ms-teams.exe' OR Name = 'Teams.exe' OR Name = 'msedge.exe' OR " +
         "Name = 'chrome.exe' OR Name = 'firefox.exe'"
foreach ($p in @(Get-CimInstance Win32_Process -Filter $names)) {
  $owner = Invoke-CimMethod -InputObject $p -MethodName GetOwner
  if ($owner.User -eq $user -and $owner.Domain -eq $domain) { $open += $p.Name.ToLower() }
}
$local = Join-Path $profile 'AppData\Local'
$roaming = Join-Path $profile 'AppData\Roaming'
function Browser([string]$data) {
  $found = @()
  foreach ($dir in @(Get-ChildItem -LiteralPath $data -Directory -Force)) {
    if (-not (Test-Path -LiteralPath (Join-Path $dir.FullName 'Preferences'))) { continue }
    foreach ($part in 'Cache', 'Code Cache', 'GPUCache', 'Service Worker\CacheStorage') {
      $found += Join-Path $dir.FullName $part
    }
  }
  $found
}
$script:freed = [int64]0; $script:left = 0
function Empty([string]$folder) {
  foreach ($item in @(Get-ChildItem -LiteralPath $folder -Force)) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    if ($item.PSIsContainer) {
      Empty $item.FullName
      Remove-Item -LiteralPath $item.FullName -Force
    } else {
      $size = $item.Length
      try {
        Remove-Item -LiteralPath $item.FullName -Force -ErrorAction Stop
        $script:freed += $size
      } catch { $script:left++ }
    }
  }
}
foreach ($app in $apps -split ',') {
  if ($app -eq 'teams') {
    $exe = 'ms-teams.exe', 'teams.exe'
    $folders = (Join-Path $roaming 'Microsoft\Teams'),
      (Join-Path $local 'Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams')
  } elseif ($app -eq 'edge') {
    $exe = @('msedge.exe'); $folders = Browser (Join-Path $local 'Microsoft\Edge\User Data')
  } elseif ($app -eq 'chrome') {
    $exe = @('chrome.exe'); $folders = Browser (Join-Path $local 'Google\Chrome\User Data')
  } elseif ($app -eq 'firefox') {
    $exe = @('firefox.exe')
    $folders = @(Get-ChildItem -LiteralPath (Join-Path $local 'Mozilla\Firefox\Profiles') `
      -Directory -Force | ForEach-Object { Join-Path $_.FullName 'cache2' })
  } else { continue }
  if (@($exe | Where-Object { $open -contains $_ }).Count) {
    "CAPYPANEL-CACHE $app open 0 0"; continue
  }
  $there = @($folders | Where-Object { $_ -and (Test-Path -LiteralPath $_) })
  if (-not $there.Count) { "CAPYPANEL-CACHE $app none 0 0"; continue }
  $script:freed = [int64]0; $script:left = 0
  foreach ($folder in $there) { Empty $folder }
  "CAPYPANEL-CACHE $app cleared $($script:freed) $($script:left)"
}
"""


def clear_script(person: Person, apps: tuple[App, ...], profile: str = "") -> Script:
    """Clears `apps`' caches in `person`'s profile; run as CapyPanel's account. `profile`:
    tests only, a folder that stands in for the profile."""
    code = _CLEAR.lstrip("\n").encode()
    arguments = (person.user, person.domain, ",".join(apps), *((profile,) if profile else ()))
    return Script("Clear caches", Language.POWERSHELL, code, arguments)


_CACHE_LINE = re.compile(r"^CAPYPANEL-CACHE (\w+) (\w+) (\d+) (\d+)$", re.MULTILINE)
NO_PROFILE = "CAPYPANEL-CACHE-NOPROFILE"


def cleared(output: str) -> list[Cleared]:
    """What Clear caches did, app by app."""
    found = []
    for line in _CACHE_LINE.finditer(output):
        try:
            found.append(Cleared(App(line[1]), CacheState(line[2]), int(line[3]), int(line[4])))
        except ValueError:
            continue
    return found
