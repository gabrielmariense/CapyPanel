"""Running a script on another PC, the same way whichever way in works.

Three ways in, tried in this order: WinRM when the PC listens for it, then WMI (both ask
Windows' own Win32_Process to start a program, over WinRM's protocol or over DCOM), then PsExec
when it's set up. The way that worked is tried first next time, until CapyPanel closes.

Every way starts the same small PowerShell wrapper on the PC. It runs the script and keeps its
output and exit code in C:\\Windows\\Temp\\CapyPanel\\, a folder only administrators and the
system can open; CapyPanel reads them back over the ADMIN$ share (that same folder, wherever
Windows is installed) and deletes them, even when the run failed. So the output has no length
limit (PsExec cuts what it relays at 256 bytes) and nothing stays on the PC. Files of a run
CapyPanel lost track of are deleted the next time it runs something on that PC.

A PowerShell script travels inside the command; a batch file, or a PowerShell script too big
for a command line, is first copied to that folder under a random name.

A script runs as the account CapyPanel uses for the PC, or (Run as) as SYSTEM or as the person
signed in at the PC. Those two go through a scheduled task the wrapper makes for the run and
deletes after: SYSTEM's runs out of sight, the person's runs in their own session (so a drive it
maps is theirs), started hidden through Windows Script Host, with no password, and with read
access to that run's files only.

Each run, worked or not, gets a line in the run log."""

import base64
import contextlib
import ctypes
import html
import json
import logging
import re
import secrets
import socket
import subprocess
import threading
import time
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from capypanel.core import winsec
from capypanel.core.remote.access import (
    REACH_TIMEOUT,
    Account,
    Reason,
    RemoteError,
    check_reachable,
    network_identity,
    reason_of,
)
from capypanel.core.remote.inventory import run_cim

WINRM_PORT = 5985
TIMEOUT = 10 * 60.0  # seconds a run gets by default; a script can be given longer
START_GRACE = 45.0  # seconds for the wrapper to show it started: PowerShell on a busy PC is slow
SWEEP_AGE = 3 * 60 * 60.0  # leftovers older than this are deleted: past any run's time
PSEXEC_TIMEOUT = 60  # seconds for PsExec to start the wrapper (it doesn't wait for the run)
COMMAND_LIMIT = 30_000  # characters: Windows' command line holds 32 767; room for PsExec's own
LOG_SIZE, LOG_KEEP = 2_000_000, 5  # the run log: bytes per file, older files kept
FOLDER = r"Temp\CapyPanel"  # under Windows' folder on the PC, so C:\Windows\Temp\CapyPanel
# Only files with these names are ever deleted from the folder: what CapyPanel itself made.
_OURS = re.compile(r"^[0-9a-f]{16}(-task)?\.(run|json|tmp|out|err|ps1|cmd|vbs|code)$")

log = logging.getLogger(__name__)


class Language(StrEnum):
    POWERSHELL = "powershell"
    BATCH = "batch"  # .bat and .cmd


@dataclass(frozen=True)
class Script:
    name: str  # what the run log calls it
    language: Language
    code: bytes  # the script as written, byte for byte
    arguments: tuple[str, ...] = ()


class RunAs(StrEnum):
    ACCOUNT = "account"  # the account CapyPanel uses for the PC: yours, or the one typed for it
    SYSTEM = "system"
    USER = "user"  # the person signed in at the PC, named when the run starts


class Engine(StrEnum):  # in the order they're tried
    WINRM = "winrm"
    WMI = "wmi"
    PSEXEC = "psexec"


ENGINE_NAMES = {Engine.WINRM: "WinRM", Engine.WMI: "WMI", Engine.PSEXEC: "PsExec"}


@dataclass(frozen=True)
class RunResult:
    engine: Engine
    exit_code: int
    output: str  # what the script wrote, with Windows' line ends made plain
    errors: str  # what it wrote as errors
    seconds: float

    @property
    def worked(self) -> bool:
        return self.exit_code == 0


class Problem(StrEnum):
    NO_WAY_IN = "no-way-in"  # WinRM off, WMI not answering, PsExec not set up or not working
    BLOCKED = "blocked"  # started, but never ran: security software on the PC, most likely
    NOT_STARTED = "not-started"  # the wrapper ran but couldn't start the script
    TIMED_OUT = "timed-out"  # no answer in time; it may still be running on the PC
    NO_RESULT = "no-result"  # the answer file was there but couldn't be read


class RunError(Exception):
    def __init__(self, problem: Problem, detail: str = "", tried: Sequence[str] = ()) -> None:
        super().__init__(f"{problem}: {detail}" if detail else str(problem))
        self.problem, self.detail, self.tried = problem, detail, tuple(tried)
        self.engine: Engine | None = None  # the way in that started it, when one did


class _NotThisWay(Exception):
    """This way in didn't start the run; the next one may."""


# Starts `command` (a program and its arguments, none with spaces) on the PC, or raises.
Starter = Callable[[str, Sequence[str], Account | None], None]


class Runner:
    """Runs scripts on PCs. One for the whole app, so it remembers the way into each PC."""

    def __init__(
        self,
        psexec: Callable[[], Path | None],
        log_file: Path | None = None,
        *,
        starters: Mapping[Engine, Starter] | None = None,
        folder_of: Callable[[str], Path] = lambda host: Path(rf"\\{host}\ADMIN$") / FOLDER,
        listens: Callable[[str, int], bool] | None = None,
        reachable: Callable[[str], None] = check_reachable,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        remote_folder: str = "",  # tests: the wrapper's folder; "" means Windows' Temp\CapyPanel
    ) -> None:
        self._psexec = psexec
        self._starters = dict(starters) if starters is not None else {
            Engine.WINRM: lambda h, c, a: _start_cim(h, c, a, "Wsman"),
            Engine.WMI: lambda h, c, a: _start_cim(h, c, a, "Dcom"),
            Engine.PSEXEC: self._start_psexec,
        }  # fmt: skip
        self._folder_of, self._reachable = folder_of, reachable
        self._listens = listens or _listens
        self._clock, self._sleep = clock, sleep
        self._remote_folder = remote_folder
        self._worked: dict[str, Engine] = {}  # host, case-folded -> the way in that worked
        self._log_file = log_file
        self._log_lock = threading.Lock()  # runs on several PCs at once share the file

    def way_in(self, host: str) -> Engine | None:
        """The way in that last worked for `host`, if any did."""
        return self._worked.get(host.casefold())

    def run(
        self,
        host: str,
        script: Script,
        account: Account | None = None,
        timeout: float = TIMEOUT,
        run_as: RunAs = RunAs.ACCOUNT,
        user: str = "",
    ) -> RunResult:
        """Runs `script` on `host` and waits for it to end; `user` ("DOMAIN\\name") is who it
        runs as with RunAs.USER. Raises RemoteError (unreachable, or the account isn't accepted
        or isn't an admin there) or RunError."""
        if run_as is RunAs.USER and not user:
            raise ValueError("running as the signed-in person needs their name")
        as_who = {RunAs.ACCOUNT: "", RunAs.SYSTEM: "SYSTEM", RunAs.USER: user}[run_as]
        try:
            self._reachable(host)
            result = self._run(host, script, account, timeout, run_as, user)
        except (RemoteError, RunError, OSError) as e:
            engine = e.engine if isinstance(e, RunError) else None
            self._write_log(host, script, engine, account, as_who, _log_outcome(e))
            raise
        outcome = f"exit {result.exit_code}"
        self._write_log(host, script, result.engine, account, as_who, outcome)
        return result

    def _run(
        self,
        host: str,
        script: Script,
        account: Account | None,
        timeout: float,
        run_as: RunAs = RunAs.ACCOUNT,
        user: str = "",
    ) -> RunResult:
        started = self._clock()
        run_id = secrets.token_hex(8)
        folder = self._folder_of(host)
        # The share's files are read and written as the account; the ways in get it themselves.
        with network_identity(account) as identity:
            with identity():
                _prepare(folder, protect=not self._remote_folder)
                self._sweep(folder)
            try:
                with identity():
                    command = self._command(folder, run_id, script, run_as, user, timeout)
                engine = self._start(host, command, account, folder, run_id, identity)
                try:
                    with identity():
                        return self._result(folder, run_id, engine, started, timeout)
                except RunError as e:
                    e.engine = engine
                    raise
            finally:
                with identity():
                    _delete_run(folder, run_id)

    # ---- the command the PC runs ----

    def _command(
        self,
        folder: Path,
        run_id: str,
        script: Script,
        run_as: RunAs = RunAs.ACCOUNT,
        user: str = "",
        timeout: float = TIMEOUT,
    ) -> list[str]:
        """The wrapper's command line; writes the script to the folder first when it has to."""

        def wrapped(launch: str) -> list[str]:
            return _powershell(self._wrapper(run_id, launch, run_as, user, timeout))

        rest = subprocess.list2cmdline(script.arguments)
        rest = f" {rest}" if rest else ""
        if script.language is Language.POWERSHELL:
            text = _text(script.code)
            if text is not None:
                inline = "& {\n" + text + "\n} " + " ".join(map(_ps_quote, script.arguments))
                command = wrapped(_launch_inline(inline))
                if len(" ".join(command)) <= COMMAND_LIMIT:
                    return command
            (folder / f"{run_id}.ps1").write_bytes(_with_bom(script.code))
            launch = _launch("powershell", f"{_POWERSHELL_FLAGS} -File ", f"{run_id}.ps1", rest)
        else:
            (folder / f"{run_id}.cmd").write_bytes(script.code)
            launch = _launch("cmd", '/d /s /c "', f"{run_id}.cmd", f'{rest}"')
        return wrapped(launch)

    def _wrapper(self, run_id: str, launch: str, run_as: RunAs, user: str, timeout: float) -> str:
        folder = (
            _ps_quote(self._remote_folder)
            if self._remote_folder
            else f"(Join-Path $env:SystemRoot {_ps_quote(FOLDER)})"
        )
        start = _START_HERE if run_as is RunAs.ACCOUNT else _START_TASK
        return (
            _WRAPPER.replace("__START__", start)
            .replace("__DIR__", folder)
            .replace("__ID__", run_id)
            .replace("__LAUNCH__", launch)
            .replace("__AS__", _ps_quote(str(run_as)))
            .replace("__USER__", _ps_quote(user))
            .replace("__TIMEOUT__", str(int(timeout)))
        )

    # ---- starting it ----

    def _ways(self, host: str) -> list[Engine]:
        ways = list(Engine)
        known = self.way_in(host)
        if known is not None:  # the one that worked last time first
            ways.remove(known)
            ways.insert(0, known)
        return ways

    def _start(
        self,
        host: str,
        command: Sequence[str],
        account: Account | None,
        folder: Path,
        run_id: str,
        identity: Callable[[], AbstractContextManager[None]],
    ) -> Engine:
        tried: list[str] = []
        blocked = False
        for engine in self._ways(host):
            name = ENGINE_NAMES[engine]
            if engine is Engine.WINRM and not self._listens(host, WINRM_PORT):
                tried.append(f"{name}: not on")
                continue
            if engine is Engine.PSEXEC and self._psexec() is None:
                tried.append(f"{name}: not set up")
                continue
            try:
                self._starters[engine](host, command, account)
            except RemoteError as e:
                if e.reason in (Reason.REJECTED, Reason.NOT_ADMIN):
                    raise  # the next way would ask with the same account: no lockouts
                tried.append(f"{name}: {e}")
                continue
            except (_NotThisWay, OSError, TimeoutError) as e:
                tried.append(f"{name}: {e}")
                continue
            with identity():
                began = self._began(folder, run_id)
            if began:
                self._worked[host.casefold()] = engine
                return engine
            blocked = True  # started, never ran; another way may get past what stopped it
            tried.append(f"{name}: started, but never ran")
        if blocked:
            raise RunError(Problem.BLOCKED, tried=tried)
        raise RunError(Problem.NO_WAY_IN, tried=tried)

    def _began(self, folder: Path, run_id: str) -> bool:
        """Whether the wrapper shows it started, within START_GRACE."""
        waited_from = self._clock()
        while True:
            if (folder / f"{run_id}.run").exists() or (folder / f"{run_id}.json").exists():
                return True
            waited = self._clock() - waited_from
            if waited >= START_GRACE:
                return False
            self._sleep(_pause(waited))

    def _start_psexec(self, host: str, command: Sequence[str], account: Account | None) -> None:
        program = self._psexec()
        if program is None:
            raise _NotThisWay("not set up")
        # -d: it returns once the wrapper starts, with the wrapper's process ID as its exit code.
        argv = [
            str(program), rf"\\{host}", "-accepteula", "-nobanner", "-d", "-h", "-n", "10",
            *command,
        ]  # fmt: skip
        code = _spawn(argv, account, PSEXEC_TIMEOUT)
        if code > 0 and code % 4 == 0:  # a process ID: Windows' are multiples of 4, its errors not
            return
        reason = reason_of(code)
        if reason is not Reason.OTHER:
            raise RemoteError(reason, code)
        raise _NotThisWay(f"PsExec ended with code {code}")

    # ---- its answer ----

    def _result(
        self, folder: Path, run_id: str, engine: Engine, started: float, timeout: float
    ) -> RunResult:
        answer = folder / f"{run_id}.json"
        while not answer.exists():
            waited = self._clock() - started
            if waited >= timeout:
                raise RunError(Problem.TIMED_OUT, f"no answer within {timeout:.0f} s")
            self._sleep(_pause(waited))
        try:
            found = json.loads(answer.read_bytes().decode("utf-8-sig"))
            if not isinstance(found, dict):
                raise ValueError("not an answer")
        except (OSError, ValueError) as e:
            raise RunError(Problem.NO_RESULT, str(e)) from e
        if found.get("error") or found.get("code") is None:
            raise RunError(Problem.NOT_STARTED, str(found.get("error") or ""))
        oem = int(found.get("oem") or 0)
        return RunResult(
            engine=engine,
            exit_code=int(found["code"]),
            output=_read_output(folder / f"{run_id}.out", oem),
            errors=_plain(_read_output(folder / f"{run_id}.err", oem)),
            seconds=self._clock() - started,
        )

    def _sweep(self, folder: Path) -> None:
        """Deletes what runs CapyPanel lost track of left behind, once it's old enough that no
        run can still be using it."""
        now = time.time()
        try:
            files = list(folder.iterdir())
        except OSError:
            return
        for file in files:
            if not _OURS.match(file.name):
                continue
            with contextlib.suppress(OSError):
                if now - file.stat().st_mtime > SWEEP_AGE:
                    file.unlink()

    def _write_log(
        self,
        host: str,
        script: Script,
        engine: Engine | None,
        account: Account | None,
        as_who: str,
        outcome: str,
    ) -> None:
        if self._log_file is None:
            return
        way = ENGINE_NAMES[engine] if engine is not None else "-"
        who = account.user if account is not None else "(your Windows account)"
        if as_who:
            who = f"{who} as {as_who}"
        when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = "\t".join((when, host, script.name, way, who, outcome)).replace("\n", " ")
        with self._log_lock:
            try:
                _append(self._log_file, line)
            except OSError as e:
                log.warning("Couldn't write the run log %s: %s", self._log_file, e)


# ---- the PC's side ----

# Runs on the PC as PowerShell. Only the first start of a run goes ahead: when a slow PC starts it
# after CapyPanel tried another way in, the second copy finds the .run mark and stops.
_WRAPPER = r"""$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'
$dir = __DIR__
$base = Join-Path $dir '__ID__'
try { [IO.File]::Open("$base.run", 'CreateNew', 'Write', 'None').Close() } catch { exit }
$result = @{code = $null; error = ''; oem = [Console]::OutputEncoding.CodePage}
function Loader($packed) {
  '$ProgressPreference=''SilentlyContinue'';' +
  '$d=[IO.Compression.DeflateStream]::new([IO.MemoryStream]::new(' +
  '[Convert]::FromBase64String(' +
  "'$packed'" + ')),[IO.Compression.CompressionMode]::Decompress);' +
  '$r=[IO.StreamReader]::new($d,[Text.Encoding]::UTF8);$s=$r.ReadToEnd();$r.Dispose();' +
  'Invoke-Expression $s'
}
function Q([string]$text) { "'" + ($text -replace "(['‘’‚‛])", '$1$1') + "'" }
try {
__LAUNCH__
__START__
} catch { $result.error = $_.Exception.Message }
[IO.File]::WriteAllText("$base.tmp", (ConvertTo-Json -InputObject $result -Compress))
Move-Item -LiteralPath "$base.tmp" -Destination "$base.json" -Force
"""

# As the account CapyPanel uses: the wrapper starts the script itself.
_START_HERE = r"""
  $p = Start-Process -FilePath $exe -ArgumentList $argline -WorkingDirectory $dir -NoNewWindow `
    -PassThru -RedirectStandardOutput "$base.out" -RedirectStandardError "$base.err"
  $null = $p.Handle  # keeps the process' handle, so its exit code can be read
  $p.WaitForExit()
  $result.code = $p.ExitCode
"""

# As SYSTEM or the signed-in person: a scheduled task runs a small script that starts the script
# and writes its exit code to .code. Task Scheduler's own API (not its PowerShell module, which
# fails on PCs with a broken WMI). The person's task uses their open session: no password.
_START_TASK = r"""
  $user = __USER__; $system = __AS__ -eq 'system'
  $work = if ($system) { $dir } else { Join-Path $env:SystemRoot 'Temp' }  # theirs to enter
  $inner = "`$p = Start-Process -FilePath $(Q $exe) -ArgumentList $(Q $argline) " +
    "-WorkingDirectory $(Q $work) -NoNewWindow -PassThru " +
    "-RedirectStandardOutput $(Q "$base.out") -RedirectStandardError $(Q "$base.err")`r`n" +
    "`$null = `$p.Handle; `$p.WaitForExit()`r`n" +
    "[IO.File]::WriteAllText($(Q "$base.code"), [string]`$p.ExitCode)"
  [IO.File]::WriteAllText("$base-task.ps1", $inner, (New-Object Text.UTF8Encoding $true))
  $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
  $run = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File " +
    "`"$base-task.ps1`""
  if ($system) {
    $command = $shell; $arguments = $run
    $principal = '<UserId>S-1-5-18</UserId><LogonType>ServiceAccount</LogonType>' +
      '<RunLevel>HighestAvailable</RunLevel>'
  } else {
    # Hidden: Windows Script Host starts PowerShell with no window on the person's screen.
    $vbs = "WScript.Quit CreateObject(`"WScript.Shell`").Run(`"`"`"$shell`"`" " +
      ($run -replace '"', '""') + "`", 0, True)"
    [IO.File]::WriteAllText("$base.vbs", $vbs, [Text.Encoding]::Unicode)
    $command = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $arguments = "//B //Nologo `"$base.vbs`""
    $principal = "<UserId>$([Security.SecurityElement]::Escape($user))</UserId>" +
      '<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>'
    foreach ($kind in 'out', 'err', 'code') { [IO.File]::WriteAllText("$base.$kind", '') }
    $grants = @{"$base-task.ps1" = 'R'; "$base.vbs" = 'R'; "$base.out" = 'M'; "$base.err" = 'M'
                "$base.code" = 'M'; "$base.ps1" = 'R'; "$base.cmd" = 'R'}
    foreach ($file in $grants.Keys) {
      if (Test-Path -LiteralPath $file) {
        $null = & icacls.exe $file /grant "$($user):($($grants[$file]))"
        if ($LASTEXITCODE) { throw "Couldn't let $user read $file (icacls $LASTEXITCODE)." }
      }
    }
  }
  $limit = __TIMEOUT__
  $xml = '<?xml version="1.0" encoding="UTF-16"?>' +
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">' +
    "<Principals><Principal id=`"Run`">$principal</Principal></Principals>" +
    '<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>' +
    '<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>' +
    '<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowStartOnDemand>true' +
    "</AllowStartOnDemand><Enabled>true</Enabled><ExecutionTimeLimit>PT$($limit + 60)S" +
    '</ExecutionTimeLimit><Priority>7</Priority></Settings>' +
    "<Actions Context=`"Run`"><Exec><Command>$([Security.SecurityElement]::Escape($command))" +
    "</Command><Arguments>$([Security.SecurityElement]::Escape($arguments))</Arguments>" +
    '</Exec></Actions></Task>'
  $service = New-Object -ComObject Schedule.Service
  $service.Connect()
  $tasks = $service.GetFolder('\')
  $name = 'CapyPanel-__ID__'
  try {
    if ($system) { $null = $tasks.RegisterTask($name, $xml, 6, 'SYSTEM', $null, 5) }
    else { $null = $tasks.RegisterTask($name, $xml, 6, $null, $null, 3) }
    $null = $tasks.GetTask($name).Run($null)
    $from = Get-Date
    while ($true) {
      Start-Sleep -Milliseconds 500
      $code = if (Test-Path -LiteralPath "$base.code") { [IO.File]::ReadAllText("$base.code") }
      if ("$code".Trim()) { $result.code = [int]"$code".Trim(); break }
      $task = $tasks.GetTask($name)
      $waited = ((Get-Date) - $from).TotalSeconds
      if ($task.State -ne 4 -and $waited -gt 15) {  # 4: running
        $result.error = 'The scheduled task ended without an answer (result 0x{0:X8}).' -f
          $task.LastTaskResult
        break
      }
      if ($waited -gt $limit) { $task.Stop(0); $result.error = 'Out of time.'; break }
    }
  } finally { try { $tasks.DeleteTask($name, 0) } catch { } }
"""

# Text: with its output going to files, PowerShell would otherwise write errors and progress as XML.
_POWERSHELL_FLAGS = "-NoLogo -NoProfile -NonInteractive -OutputFormat Text -ExecutionPolicy Bypass"
_PROGRAMS = {
    "powershell": "(Join-Path $env:SystemRoot 'System32\\WindowsPowerShell\\v1.0\\powershell.exe')",
    "cmd": "$env:ComSpec",
}


def _launch(program: str, before: str, file_name: str, after: str) -> str:
    """Starts a script copied to the folder, by its full path on the PC, in quotes."""
    path = f"(Join-Path $dir {_ps_quote(file_name)})"
    argline = f"{_ps_quote(before)} + '\"' + {path} + '\"' + {_ps_quote(after)}"
    return f"  $exe = {_PROGRAMS[program]}\n  $argline = {argline}"


def _launch_inline(text: str) -> str:
    """The script travels packed inside the wrapper, and from there inside its own command."""
    flags = _ps_quote(f"{_POWERSHELL_FLAGS} -EncodedCommand ")
    return (
        f"  $exe = {_PROGRAMS['powershell']}\n"
        f"  $argline = {flags} + [Convert]::ToBase64String("
        f"[Text.Encoding]::Unicode.GetBytes((Loader '{_pack(text)}')))"
    )


def _powershell(script: str) -> list[str]:
    """The command that runs `script` on the PC: packed, so a long one still fits."""
    loader = (
        "$ProgressPreference='SilentlyContinue';"
        "$d=[IO.Compression.DeflateStream]::new([IO.MemoryStream]::new([Convert]::"
        f"FromBase64String('{_pack(script)}')),[IO.Compression.CompressionMode]::Decompress);"
        "$r=[IO.StreamReader]::new($d,[Text.Encoding]::UTF8);$s=$r.ReadToEnd();$r.Dispose();"
        "Invoke-Expression $s"
    )
    encoded = base64.b64encode(loader.encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
        "Bypass", "-EncodedCommand", encoded,
    ]  # fmt: skip


def _pack(text: str) -> str:
    """Raw deflate, which .NET's DeflateStream reads, in base64."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    return base64.b64encode(packer.compress(text.encode("utf-8")) + packer.flush()).decode()


def _ps_quote(value: str) -> str:
    """A PowerShell string that stays exactly `value`: nothing inside it runs. PowerShell also
    takes the typographic single quotes as quotes, so each is doubled like the plain one."""
    return "'" + _QUOTES.sub(r"\1\1", value) + "'"


_QUOTES = re.compile("([\u0027\u2018\u2019\u201a\u201b])")


def _text(code: bytes) -> str | None:
    """A PowerShell script as text when it's UTF-8 (most are, or plain ASCII); None otherwise, so
    it runs from a file, read the way Windows PowerShell reads its own files."""
    try:
        return code.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _with_bom(code: bytes) -> bytes:
    """Windows PowerShell reads a .ps1 without a BOM in the PC's old code page: a UTF-8 script
    gets the BOM that makes it read as UTF-8. Anything else is copied as it is."""
    if code.startswith(b"\xef\xbb\xbf") or code.isascii():
        return code
    try:
        code.decode("utf-8")
    except UnicodeDecodeError:
        return code
    return b"\xef\xbb\xbf" + code


# ---- this PC's side ----


def _prepare(folder: Path, protect: bool) -> None:
    """Creates the run folder on the PC if needed, open to administrators and the system only.
    Raises RemoteError: the share refusing the account is the first sign it isn't an admin."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if protect:
            winsec.make_admins_only(folder)
    except OSError as e:
        code = e.winerror or 0
        raise RemoteError(reason_of(code), code) from e


def _delete_run(folder: Path, run_id: str) -> None:
    for name in (f"{run_id}-task.ps1", *(f"{run_id}.{kind}" for kind in _KINDS)):
        with contextlib.suppress(OSError):
            (folder / name).unlink(missing_ok=True)


_KINDS = ("run", "json", "tmp", "out", "err", "ps1", "cmd", "vbs", "code")


def _read_output(file: Path, oem: int) -> str:
    try:
        data = file.read_bytes()
    except OSError:
        return ""
    return decode_output(data, oem)


def decode_output(data: bytes, oem: int) -> str:
    """A console program's output as text. Most write in the PC's console code page (`oem`);
    some, like sfc, write UTF-16; PowerShell may write UTF-8."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    elif len(data) >= 2 and data[1::2].count(0) > len(data) // 4:  # UTF-16 without its mark
        text = data.decode("utf-16-le", errors="replace")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode(f"cp{oem}", errors="replace")
            except LookupError:
                text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _plain(errors: str) -> str:
    """PowerShell may still send its errors as XML ("#< CLIXML"): their text, without the rest
    (progress bars and the like)."""
    if not errors.startswith("#< CLIXML"):
        return errors
    found: list[str] = []
    for line in errors.split("\n")[1:]:
        if not line.startswith("<Objs "):
            found.append(line + "\n" if line else "")
            continue
        for part in re.findall(r'<S S="Error">(.*?)</S>', line, re.DOTALL):
            text = html.unescape(part)
            found.append(re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m[1], 16)), text))
    return "".join(found).replace("\r\n", "\n")


def _pause(waited: float) -> float:
    """How long to wait before looking again: often at first, then rarely, so a long run costs
    the PC almost nothing."""
    return 0.5 if waited < 5 else 1.0 if waited < 60 else 3.0


def _listens(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), REACH_TIMEOUT).close()
    except OSError:
        return False
    return True


def _log_outcome(error: BaseException) -> str:
    if isinstance(error, RunError):
        tried = f" ({'; '.join(error.tried)})" if error.tried else ""
        return f"failed: {error.problem}{tried}"
    return f"failed: {error}"


def _append(log_file: Path, line: str) -> None:
    """One line at the end of the run log; a full one moves aside first, the oldest dropped."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if log_file.exists() and log_file.stat().st_size > LOG_SIZE:
        for n in range(LOG_KEEP - 1, 0, -1):
            older = log_file.with_name(f"{log_file.name}.{n}")
            if older.exists():
                older.replace(log_file.with_name(f"{log_file.name}.{n + 1}"))
        log_file.replace(log_file.with_name(f"{log_file.name}.1"))
    with log_file.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---- the ways in ----

_START = r"""
try {
  $r = Invoke-CimMethod -CimSession $session -ClassName Win32_Process -MethodName Create `
    -Arguments @{CommandLine = $in.command}
  Send @{code = [int]$r.ReturnValue}
} catch { Send @{error = [int64]$_.Exception.HResult}; exit 1 }
finally { Remove-CimSession $session }
"""

# What Win32_Process.Create answers when it doesn't start the program.
_CREATE_ERRORS = {
    2: "access denied", 3: "not allowed", 8: "unknown failure", 9: "path not found",
    21: "invalid parameter",
}  # fmt: skip


def _start_cim(host: str, command: Sequence[str], account: Account | None, protocol: str) -> None:
    try:
        found = run_cim(_START, host, account, protocol, {"command": " ".join(command)})
    except RemoteError as e:
        if e.reason in (Reason.REJECTED, Reason.NOT_ADMIN):
            raise
        raise _NotThisWay(str(e)) from e
    code = int(found.get("code") or 0)
    if code:
        raise _NotThisWay(f"Win32_Process.Create: {_CREATE_ERRORS.get(code, code)}")


def _spawn(argv: Sequence[str], account: Account | None, timeout: float) -> int:
    """Runs a program on this PC and returns its exit code. With an account, the program uses it
    for the network only, like `runas /netonly`, so no password goes on its command line."""
    if account is None:
        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"no answer within {timeout:.0f} s") from e
        return done.returncode & 0xFFFFFFFF
    with _process_as(account, subprocess.list2cmdline(argv)) as process:
        if _kernel32.WaitForSingleObject(process, int(timeout * 1000)) != 0:
            _kernel32.TerminateProcess(process, 1)
            raise TimeoutError(f"no answer within {timeout:.0f} s")
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR), ("desktop", wintypes.LPWSTR),
        ("title", wintypes.LPWSTR), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
        ("x_size", wintypes.DWORD), ("y_size", wintypes.DWORD), ("x_chars", wintypes.DWORD),
        ("y_chars", wintypes.DWORD), ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("show", wintypes.WORD), ("reserved2_size", wintypes.WORD),
        ("reserved2", ctypes.c_void_p), ("stdin", wintypes.HANDLE),
        ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE),
    ]  # fmt: skip


class _ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
        ("process_id", wintypes.DWORD), ("thread_id", wintypes.DWORD),
    ]  # fmt: skip


@contextlib.contextmanager
def _process_as(account: Account, command_line: str) -> Iterator[int]:
    domain, _sep, name = account.user.rpartition("\\")  # "DOMAIN\\name", or a UPN
    startup, info = _StartupInfo(), _ProcessInfo()
    startup.cb = ctypes.sizeof(startup)
    netcredentials_only, no_window = 2, 0x08000000
    line = ctypes.create_unicode_buffer(command_line)  # Windows may write to it
    if not _advapi32.CreateProcessWithLogonW(
        name, domain or None, account.password, netcredentials_only, None, line, no_window,
        None, None, ctypes.byref(startup), ctypes.byref(info),
    ):  # fmt: skip
        raise ctypes.WinError(ctypes.get_last_error())
    _kernel32.CloseHandle(info.thread)
    try:
        yield info.process
    finally:
        _kernel32.CloseHandle(info.process)


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.CreateProcessWithLogonW.restype = wintypes.BOOL
_advapi32.CreateProcessWithLogonW.argtypes = [
    wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPCWSTR,
    wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(_StartupInfo), ctypes.POINTER(_ProcessInfo),
]  # fmt: skip
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
