"""A short command line that stands for a long one.

Starting a program with an account for the network only (as `runas /netonly` does) goes through
Windows' CreateProcessWithLogonW, which takes a command line of 1024 characters at most. The
command that runs a script on another PC is several thousand. So CapyPanel starts itself again
with a short line, `--relay <file>`, and that copy reads the real command from the file and runs
it. What it starts keeps the account, as anything started by a /netonly program does.

The file holds the command only, never a password; it's in the user's own temp folder and is
deleted as soon as it's read. This module imports nothing of CapyPanel's, so the copy starts
fast and shows no window."""

import contextlib
import ctypes
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from typing import NoReturn

FLAG = "--relay"


def command(file: str) -> list[str]:
    """The command that starts CapyPanel as a relay for the command kept in `file`."""
    module = [] if getattr(sys, "frozen", False) else ["-m", "capypanel"]  # one .exe, or Python
    return [sys.executable, *module, FLAG, file]


def write(file: str, argv: Sequence[str]) -> None:
    with open(file, "w", encoding="utf-8") as kept:
        json.dump(list(argv), kept)


def main(file: str) -> NoReturn:
    """Runs the command kept in `file`, out of sight, and ends with its exit code exactly (PsExec
    answers with a process ID there, which can be any 32-bit number)."""
    try:
        with open(file, encoding="utf-8") as kept:
            argv = json.load(kept)
        with contextlib.suppress(OSError):
            os.unlink(file)
        code = subprocess.run(
            argv, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW
        ).returncode
    except OSError as e:  # the program isn't there, or wasn't allowed to start
        code = e.winerror or 1
    except ValueError:
        code = 1
    ctypes.windll.kernel32.ExitProcess(ctypes.c_uint(code & 0xFFFFFFFF))
    raise SystemExit(code)  # never reached
