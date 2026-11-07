"""Your own scripts: PowerShell and batch files in one scripts folder, written in any editor and
run on a PC through core.remote.run.

A script is called as `script <host> <arguments>`: the host's name as CapyPanel knows it, then
the arguments typed once when it was approved. Nothing in the folder runs before someone has
read it and approved it, and approving answers whether it's risky (risky ones ask before every
run). An approval holds the file's fingerprint (SHA-256): a file changed since is "changed,
review before use" again, and the bytes that run are the bytes that were checked. A file every
user may change can't be approved at all."""

import hashlib
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.remote.run import Language, RunAs, Script

EXTENSIONS = {".ps1": Language.POWERSHELL, ".bat": Language.BATCH, ".cmd": Language.BATCH}
MAX_SIZE = 512 * 1024  # bytes: a script, not a program


class State(StrEnum):
    READY = "ready"  # approved, unchanged since
    NEW = "new"  # never approved
    CHANGED = "changed"  # approved, then changed
    OPEN = "open"  # every user may change it: it can't be approved
    TOO_BIG = "too-big"
    UNREADABLE = "unreadable"


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
        if path.suffix.casefold() in EXTENSIONS and path.is_file()
    ]
    return sorted(found, key=lambda s: s.name.casefold())


def read(path: Path, approval: Approval | None) -> OwnScript:
    """One script as it is now, checked against its approval."""
    language = EXTENSIONS[path.suffix.casefold()]
    try:
        if path.stat().st_size > MAX_SIZE:
            return OwnScript(path, language, State.TOO_BIG, approval=approval)
        code = path.read_bytes()
    except OSError:
        return OwnScript(path, language, State.UNREADABLE, approval=approval)
    if len(code) > MAX_SIZE:
        return OwnScript(path, language, State.TOO_BIG, approval=approval)
    digest = hashlib.sha256(code).hexdigest()
    if winsec.anyone_can_change(path):
        state = State.OPEN
    elif approval is None:
        state = State.NEW
    elif approval.digest != digest:
        state = State.CHANGED
    else:
        state = State.READY
    return OwnScript(path, language, state, code, digest, approval)


def split_arguments(typed: str) -> list[str]:
    """`-Name "Front desk" C:\\Temp` → ["-Name", "Front desk", "C:\\Temp"]: quotes group,
    backslashes stay as they are. Raises ValueError on a quote left open."""
    lexer = shlex.shlex(typed, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    return list(lexer)


def to_script(own: OwnScript, host: str) -> Script:
    """What runs: the bytes read and checked, called with the host's name and its arguments."""
    if not own.ready or own.approval is None:
        raise ValueError(f"{own.file.name} isn't approved as it is")
    arguments = (host, *split_arguments(own.approval.arguments))
    return Script(own.name, own.language, own.code, arguments)


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
