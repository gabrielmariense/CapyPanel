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
import logging
import subprocess
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import dataclass, field
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

WMI_TIMEOUT = 90  # seconds for one read, its connection included

log = logging.getLogger(__name__)

# How reads reach a PC's WMI (over DCOM; WinRM always goes through PowerShell):
AUTO = "auto"  # WMI straight from CapyPanel; PowerShell only when that can't be used here
DIRECT = "direct"  # only WMI straight from CapyPanel
POWERSHELL = "powershell"  # only a PowerShell started on this PC, as before 0.24
transport = AUTO  # set from Settings
powershell_blocked = False  # Windows refused to start it here this session

# Each PowerShell script that has a twin reading the same over WMI directly, with the same answer.
Reader = Callable[[Any, Mapping[str, str]], Any]
_READERS: dict[str, Reader] = {}


def reads(script: str) -> Callable[[Reader], Reader]:
    """Marks a function as `script`'s twin: it gets a wmi.Wmi and the script's `$in` values,
    and answers what the script would have sent."""

    def mark(reader: Reader) -> Reader:
        _READERS[script] = reader
        return reader

    return mark


class PowerShellBlocked(OSError):
    """Windows didn't let CapyPanel start PowerShell on this PC, often an antivirus's doing."""

    def __init__(self, error: OSError) -> None:
        super().__init__(
            error.errno,
            f"PowerShell couldn't start on this PC ({error.strerror or error}); an antivirus "
            "may have blocked it",
        )


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
    # Rows that couldn't be read while the others could ("windows", "model", "serial",
    # "memory", "bios"), each with why: some PCs' WMI lacks one of the classes.
    unread: Mapping[str, RemoteError] = field(default_factory=dict)


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
        unread=dict(found.get("unread") or {}),
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
    """Reads `host` with `script`, or with its twin over WMI directly when it has one and
    `protocol` is DCOM (the twin starts no program, so no antivirus has a command line to
    judge). PowerShell is the way when WMI can't be used from this PC at all, and for WinRM.
    Raises RemoteError, TimeoutError, or PowerShellBlocked when PowerShell was needed and
    Windows wouldn't start it."""
    from capypanel.core.remote import wmi

    reader = _READERS.get(script)
    if protocol == "Dcom" and reader is not None and transport != POWERSHELL:
        try:
            return wmi.read(reader, host, account, dict(values or {}), timeout)
        except wmi.Unavailable as e:
            if transport == DIRECT:
                raise RemoteError(Reason.OTHER) from e
            log.warning("WMI can't be used from this PC (%s); reading %s with PowerShell", e, host)
    return _powershell(script, host, account, protocol, values, timeout)


def _powershell(
    script: str,
    host: str,
    account: Account | None,
    protocol: str,
    values: Mapping[str, str] | None,
    timeout: float,
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
    except OSError as e:  # the program itself wasn't let start: never the other PC's doing
        global powershell_blocked  # noqa: PLW0603 - for the session, as the log says
        powershell_blocked = True
        log.warning("PowerShell couldn't start on this PC to read %s: %s", host, e)
        raise PowerShellBlocked(e) from e
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


# ---- the same reads over WMI directly ----

_VERSION_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"


@reads(_FACTS)
def _facts_direct(wmi: Any, _values: Mapping[str, str]) -> dict[str, Any]:
    from capypanel.core.remote.wmi import HKLM

    # Each part by itself: a PC whose WMI lacks one class (a damaged repository answers "not
    # found") still shows the rest, and the log names the part.
    failed: dict[str, RemoteError] = {}

    def part(name: str, read: Callable[[], Any]) -> Any:
        try:
            return read()
        except RemoteError as e:
            if e.reason is not Reason.OTHER:
                raise  # no access, or it stopped answering: the whole read's own error
            log.warning("PC facts on %s: %s couldn't be read: %s", wmi.host, name, e)
            failed[name] = e
            return None

    system = part("Win32_ComputerSystem", lambda: wmi.first(
        "SELECT Manufacturer, Model, TotalPhysicalMemory FROM Win32_ComputerSystem"))  # fmt: skip
    bios = part("Win32_BIOS", lambda: wmi.first(
        "SELECT SerialNumber, SMBIOSBIOSVersion FROM Win32_BIOS"))  # fmt: skip
    os = part("Win32_OperatingSystem", lambda: wmi.first(
        "SELECT Caption, BuildNumber FROM Win32_OperatingSystem"))  # fmt: skip
    version = part("the registry's Windows version", lambda: (
        wmi.string(HKLM, _VERSION_KEY, "DisplayVersion"),
        wmi.dword(HKLM, _VERSION_KEY, "UBR")))  # fmt: skip
    if len(failed) == 4:
        raise next(iter(failed.values()))  # nothing at all: the read failed
    unread: dict[str, RemoteError] = {}
    for name, rows in (("Win32_OperatingSystem", ("windows",)),
                       ("Win32_ComputerSystem", ("model", "memory")),
                       ("Win32_BIOS", ("serial", "bios"))):  # fmt: skip
        if name in failed:
            unread.update(dict.fromkeys(rows, failed[name]))
    return {
        "caption": getattr(os, "Caption", None), "build": getattr(os, "BuildNumber", None),
        "release": version[0] if version else None, "patch": version[1] if version else None,
        "maker": getattr(system, "Manufacturer", None), "model": getattr(system, "Model", None),
        "memory": getattr(system, "TotalPhysicalMemory", None),
        "serial": getattr(bios, "SerialNumber", None),
        "bios": getattr(bios, "SMBIOSBIOSVersion", None),
        "unread": unread,
    }  # fmt: skip


@reads(_PROGRAMS)
def _programs_direct(wmi: Any, _values: Mapping[str, str]) -> list[dict[str, Any]]:
    from capypanel.core.remote.wmi import HKLM

    found = []
    for root in (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        for sub in wmi.subkeys(HKLM, root):
            key = f"{root}\\{sub}"
            names = wmi.value_names(HKLM, key)[1]
            if "DisplayName" not in names or "ParentKeyName" in names:
                continue
            if "SystemComponent" in names and wmi.dword(HKLM, key, "SystemComponent") == 1:
                continue
            entry = {
                name: wmi.string(HKLM, key, name)
                for name in ("DisplayName", "DisplayVersion", "Publisher", "InstallDate")
                if name in names
            }
            if entry.get("DisplayName"):
                found.append(entry)
    return found


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
