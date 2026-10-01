"""Starting a remote tool for one target, and the passwords typed this session (memory only)."""

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from capypanel.core.tools.definitions import SECRET, ToolDefinition, command_line, redacted

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Credential:
    user: str
    password: str


class SessionCredentials:
    """Passwords typed while the app runs, per tool. Never written anywhere: gone on exit."""

    def __init__(self) -> None:
        self._by_tool: dict[str, Credential] = {}

    def get(self, tool_id: str) -> Credential | None:
        return self._by_tool.get(tool_id)

    def remember(self, tool_id: str, credential: Credential) -> None:
        self._by_tool[tool_id] = credential

    def forget(self, tool_id: str | None = None) -> None:
        if tool_id is None:
            self._by_tool.clear()
        else:
            self._by_tool.pop(tool_id, None)

    def __bool__(self) -> bool:
        return bool(self._by_tool)


@dataclass(frozen=True)
class Target:
    address: str
    port: int | None = None


def launch(
    tool: ToolDefinition,
    executable: Path,
    target: Target,
    credential: Credential | None = None,
) -> subprocess.Popen[bytes]:
    """Starts the tool and returns at once; the tool runs on its own. Raises OSError."""
    port = target.port if target.port is not None else tool.port
    values = {
        "address": target.address,
        "port": str(port) if port is not None else "",
        "user": credential.user if credential else "",
        SECRET: credential.password if credential else "",
    }
    argv = command_line(tool, executable, values)
    log.info("Starting %s: %s", tool.id, redacted(argv, [values[SECRET]]))
    return subprocess.Popen(
        argv,
        cwd=executable.parent,  # some tools look for their DLLs and settings next to them
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
