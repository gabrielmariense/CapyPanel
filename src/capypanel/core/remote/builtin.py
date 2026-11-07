"""The scripts CapyPanel ships with, run on a PC through core.remote.run.

They run as the account CapyPanel uses for the PC, so they act on the PC itself: Update group
policy refreshes the computer's policies (a user's own come with running as the logged-on user).
Their output is cleaned for reading: progress bars that redraw one line are left out, and every
tool's text comes out in the PC's own language."""

import re
from dataclasses import dataclass

from capypanel.core.remote.run import TIMEOUT, Language, Script

REPAIR_TIMEOUT = 2 * 60 * 60.0  # seconds: DISM and sfc together can take an hour on a slow PC

# Runs a console program and keeps what it says: the last state of each line it redraws, without
# progress bars. Its output is read whole, since PowerShell's own reading would split a redrawn
# line at every \r. -Unicode: the program writes UTF-16 (sfc), not the console's code page.
_RUN = r"""
$ProgressPreference = 'SilentlyContinue'
function Run([string]$exe, [string[]]$arguments, [switch]$Unicode) {
  $info = New-Object Diagnostics.ProcessStartInfo $exe
  $info.Arguments = ($arguments | ForEach-Object {
    if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
  $info.UseShellExecute = $false; $info.CreateNoWindow = $true
  $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
  $encoding = if ($Unicode) { [Text.Encoding]::Unicode } else { [Console]::OutputEncoding }
  $info.StandardOutputEncoding = $encoding; $info.StandardErrorEncoding = $encoding
  $p = [Diagnostics.Process]::Start($info)
  $errors = $p.StandardError.ReadToEndAsync()
  $said = $p.StandardOutput.ReadToEnd()
  $p.WaitForExit()
  $global:LASTEXITCODE = $p.ExitCode
  foreach ($line in (($said + $errors.Result) -replace "`0", '' -split "`n")) {
    $text = @($line -split "`r" | Where-Object { $_.Trim() })[-1]
    if ($text -and $text -notmatch '^\s*\[[=\s]*[\d.,]+%[=\s]*\]\s*$') { $text.TrimEnd() }
  }
}
"""

_GPUPDATE = (
    _RUN
    + r"""
Run gpupdate.exe '/target:computer', '/force', '/wait:600'
exit $LASTEXITCODE
"""
)

_DNS = (
    _RUN
    + r"""
Run ipconfig.exe '/flushdns'
if ($LASTEXITCODE) { exit $LASTEXITCODE }
Run ipconfig.exe '/registerdns'
exit $LASTEXITCODE
"""
)

_CLOCK = (
    _RUN
    + r"""
$service = Get-Service w32time
if ($service.Status -ne 'Running') { Start-Service w32time; Start-Sleep -Seconds 2 }
Run w32tm.exe '/resync', '/force'
exit $LASTEXITCODE
"""
)

_REPAIR = (
    _RUN
    + r"""
Run DISM.exe '/Online', '/Cleanup-Image', '/RestoreHealth', '/NoRestart'
$dism = $LASTEXITCODE
Run sfc.exe '/scannow' -Unicode
$sfc = $LASTEXITCODE
if ($dism) { exit $dism }
exit $sfc
"""
)

# Files untouched for a day, in Windows' Temp and every user's; never CapyPanel's own folder, never
# through a link (a junction in a Temp folder could point anywhere). Files in use stay.
_CLEAN = r"""
$ErrorActionPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'
$cutoff = (Get-Date).AddDays(-1)
$ours = Join-Path $env:SystemRoot 'Temp\CapyPanel'
$roots = @(Join-Path $env:SystemRoot 'Temp')
foreach ($p in @(Get-CimInstance Win32_UserProfile -Filter 'Special = FALSE')) {
  $roots += Join-Path $p.LocalPath 'AppData\Local\Temp'
}
$script:freed = [int64]0; $script:files = 0; $script:left = 0
function Clean([string]$folder) {
  foreach ($item in @(Get-ChildItem -LiteralPath $folder -Force)) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
    if ($item.PSIsContainer) {
      if ($item.FullName -eq $ours) { continue }
      Clean $item.FullName
      $empty = -not @(Get-ChildItem -LiteralPath $item.FullName -Force)
      if ($empty -and $item.CreationTime -lt $cutoff) {
        Remove-Item -LiteralPath $item.FullName -Force
      }
    } elseif ($item.LastWriteTime -lt $cutoff) {
      $size = $item.Length
      try {
        Remove-Item -LiteralPath $item.FullName -Force -ErrorAction Stop
        $script:freed += $size; $script:files++
      } catch { $script:left++ }
    }
  }
}
foreach ($root in $roots) { if (Test-Path -LiteralPath $root) { Clean $root } }
"CAPYPANEL-CLEAN freed=$($script:freed) files=$($script:files) left=$($script:left)"
"""


@dataclass(frozen=True)
class BuiltIn:
    script: Script
    timeout: float = TIMEOUT


def _ps(name: str, code: str) -> Script:
    return Script(name, Language.POWERSHELL, code.lstrip("\n").encode("utf-8"))


# By host command id (core.hosts.commands).
BUILT_IN = {
    "gpupdate": BuiltIn(_ps("Update group policy", _GPUPDATE)),
    "dns": BuiltIn(_ps("Refresh DNS", _DNS)),
    "clock": BuiltIn(_ps("Sync the clock", _CLOCK)),
    "repair": BuiltIn(_ps("Repair Windows files", _REPAIR), REPAIR_TIMEOUT),
    "clean-temp": BuiltIn(_ps("Clean temporary files", _CLEAN)),
}


@dataclass(frozen=True)
class Cleaned:
    freed: int  # bytes
    files: int
    left: int  # files in use, left where they were


_CLEANED = re.compile(r"^CAPYPANEL-CLEAN freed=(\d+) files=(\d+) left=(\d+)$", re.MULTILINE)


def cleaned(output: str) -> tuple[Cleaned | None, str]:
    """What Clean temporary files did, and its output without the line that says it."""
    found = _CLEANED.search(output)
    if found is None:
        return None, output
    rest = (output[: found.start()] + output[found.end() :]).strip("\n")
    return Cleaned(int(found[1]), int(found[2]), int(found[3])), rest
