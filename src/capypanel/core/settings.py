"""Where the app keeps its files, portable mode, and the settings file (DECISIONS §9)."""

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APP_ID = "CapyPanel"  # internal folder name; stays the same if the product is renamed
PORTABLE_MARKER = "capypanel.portable"
SETTINGS_SCHEMA = 1


def app_dir() -> Path:
    """The folder with the executable when packaged, or the repository root from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Paths:
    settings_dir: Path
    log_dir: Path
    portable: bool

    @property
    def settings_file(self) -> Path:
        return self.settings_dir / "settings.json"

    @property
    def user_tools_dir(self) -> Path:
        return self.settings_dir / "tools"

    @property
    def user_profiles_dir(self) -> Path:
        return self.settings_dir / "profiles"


def resolve_paths(folder: Path | None = None, env: Mapping[str, str] | None = None) -> Paths:
    """Normal mode uses the Windows profile folders; a marker next to the app means portable."""
    folder = folder if folder is not None else app_dir()
    if (folder / PORTABLE_MARKER).exists():
        data = folder / "userdata"
        return Paths(settings_dir=data, log_dir=data / "logs", portable=True)
    env = os.environ if env is None else env
    return Paths(
        settings_dir=Path(env["APPDATA"]) / APP_ID,
        log_dir=Path(env["LOCALAPPDATA"]) / APP_ID,
        portable=False,
    )


def ensure_dirs(paths: Paths) -> None:
    """Create the app's own folders. The user layer starts empty: presets are never copied."""
    for folder in (
        paths.settings_dir,
        paths.log_dir,
        paths.user_tools_dir,
        paths.user_profiles_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)


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
