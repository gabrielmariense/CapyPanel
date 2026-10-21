"""Where the app keeps its files, portable mode, and the settings file.

Everything lives in one folder per computer, C:\\ProgramData\\CapyPanel (or <app>\\userdata when
portable). Shared by everyone on the PC: lists\\ (a folder per tool, e.g. lists\\hosts\\, with its
default list and any shared list), profiles\\ and tools\\ (the company's tool definitions and where
each tool is installed). users\\<user@DOMAIN>\\ holds each user's settings and lists\\ (again a
folder per tool, with the personal list and their own lists), private to that user and
administrators; logs\\<user@DOMAIN>.log, one per user."""

import copy
import json
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capypanel.core import files, winsec
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
class ListPlaces:
    """Where one tool keeps its lists."""

    shared_dir: Path  # lists saved here show up for everyone on the PC, with no adding
    user_dir: Path  # this user's own: lists saved here show up for them only

    @property
    def default(self) -> Path:
        return self.shared_dir / "default.json"

    @property
    def personal(self) -> Path:
        return self.user_dir / "personal.json"


@dataclass(frozen=True)
class Paths:
    root: Path  # ProgramData\CapyPanel, or <app>\userdata when portable
    account: str  # "user@DOMAIN": names this user's folder and log file
    portable: bool

    @property
    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    @property
    def company_tools_dir(self) -> Path:
        return self.root / "tools"

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
    def lists_dir(self) -> Path:
        """Every tool's shared lists, in a folder per tool."""
        return self.root / "lists"

    @property
    def user_lists_dir(self) -> Path:
        """This user's own lists, in a folder per tool."""
        return self.user_dir / "lists"

    def lists(self, tool_id: str) -> ListPlaces:
        """One tool's lists folders, shared and the user's own: lists\\<tool id>\\."""
        return ListPlaces(self.lists_dir / tool_id, self.user_lists_dir / tool_id)


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
    """Create the user's folder, private to them. Its tools subfolder is created
    only when something is first saved there. Raises UserFolderError if someone else made
    the folder first."""
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


def load_settings(path: Path) -> dict[str, Any]:
    """Read settings; a missing file gives defaults, a corrupt one is set aside, not overwritten."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": SETTINGS_SCHEMA}
    except ValueError:
        data = None
    if not isinstance(data, dict):
        path.replace(path.with_name(path.name + ".broken"))
        return {"schema": SETTINGS_SCHEMA}
    return data


TOOLS_KEY = "tools"  # each tool's own settings, by tool id
TOOLS_OFF_KEY = "tools_off"  # the ids of the tools turned off: they don't load
TOOL_KEY = "tool"  # the tool shown last
# What the window shows at start: the Home page, the tool shown last, or a tool's id.
START_KEY, START_HOME, START_LAST = "start", "home", "last"
# The shell's own settings; everything else at the top level was the Hosts tool's before 0.20.
SHELL_KEYS = frozenset(
    {
        "schema",
        "window_geometry",
        "settings_geometry",
        "theme",
        "language",
        TOOL_KEY,
        TOOLS_KEY,
        TOOLS_OFF_KEY,
        START_KEY,
    }
)


def tool_prefs(prefs: dict[str, Any], tool_id: str, *, inherit: bool = False) -> dict[str, Any]:
    """A tool's own section of the settings, made the first time it's asked for. With `inherit`
    (Hosts), a new section starts from what 0.19 kept at the top level, which stays there too, so
    an older version still reads it."""
    tools = prefs.get(TOOLS_KEY)
    if not isinstance(tools, dict):
        tools = prefs[TOOLS_KEY] = {}
    section = tools.get(tool_id)
    if not isinstance(section, dict):
        section = {}
        if inherit:
            section = {k: copy.deepcopy(v) for k, v in prefs.items() if k not in SHELL_KEYS}
        tools[tool_id] = section
    return section


def save_settings(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    files.write_json(path, dict(data))
