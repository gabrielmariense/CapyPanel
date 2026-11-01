"""Starting a remote tool for one target, and the passwords typed for it (in memory, or saved
in Windows Credential Manager when the user chose so)."""

import logging
import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from capypanel.core import credstore
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


SAVED = "profile/"  # saved passwords: CapyPanel/profile/<profile id> in Credential Manager


class SessionCredentials:
    """Passwords typed while the app runs, one per connection profile: in memory until the app
    closes, and also in Windows Credential Manager when the user chose to save them. Per
    profile, so the Windows-account password never reaches the Pis."""

    def __init__(self, saving: bool = False) -> None:
        self._by_profile: dict[str, Credential] = {}
        self.saving = saving

    def set_saving(self, saving: bool) -> None:
        """Off again deletes every saved password; the ones typed this session stay in memory.
        Raises OSError."""
        self.saving = saving
        if not saving:
            self._delete_saved(None)

    def get(self, profile_id: str) -> Credential | None:
        found = self._by_profile.get(profile_id)
        if found is None and self.saving:
            found = self._load(profile_id)
            if found is not None:
                self._by_profile[profile_id] = found
        return found

    def remember(self, profile_id: str, credential: Credential) -> None:
        """Raises OSError or ValueError when it couldn't be saved; it's kept in memory anyway."""
        self._by_profile[profile_id] = credential
        if self.saving:
            credstore.save(SAVED + profile_id, credential.password, user=credential.user)

    def forget(self, profile_id: str | None = None) -> None:
        """Also deletes the saved password, saving or not. Raises OSError."""
        if profile_id is None:
            self._by_profile.clear()
        else:
            self._by_profile.pop(profile_id, None)
        self._delete_saved(profile_id)

    def kept(self) -> list[tuple[str, Credential, bool]]:
        """Every password kept: (profile id, credential, saved in Credential Manager), by id.
        Saved ones are listed even with saving off, when Windows didn't delete them."""
        saved = {name.removeprefix(SAVED) for name in self._saved_names()}
        found = []
        for profile_id in sorted(set(self._by_profile) | saved):
            credential = self._by_profile.get(profile_id) or self._load(profile_id)
            if credential is not None:
                found.append((profile_id, credential, profile_id in saved))
        return found

    def __contains__(self, profile_id: str) -> bool:
        return self.get(profile_id) is not None

    def __bool__(self) -> bool:
        return bool(self._by_profile) or bool(self.saving and self._saved_names())

    def _load(self, profile_id: str) -> Credential | None:
        try:
            found = credstore.read(SAVED + profile_id)
        except OSError as e:
            log.warning("Couldn't read the saved password of %s: %s", profile_id, e)
            return None
        return Credential(*found) if found is not None else None

    def _saved_names(self) -> list[str]:
        try:
            return credstore.names(SAVED)
        except OSError as e:
            log.warning("Couldn't list the saved passwords: %s", e)
            return []

    def _delete_saved(self, profile_id: str | None) -> None:
        names = self._saved_names() if profile_id is None else [SAVED + profile_id]
        for name in names:
            credstore.forget(name)


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
        content = viewer_settings.read(settings, tool.settings_file.clear)
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
