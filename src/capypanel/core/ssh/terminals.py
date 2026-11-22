import ctypes
import logging
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from ctypes import wintypes as wt
from dataclasses import dataclass
from pathlib import Path

from capypanel.core.i18n import _

log = logging.getLogger(__name__)
KEY = "terminal"
READY_KEY, PROGRAM_KEY, ARGUMENTS_KEY = "ready", "program", "arguments"
SSH, NAME = "{ssh}", "{name}"
_PLACEHOLDER = re.compile(r"\{(ssh|name)\}")
# Names come from the list as typed: only one no shell could misread reaches the program.
_PLAIN_NAME = re.compile(r"[^\W_][\w.-]{0,99}\Z")


@dataclass(frozen=True)
class Ready:
    id: str
    name: str
    paths: tuple[str, ...]
    arguments: str


READY = (
    Ready(
        "windows-terminal",
        "Windows Terminal",
        (r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe",),
        f"new-tab --title {NAME} -- {SSH}",
    ),
)


@dataclass(frozen=True)
class Terminal:
    program: Path
    arguments: str
    ready: str = ""

    @property
    def name(self) -> str:
        found = next((r for r in READY if r.id == self.ready), None)
        return found.name if found is not None else self.program.name


def ready_here(env: Mapping[str, str] | None = None) -> list[Terminal]:
    found = []
    for ready in READY:
        path = _locate(ready, env)
        if path is not None:
            found.append(Terminal(path, ready.arguments, ready.id))
    return found


def from_prefs(value: object, env: Mapping[str, str] | None = None) -> Terminal | None:
    if not isinstance(value, Mapping):
        return None
    ready_id = value.get(READY_KEY)
    if ready_id is not None:
        ready = next((r for r in READY if r.id == ready_id), None)
        where = _expand(ready.paths[0], env) if ready is not None else ""
        if ready is None or not where:
            return None
        return Terminal(_locate(ready, env) or Path(where), ready.arguments, ready.id)
    program, arguments = value.get(PROGRAM_KEY), value.get(ARGUMENTS_KEY)
    if not (isinstance(program, str) and isinstance(arguments, str)):
        return None
    if not Path(program).is_absolute() or problem(program, arguments, look=False):
        return None
    return Terminal(Path(program), arguments)


def to_prefs(terminal: Terminal) -> dict[str, str]:
    if terminal.ready:
        return {READY_KEY: terminal.ready}
    return {PROGRAM_KEY: str(terminal.program), ARGUMENTS_KEY: terminal.arguments}


def problem(program: str, arguments: str, *, look: bool = True) -> str:
    path = Path(program.strip())
    if not program.strip():
        return _("Pick the program.")
    # A .bat or .cmd would hand the arguments to cmd.exe, which reads them its own way.
    if path.suffix.casefold() != ".exe":
        return _("Pick a program: a file whose name ends in .exe.")
    if look and not (path.is_absolute() and path.is_file()):
        return _("There's no program at this path.")
    if SSH not in arguments:
        return _("The arguments need {ssh}, where the program takes the command it runs.")
    return ""


def command(terminal: Terminal, ssh_argv: Sequence[str], name: str) -> list[str]:
    """ssh_argv must come from launch.command_line, which checks it."""
    title = name if _PLAIN_NAME.match(name) else ssh_argv[-1]
    joined = subprocess.list2cmdline(ssh_argv)
    argv = [str(terminal.program)]
    for arg in split(terminal.arguments):
        if arg == SSH:
            argv.extend(ssh_argv)
        else:
            argv.append(_PLACEHOLDER.sub(lambda m: joined if m[1] == "ssh" else title, arg))
    return argv


def start(terminal: Terminal, ssh_argv: Sequence[str], name: str) -> subprocess.Popen[bytes]:
    argv = command(terminal, ssh_argv, name)
    log.info("Starting %s for ssh.exe %s", terminal.name, subprocess.list2cmdline(ssh_argv[1:]))
    home = Path.home()
    return subprocess.Popen(  # noqa: S603 -- the person's own program; ssh.exe's arguments checked
        argv,
        executable=str(terminal.program),
        # Ignored by a windowed program; a console one, such as cmd.exe, gets a window of its own.
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        cwd=home if home.is_dir() else None,
        close_fds=True,
    )


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.CommandLineToArgvW.argtypes = (wt.LPCWSTR, ctypes.POINTER(ctypes.c_int))
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(wt.LPWSTR)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.LocalFree.argtypes = (ctypes.c_void_p,)
_k32.LocalFree.restype = ctypes.c_void_p


def split(arguments: str) -> list[str]:
    count = ctypes.c_int()
    # The first word follows other rules, and an empty line would give this program's own path.
    found = _shell32.CommandLineToArgvW("x " + arguments, ctypes.byref(count))
    if not found:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [found[i] for i in range(1, count.value)]
    finally:
        _k32.LocalFree(ctypes.cast(found, ctypes.c_void_p))


def _locate(ready: Ready, env: Mapping[str, str] | None) -> Path | None:
    for raw in ready.paths:
        expanded = _expand(raw, env)
        if expanded and Path(expanded).is_file():
            return Path(expanded)
    return None


def _expand(raw: str, env: Mapping[str, str] | None) -> str:
    values = os.environ if env is None else env
    missing = False

    def value(match: re.Match[str]) -> str:
        nonlocal missing
        found = values.get(match[1])
        missing = missing or not found
        return found or ""

    expanded = re.sub(r"%([^%]+)%", value, raw)
    return "" if missing else expanded
