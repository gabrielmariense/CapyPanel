"""What a PC is and what's installed on it, read only.

Free space and the last restart come over file sharing, as Refresh's checks do, in a few tens of
milliseconds. The rest (Windows' version, maker, model, serial, BIOS, memory, and the installed
programs) comes from WMI over DCOM, Windows' own management service, through PowerShell: about
2 to 5 seconds for a first connection. The registry is read through WMI's registry provider, so
the Remote Registry service (off by default) isn't needed. Nothing is installed or run on the
PC, and programs are read from the uninstall list, never through Win32_Product (which makes
Windows check, and sometimes repair, every MSI program it lists).

Installed programs are those installed for every user of the PC; a program someone installed
only for themselves is in their own profile and isn't listed."""

import base64
import ctypes
import json
import subprocess
from collections.abc import Mapping
from ctypes import wintypes
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from capypanel.core.remote.access import (
    Account,
    Reason,
    RemoteError,
    as_account,
    check_reachable,
    last_error,
    reason_of,
)

WMI_TIMEOUT = 90  # seconds for one PowerShell run, its connection included


@dataclass(frozen=True)
class DiskSpace:
    free: int  # bytes on C:
    total: int


@dataclass(frozen=True)
class PcFacts:
    windows: str  # "Windows 11 Pro"
    release: str  # "25H2", or "" on old versions that don't have one
    build: str  # "26200.9168": the build and its patch level
    maker: str
    model: str
    serial: str
    bios: str
    memory: int  # bytes


@dataclass(frozen=True)
class Program:
    name: str
    version: str
    publisher: str
    installed: date | None  # when the program says it was installed, if it does


def disk_space(host: str, account: Account | None = None) -> DiskSpace:
    """Free and total space on `host`'s C: drive, over the C$ share. Raises RemoteError."""
    check_reachable(host)
    free, total = ctypes.c_ulonglong(), ctypes.c_ulonglong()
    with as_account(account):
        if not _kernel32.GetDiskFreeSpaceExW(
            f"\\\\{host}\\C$\\", None, ctypes.byref(total), ctypes.byref(free)
        ):
            raise last_error()
    return DiskSpace(free.value, total.value)


def last_restart(host: str, account: Account | None = None) -> datetime:
    """When Windows last started on `host` (UTC), from when its file-sharing client started: the
    same minute, as WMI's boot time. Raises RemoteError."""
    check_reachable(host)
    buffer = ctypes.c_void_p()
    with as_account(account):
        code = _netapi32.NetStatisticsGet(
            f"\\\\{host}", "LanmanWorkstation", 0, 0, ctypes.byref(buffer)
        )
    if code:
        raise RemoteError(reason_of(code), code)
    try:  # STAT_WORKSTATION_0 starts with StatisticsStartTime, a FILETIME
        started = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_longlong))[0]
    finally:
        _netapi32.NetApiBufferFree(buffer)
    return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=started // 10)


def pc_facts(host: str, account: Account | None = None) -> PcFacts:
    """`host`'s Windows version and hardware, over WMI. Raises RemoteError, TimeoutError."""
    check_reachable(host)
    found = run_cim(_FACTS, host, account)
    return PcFacts(
        windows=str(found["caption"] or "").removeprefix("Microsoft ").strip(),
        release=str(found["release"] or ""),
        build=f"{found['build']}.{found['patch']}" if found["patch"] is not None else
        str(found["build"] or ""),
        maker=str(found["maker"] or "").strip(),
        model=str(found["model"] or "").strip(),
        serial=str(found["serial"] or "").strip(),
        bios=str(found["bios"] or "").strip(),
        memory=int(found["memory"] or 0),
    )  # fmt: skip


def installed_programs(host: str, account: Account | None = None) -> list[Program]:
    """The programs installed for every user of `host`, by name, without Windows' own parts and
    updates. Raises RemoteError, TimeoutError."""
    check_reachable(host)
    found = run_cim(_PROGRAMS, host, account)
    programs = {
        (p.name.casefold(), p.version): p
        for p in (_program(entry) for entry in found)  # 32- and 64-bit lists can repeat one
    }
    return sorted(programs.values(), key=lambda p: (p.name.casefold(), p.version))


def _program(entry: dict[str, str | None]) -> Program:
    when = entry.get("InstallDate") or ""
    try:
        installed = datetime.strptime(when.strip(), "%Y%m%d").date()
    except ValueError:
        installed = None  # missing, or written another way by its installer
    return Program(
        name=(entry.get("DisplayName") or "").strip(),
        version=(entry.get("DisplayVersion") or "").strip(),
        publisher=(entry.get("Publisher") or "").strip(),
        installed=installed,
    )


def run_cim(
    script: str,
    host: str,
    account: Account | None,
    protocol: str = "Dcom",
    values: Mapping[str, str] | None = None,
    timeout: float = WMI_TIMEOUT,
) -> Any:
    """Runs a PowerShell script that uses `$session`, a CIM session to `host` over `protocol`
    ("Dcom" for WMI, "Wsman" for WinRM), and answers with Send. The host, the account and
    `values` (as `$in.<name>`) go in through standard input, never on the command line, so they
    can't change the script and the password isn't visible to other programs."""
    data = {**(values or {}), "host": host, "protocol": protocol, "user": "", "password": ""}
    if account:
        data["user"], data["password"] = account.user, account.password
    command = base64.b64encode((_COMMON + script).encode("utf-16-le")).decode()
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", command],
            input=json.dumps(data).encode(),  # ASCII: other characters travel as \u escapes
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as e:
        raise TimeoutError(f"WMI didn't answer within {timeout:.0f} s") from e
    try:
        answer = json.loads(base64.b64decode(done.stdout).decode("utf-8"))
    except ValueError as e:
        raise RemoteError(Reason.OTHER) from e
    if done.returncode:
        raise wmi_error(int(answer.get("error") or 0))
    return answer


def wmi_error(code: int) -> RemoteError:
    """WMI's failures come as HRESULTs; Windows' own errors among them (0x8007xxxx) carry the
    same codes as the other remote calls."""
    code &= 0xFFFFFFFF
    if code >> 16 == 0x8007:
        return RemoteError(reason_of(code & 0xFFFF), code & 0xFFFF)
    if code == 0x80041003:  # WBEM_E_ACCESS_DENIED: connected, but not allowed to read
        return RemoteError(Reason.NOT_ADMIN, code)
    return RemoteError(Reason.OTHER, code)


# Shared by every CIM script: read the input, open one session, send back base64'd UTF-8 JSON
# (so names in any language survive the console), and turn a failure into its HRESULT.
_COMMON = r"""
$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'
function Send($value) {
  $json = ConvertTo-Json -InputObject $value -Compress -Depth 4
  [Console]::Out.Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)))
}
$in = [Console]::In.ReadToEnd() | ConvertFrom-Json
$HKLM = [uint32]2147483650
function Reg($method, $key, $name) {
  $a = @{hDefKey = $HKLM; sSubKeyName = $key}
  if ($name) { $a.sValueName = $name }
  Invoke-CimMethod -CimSession $session -Namespace root/default -ClassName StdRegProv `
    -MethodName $method -Arguments $a
}
try {
  $p = @{ComputerName = $in.host; SessionOption = (New-CimSessionOption -Protocol $in.protocol)
         OperationTimeoutSec = 30}
  if ($in.user) {
    $secret = ConvertTo-SecureString $in.password -AsPlainText -Force
    $p.Credential = New-Object System.Management.Automation.PSCredential($in.user, $secret)
  }
  $session = New-CimSession @p
} catch {
  $code = $_.Exception.HResult; $data = $_.Exception.ErrorData
  if ($data) { $e = $data.CimInstanceProperties['error_Code']; if ($e) { $code = $e.Value } }
  Send @{error = [int64]$code}; exit 1
}
"""

_FACTS = r"""
try {
  $system = Get-CimInstance -CimSession $session Win32_ComputerSystem
  $bios = Get-CimInstance -CimSession $session Win32_BIOS
  $os = Get-CimInstance -CimSession $session Win32_OperatingSystem
  $key = 'SOFTWARE\Microsoft\Windows NT\CurrentVersion'
  Send @{caption = $os.Caption; release = (Reg GetStringValue $key DisplayVersion).sValue
         build = $os.BuildNumber; patch = (Reg GetDWORDValue $key UBR).uValue
         maker = $system.Manufacturer; model = $system.Model; memory = $system.TotalPhysicalMemory
         serial = $bios.SerialNumber; bios = $bios.SMBIOSBIOSVersion}
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""

# One registry call per value: EnumValues first, so entries that aren't programs (no name,
# an update of another program, a part of Windows) cost one call.
_PROGRAMS = r"""
try {
  $found = New-Object System.Collections.ArrayList
  foreach ($root in 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                    'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall') {
    foreach ($sub in (Reg EnumKey $root).sNames) {
      $key = "$root\$sub"
      $names = @((Reg EnumValues $key).sNames)
      if ($names -notcontains 'DisplayName' -or $names -contains 'ParentKeyName') { continue }
      if ($names -contains 'SystemComponent' -and
          (Reg GetDWORDValue $key SystemComponent).uValue -eq 1) { continue }
      $entry = @{}
      foreach ($name in 'DisplayName', 'DisplayVersion', 'Publisher', 'InstallDate') {
        if ($names -contains $name) { $entry[$name] = (Reg GetStringValue $key $name).sValue }
      }
      if ($entry.DisplayName) { [void]$found.Add($entry) }
    }
  }
  Send @($found)
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetDiskFreeSpaceExW.restype = wintypes.BOOL
_kernel32.GetDiskFreeSpaceExW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong),
    ctypes.POINTER(ctypes.c_ulonglong),
]  # fmt: skip
_netapi32 = ctypes.WinDLL("netapi32")
_netapi32.NetStatisticsGet.restype = wintypes.DWORD
_netapi32.NetStatisticsGet.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.POINTER(ctypes.c_void_p),
]  # fmt: skip
_netapi32.NetApiBufferFree.argtypes = [ctypes.c_void_p]
