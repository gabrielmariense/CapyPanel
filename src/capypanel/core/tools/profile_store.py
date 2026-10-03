"""Where connection profiles come from: one built-in per tool (read-only, inside the app) and the
shared ones in <app>\\data\\profiles, next to the default list, the same for every user of the
app. Windows permissions on that folder decide who can change them, as for the default list."""

import json
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from capypanel.core.i18n import _
from capypanel.core.tools import profiles
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError

log = logging.getLogger(__name__)
SHIPPED_DIR = Path(__file__).resolve().parent / "presets" / "profiles"
BUILT_IN_DEFAULT = "ultravnc"
SETTINGS_FILE = "connections.json"  # in the data folder; holds the default profile

# Built-ins of version 0.8, retired for one per tool. Lists may still name them, so they keep
# working, but they're no longer offered for new hosts.
RETIRED = {
    pid: ConnectionProfile(pid, tool, login, options, name=name)
    for pid, tool, login, options, name in (
        ("ultravnc-password", "ultravnc", "password", (), "UltraVNC — password only"),
        ("ultravnc-account", "ultravnc", "account", (), "UltraVNC — user and password"),
        ("ultravnc-password-securevnc", "ultravnc", "password", ("securevnc",),
         "UltraVNC — password only + SecureVNC"),
        ("ultravnc-account-securevnc", "ultravnc", "account", ("securevnc",),
         "UltraVNC — user and password + SecureVNC"),
        ("realvnc-password", "realvnc", "password", (), "RealVNC — password only"),
        ("realvnc-account", "realvnc", "account", (), "RealVNC — user and password"),
    )
}  # fmt: skip


class Origin(StrEnum):
    BUILT_IN = "built-in"
    SHARED = "shared"
    RETIRED = "retired"


@dataclass(frozen=True)
class Stored:
    profile: ConnectionProfile
    origin: Origin

    @property
    def editable(self) -> bool:
        return self.origin is Origin.SHARED


class ProfileStore:
    def __init__(self, data_dir: Path, shipped_dir: Path = SHIPPED_DIR) -> None:
        self.folder = data_dir / "profiles"
        self._settings = data_dir / SETTINGS_FILE
        self._shipped = shipped_dir
        self.problems: list[tuple[Path, str]] = []
        self._built_in: dict[str, ConnectionProfile] = {}
        self._shared: dict[str, ConnectionProfile] = {}
        self.reload()

    def reload(self) -> None:
        self.problems = []
        self._built_in = dict(self._load_folder(self._shipped))
        self._shared = {}
        for pid, profile in self._load_folder(self.folder):
            if pid in self._built_in or pid in RETIRED:
                # A built-in can't be replaced, only duplicated under its own id.
                self.problems.append((self.folder / f"{pid}.json", _("Uses a built-in id.")))
                continue
            self._shared[pid] = profile

    def _load_folder(self, folder: Path) -> list[tuple[str, ConnectionProfile]]:
        found = []
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                profile = profiles.load(path)
            except ProfileError as e:
                self.problems.append((path, str(e)))
                log.warning("Connection profile %s skipped: %s", path, e)
                continue
            found.append((profile.id, profile))
        return found

    # ---- reading ----

    def all(self) -> list[Stored]:
        """Built-ins first, then the shared ones by name. Retired ones are left out."""
        built_in = [Stored(p, Origin.BUILT_IN) for p in self._built_in.values()]
        shared = sorted(self._shared.values(), key=lambda p: p.name.casefold())
        return built_in + [Stored(p, Origin.SHARED) for p in shared]

    def find(self, profile_id: str) -> Stored | None:
        if profile_id in self._built_in:
            return Stored(self._built_in[profile_id], Origin.BUILT_IN)
        if profile_id in self._shared:
            return Stored(self._shared[profile_id], Origin.SHARED)
        if profile_id in RETIRED:
            return Stored(RETIRED[profile_id], Origin.RETIRED)
        return None

    def default_id(self) -> str:
        try:
            data = json.loads(self._settings.read_text(encoding="utf-8-sig"))
            wanted = data.get("default_profile") if isinstance(data, dict) else None
        except (OSError, ValueError):
            wanted = None
        if isinstance(wanted, str) and self.find(wanted) is not None:
            return wanted
        return BUILT_IN_DEFAULT

    def can_edit(self) -> bool:
        """Whether Windows lets this user create and change files in the profiles folder."""
        folder = self.folder
        while not folder.exists() and folder.parent != folder:
            folder = folder.parent  # the folder is made on the first save
        try:
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".capypanel-", suffix=".tmp"):
                pass
        except OSError:
            return False
        return True

    # ---- changing (shared profiles only) ----

    def new_id(self, name: str) -> str:
        """An id made from the name ("Clinics (SecureVNC)" -> "clinics-securevnc"), unused."""
        plain = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
        base = re.sub(r"[^a-z0-9]+", "-", plain)
        base = base.strip("-")[:48] or "profile"
        candidate, number = base, 2
        while self.find(candidate) is not None:
            candidate, number = f"{base}-{number}", number + 1
        return candidate

    def save(self, profile: ConnectionProfile) -> None:
        """Writes a shared profile, new or changed. Raises ProfileError or OSError."""
        existing = self.find(profile.id)
        if existing is not None and not existing.editable:
            raise ProfileError(_("Built-in profiles can't be changed, only duplicated."))
        self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        log.info("Connection profile saved: %s (%s)", profile.id, profile.name)
        self.reload()

    def delete(self, profile_id: str) -> None:
        existing = self.find(profile_id)
        if existing is None or not existing.editable:
            raise ProfileError(_("Built-in profiles can't be deleted."))
        (self.folder / f"{profile_id}.json").unlink(missing_ok=True)
        log.info("Connection profile deleted: %s (%s)", profile_id, existing.profile.name)
        self.reload()  # if it was the default, default_id() now falls back to the built-in

    def set_default(self, profile_id: str) -> None:
        if self.find(profile_id) is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._write(self._settings, {"schema": 1, "default_profile": profile_id})
        log.info("Default connection profile: %s", profile_id)

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
