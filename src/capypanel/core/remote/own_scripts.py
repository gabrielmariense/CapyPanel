"""Your own scripts: PowerShell and batch files in one scripts folder, written in any editor and
run on a PC through core.remote.run.

A script is called as `script <host> <arguments>`: the host's name as CapyPanel knows it, then
the arguments typed once when it was approved. Nothing in the folder runs before someone has
read it and approved it, and approving answers whether it's risky (risky ones ask before every
run). An approval holds the file's fingerprint (SHA-256): a file changed since is "changed,
review before use" again, and the bytes that run are the bytes that were checked. A file every
user may change can't be approved at all.

A file on the PC: a `.onpc` text file in the folder names a script that's already on each PC
(`C:\\ProgramData\\Scripts\\printers.cmd`, or with %ProgramData%). CapyPanel sends a small
launcher that runs that file with the same arguments. The PC's copy can't be reviewed here, so
before running it as anyone but the person signed in, the launcher reads its permissions on the
PC (never changes them) and refuses when every user can change it: someone could edit it and
have it run with an admin's or SYSTEM's rights."""

import hashlib
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.remote.run import Language, RunAs, Script

EXTENSIONS = {".ps1": Language.POWERSHELL, ".bat": Language.BATCH, ".cmd": Language.BATCH}
ON_PC = ".onpc"  # names a script already on each PC
# A file on the PC: a drive or an environment variable first, and one of the script kinds.
_ON_PC_PATH = re.compile(r'^(?:[A-Za-z]:\\|%\w+%\\)[^<>|"*?\r\n]+\.(?:ps1|bat|cmd)$', re.IGNORECASE)
MAX_SIZE = 512 * 1024  # bytes: a script, not a program


class State(StrEnum):
    READY = "ready"  # approved, unchanged since
    NEW = "new"  # never approved
    CHANGED = "changed"  # approved, then changed
    OPEN = "open"  # every user may change it: it can't be approved
    TOO_BIG = "too-big"
    UNREADABLE = "unreadable"
    NO_PATH = "no-path"  # a .onpc file that doesn't name a script on the PC


@dataclass(frozen=True)
class Approval:
    digest: str  # SHA-256 of the file as it was approved, in hex
    risky: bool  # asks before every run
    arguments: str = ""  # after the host's name, as typed
    run_as: RunAs = RunAs.ACCOUNT
    locked: bool = False  # always runs as run_as: no other choice at run time


@dataclass(frozen=True)
class OwnScript:
    file: Path
    language: Language
    state: State
    code: bytes = b""  # what was read, and what runs
    digest: str = ""
    approval: Approval | None = None  # kept even when the file changed, for the next review
    on_pc: str = ""  # a .onpc file: the script on the PC it names

    @property
    def name(self) -> str:
        return self.file.stem

    @property
    def id(self) -> str:
        """Its host-command id, stable while the file keeps its name."""
        return "own:" + self.file.name.casefold()

    @property
    def ready(self) -> bool:
        return self.state is State.READY


def scan(folder: Path, approvals: Mapping[str, Approval]) -> list[OwnScript]:
    """The scripts in `folder` (not its subfolders), by name. `approvals` by file name, case-
    folded. Raises OSError when the folder can't be read."""
    found = [
        read(path, approvals.get(path.name.casefold()))
        for path in folder.iterdir()
        if path.suffix.casefold() in (*EXTENSIONS, ON_PC) and path.is_file()
    ]
    return sorted(found, key=lambda s: s.name.casefold())


def read(path: Path, approval: Approval | None) -> OwnScript:
    """One script as it is now, checked against its approval."""
    language = EXTENSIONS.get(path.suffix.casefold(), Language.POWERSHELL)  # .onpc: a launcher
    try:
        if path.stat().st_size > MAX_SIZE:
            return OwnScript(path, language, State.TOO_BIG, approval=approval)
        code = path.read_bytes()
    except OSError:
        return OwnScript(path, language, State.UNREADABLE, approval=approval)
    if len(code) > MAX_SIZE:
        return OwnScript(path, language, State.TOO_BIG, approval=approval)
    digest = hashlib.sha256(code).hexdigest()
    on_pc = pc_path(code) if path.suffix.casefold() == ON_PC else ""
    if path.suffix.casefold() == ON_PC and not on_pc:
        return OwnScript(path, language, State.NO_PATH, code, digest, approval)
    if winsec.anyone_can_change(path):
        state = State.OPEN
    elif approval is None:
        state = State.NEW
    elif approval.digest != digest:
        state = State.CHANGED
    else:
        state = State.READY
    return OwnScript(path, language, state, code, digest, approval, on_pc)


def pc_path(code: bytes) -> str:
    """The script a .onpc file names: its first line that isn't empty or a # note, quotes
    taken off; "" when that isn't a .ps1, .bat or .cmd path on a drive or under a %VARIABLE%."""
    text = code.decode("utf-8-sig", "replace")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            line = line.strip('"').strip()
            return line if _ON_PC_PATH.match(line) else ""
    return ""


def split_arguments(typed: str) -> list[str]:
    """`-Name "Front desk" C:\\Temp` → ["-Name", "Front desk", "C:\\Temp"]: quotes group,
    backslashes stay as they are. Raises ValueError on a quote left open."""
    lexer = shlex.shlex(typed, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)


def to_script(own: OwnScript, host: str, run_as: RunAs = RunAs.ACCOUNT) -> Script:
    """What runs: the bytes read and checked, called with the host's name and its arguments; for
    a file on the PC, the launcher, which checks the file first unless it runs as the person."""
    if not own.ready or own.approval is None:
        raise ValueError(f"{own.file.name} isn't approved as it is")
    arguments = (host, *split_arguments(own.approval.arguments))
    if own.on_pc:
        check = "$true" if run_as is not RunAs.USER else "$false"
        launcher = _LAUNCHER.replace("__PATH__", _quote(own.on_pc)).replace("__CHECK__", check)
        return Script(own.name, Language.POWERSHELL, launcher.encode("utf-8"), arguments)
    return Script(own.name, own.language, own.code, arguments)


class PcProblem(StrEnum):
    MISSING = "missing"  # the PC has no file there
    OPEN = "open"  # every user can change it there


_MARK = "CAPYPANEL-ONPC "


def pc_problem(output: str) -> PcProblem | None:
    """Why the launcher didn't run the file on the PC, from what it wrote."""
    for line in output.splitlines():
        if line.startswith(_MARK) and line[len(_MARK) :].strip() in set(PcProblem):
            return PcProblem(line[len(_MARK) :].strip())
    return None


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


# Runs the PC's own file with the arguments it was given. Before that, unless it runs as the
# person signed in, it reads who may change the file (and replace it, through its folder): every
# user (Everyone, Users, Authenticated Users, Domain Users…) means it doesn't run. Read only.
_LAUNCHER = r"""
$path = [Environment]::ExpandEnvironmentVariables(__PATH__)
if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { 'CAPYPANEL-ONPC missing'; exit 1 }
if (__CHECK__) {
  $everyone = @('S-1-1-0', 'S-1-5-11', 'S-1-5-4', 'S-1-5-7', 'S-1-5-32-545', 'S-1-5-32-546')
  function Open([string]$item, [int64]$mask) {
    try { $acl = Get-Acl -LiteralPath $item -ErrorAction Stop } catch { return $true }
    $sid = [Security.Principal.SecurityIdentifier]
    foreach ($rule in $acl.GetAccessRules($true, $true, $sid)) {
      if ($rule.AccessControlType -ne 'Allow') { continue }
      if ($rule.PropagationFlags -band [Security.AccessControl.PropagationFlags]::InheritOnly) {
        continue
      }
      if (([int64]$rule.FileSystemRights -band $mask) -eq 0) { continue }
      $who = $rule.IdentityReference.Value
      if ($everyone -contains $who -or $who -match '^S-1-5-21-.+-51[34]$') { return $true }
    }
    $false
  }
  # The file: write, append, delete, permissions, owner, generic write or all. Its folder:
  # delete what's in it, permissions, owner, generic all.
  $file = 0x2 -bor 0x4 -bor 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40000000 -bor 0x10000000
  $folder = 0x40 -bor 0x40000 -bor 0x80000 -bor 0x10000000
  if ((Open $path $file) -or (Open (Split-Path -LiteralPath $path) $folder)) {
    'CAPYPANEL-ONPC open'; exit 1
  }
}
$global:LASTEXITCODE = 0
& $path @args
if ($LASTEXITCODE) { exit $LASTEXITCODE }
if (-not $?) { exit 1 }
exit 0
"""


# ---- approvals, as kept in the settings file ----


def approvals_from(saved: object) -> dict[str, Approval]:
    """Approvals from the settings file; anything malformed is left out (a review again)."""
    kept: dict[str, Approval] = {}
    if not isinstance(saved, dict):
        return kept
    for name, value in saved.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            continue
        digest, risky = value.get("sha256"), value.get("risky")
        arguments, locked = value.get("arguments", ""), value.get("locked", False)
        run_as = value.get("run_as")
        if not (isinstance(digest, str) and isinstance(risky, bool) and isinstance(arguments, str)
                and isinstance(locked, bool) and run_as in set(RunAs)):  # fmt: skip
            continue
        kept[name.casefold()] = Approval(digest, risky, arguments, RunAs(run_as), locked)
    return kept


def approvals_to(approvals: Mapping[str, Approval]) -> dict[str, Any]:
    return {
        name: {"sha256": a.digest, "risky": a.risky, "arguments": a.arguments,
               "run_as": str(a.run_as), "locked": a.locked}
        for name, a in sorted(approvals.items())
    }  # fmt: skip
