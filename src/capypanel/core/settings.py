"""Where the app keeps its files, portable mode, and the settings file.

Everything lives in one folder per computer, C:\\ProgramData\\CapyPanel (or <app>\\userdata when
portable): users\\<user@DOMAIN>\\ holds each user's settings, personal list, tools and profiles,
private to that user and administrators; logs\\<user@DOMAIN>.log holds one log per user."""

import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.i18n import _

log = logging.getLogger(__name__)

APP_ID = "CapyPanel"  # internal folder name; stays the same if the product is renamed
PORTABLE_MARKER = "capypanel.portable"
SETTINGS_SCHEMA = 1
_NOT_IN_FILE_NAMES = '<>:"/\\|?*'


class UserFolderError(Exception):
    """The user's folder belongs to someone else, so it isn't safe to use."""


def app_dir() -> Path:
    """The folder with the executable when packaged, or the repository root from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Paths:
    root: Path  # ProgramData\CapyPanel, or <app>\userdata when portable
    account: str  # "user@DOMAIN": names this user's folder and log file
    portable: bool

    @property
    def user_dir(self) -> Path:
        return self.root / "users" / self.account

    @property
    def log_dir(self) -> Path:
        return self.root / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / f"{self.account}.log"

    @property
    def settings_file(self) -> Path:
        return self.user_dir / "settings.json"

    @property
    def personal_list(self) -> Path:
        return self.user_dir / "hosts.json"

    @property
    def user_tools_dir(self) -> Path:
        return self.user_dir / "tools"

    @property
    def user_profiles_dir(self) -> Path:
        return self.user_dir / "profiles"


def resolve_paths(
    folder: Path | None = None,
    env: Mapping[str, str] | None = None,
    account: str | None = None,
) -> Paths:
    """ProgramData normally; a marker file next to the app means portable (in the app folder)."""
    folder = folder if folder is not None else app_dir()
    name = account if account is not None else winsec.account_name()
    name = "".join("_" if c in _NOT_IN_FILE_NAMES else c for c in name)
    if (folder / PORTABLE_MARKER).exists():
        return Paths(root=folder / "userdata", account=name, portable=True)
    env = os.environ if env is None else env
    return Paths(root=Path(env["PROGRAMDATA"]) / APP_ID, account=name, portable=False)


def ensure_dirs(paths: Paths) -> None:
    """Create the user's folder, private to them. The user layer starts empty: presets are
    never copied. Raises UserFolderError if someone else made the folder first."""
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    paths.user_dir.mkdir(parents=True, exist_ok=True)
    me = winsec.current_user_sid()
    owner = winsec.owner_sid(paths.user_dir)
    # Anyone can create folders in ProgramData, so another user could have made "ours" first.
    if owner is not None and owner not in (me, winsec.ADMINISTRATORS, winsec.SYSTEM):
        raise UserFolderError(
            _(
                "The folder “{folder}” was created by another user, so CapyPanel won't use it. "
                "Ask an administrator to delete it; it will be created again."
            ).format(folder=paths.user_dir)
        )
    try:
        winsec.make_private(paths.user_dir, me)  # every start: repairs changed permissions
    except OSError as e:
        log.warning("Couldn't make %s private: %s", paths.user_dir, e)
    for folder in (paths.user_tools_dir, paths.user_profiles_dir):
        folder.mkdir(exist_ok=True)


def load_settings(path: Path) -> dict[str, Any]:
    """Read settings; a missing file gives defaults, a corrupt one is set aside, not overwritten."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": SETTINGS_SCHEMA}
    except ValueError:
        path.replace(path.with_name(path.name + ".broken"))
        return {"schema": SETTINGS_SCHEMA}
    if not isinstance(data, dict):
        path.replace(path.with_name(path.name + ".broken"))
        return {"schema": SETTINGS_SCHEMA}
    return data


def save_settings(path: Path, data: Mapping[str, Any]) -> None:
    """Write to a temp file, then swap it in, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
