"""Starting a remote tool for one target, and the passwords typed this session (memory only)."""

import logging
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from capypanel.core.tools import viewer_settings, vncpass
from capypanel.core.tools.definitions import (
    PASSWORD_FILE,
    SECRET,
    SETTINGS_FILE,
    ToolDefinition,
    command_line,
    redacted,
)
from capypanel.core.tools.pipe import SecretPipe

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Credential:
    user: str
    password: str


class SessionCredentials:
    """Passwords typed while the app runs, one per connection profile. Never written anywhere:
    gone on exit. Per profile, so the Windows-account password never reaches the Pis."""

    def __init__(self) -> None:
        self._by_profile: dict[str, Credential] = {}

    def get(self, profile_id: str) -> Credential | None:
        return self._by_profile.get(profile_id)

    def remember(self, profile_id: str, credential: Credential) -> None:
        self._by_profile[profile_id] = credential

    def forget(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            self._by_profile.clear()
        else:
            self._by_profile.pop(profile_id, None)

    def __bool__(self) -> bool:
        return bool(self._by_profile)


@dataclass(frozen=True)
class Target:
    address: str
    port: int | None = None


def launch(
    tool: ToolDefinition,
    executable: Path,
    target: Target,
    credential: Credential | None = None,
    options: Collection[str] = (),
    settings: Path | None = None,
) -> subprocess.Popen[bytes]:
    """Starts the tool and returns at once; the tool runs on its own. `settings` is the profile's
    viewer settings file. Raises OSError, SettingsFileError."""
    port = target.port if target.port is not None else tool.port
    values = {
        "address": target.address,
        "port": str(port) if port is not None else "",
        "user": credential.user if credential else "",
        SECRET: credential.password if credential else "",
    }
    if settings is not None and tool.settings_file is not None:
        # Cleaned again: someone may have edited the shared file by hand since it was chosen.
        content = viewer_settings.read(settings, tool.settings_file.remove)
        copy = viewer_settings.temp_copy(content, tool.settings_file.extension)
        values[SETTINGS_FILE] = str(copy)
    pipe = None
    if tool.credentials == "vnc_password_file" and values[SECRET]:
        pipe = SecretPipe()  # made before the program starts, so it's there when it looks
        values[PASSWORD_FILE] = pipe.path
    argv = command_line(tool, executable, values, options)
    log.info("Starting %s: %s", tool.id, redacted(argv, [values[SECRET]]))
    try:
        process = subprocess.Popen(
            argv,
            cwd=executable.parent,  # some tools look for their DLLs and settings next to them
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        if pipe is not None:
            pipe.close()
        raise
    if pipe is not None:
        pipe.serve(vncpass.obfuscate(values[SECRET]))
    return process
