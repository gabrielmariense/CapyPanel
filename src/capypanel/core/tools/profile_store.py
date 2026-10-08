"""Connection profiles live together in C:\\ProgramData\\CapyPanel\\profiles, next to the default
list: the same for everyone on the PC. Windows permissions on the folder decide who can change
them, and a file another standard user made is ignored. The app ships starter profiles (one per
tool) that fill the folder the first time it's written; after that they're ordinary profiles."""

import json
import logging
import re
import unicodedata
from collections.abc import Collection
from pathlib import Path
from typing import Any

from capypanel.core import files, winsec
from capypanel.core.files import can_create_files
from capypanel.core.i18n import _
from capypanel.core.tools import profiles
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError

log = logging.getLogger(__name__)
STARTERS_DIR = Path(__file__).resolve().parent / "presets" / "profiles"
DEFAULT_FILE = "_default.json"  # in the profiles folder; "_" can't start a profile id
STARTERS_FILE = "_starters.json"  # starters already added once, so a deleted one stays deleted


def make_id(name: str, taken: Collection[str]) -> str:
    """An id made from the name ("Clínicas (SecureVNC)" -> "clinicas-securevnc"), not taken."""
    plain = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:48] or "profile"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


class ProfileStore:
    def __init__(self, folder: Path, starters_dir: Path = STARTERS_DIR) -> None:
        self.folder = folder
        self._starters = starters_dir
        self.problems: list[tuple[Path, str]] = []
        self._profiles: dict[str, ConnectionProfile] = {}
        self.reload()

    def reload(self) -> None:
        """The folder's profiles; the starters until the folder exists. A tool's starter that
        was never added (a tool new in this version) joins the folder once."""
        self.problems = []
        source = self.folder if self.folder.is_dir() else self._starters
        self._profiles = {}
        self._load_from(source)
        if source is self.folder:
            self._add_new_starters()

    def _load_from(self, source: Path) -> None:
        for path in sorted(source.glob("*.json")):
            if path.name.startswith("_"):
                continue  # the default-profile file, not a profile
            if source is self.folder and not winsec.made_by_trusted(path):
                reason = "made by another user, so it isn't used"
                self.problems.append((path, reason))
                log.warning("Connection profile %s skipped: %s", path, reason)
                continue
            try:
                profile = profiles.load(path)
            except ProfileError as e:
                self.problems.append((path, str(e)))
                log.warning("Connection profile %s skipped: %s", path, e)
                continue
            self._profiles[profile.id] = profile

    # ---- reading ----

    def all(self) -> list[ConnectionProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.name.casefold())

    def find(self, profile_id: str) -> ConnectionProfile | None:
        return self._profiles.get(profile_id)

    def default_id(self) -> str:
        """The chosen default, else the first profile by name; "" when there are none."""
        path = self.folder / DEFAULT_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            trusted = winsec.made_by_trusted(path)
            wanted = data.get("default_profile") if isinstance(data, dict) and trusted else None
        except (OSError, ValueError):
            wanted = None
        if isinstance(wanted, str) and wanted in self._profiles:
            return wanted
        starter = "ultravnc"  # the starter default, while it exists
        if starter in self._profiles:
            return starter
        first = self.all()
        return first[0].id if first else ""

    def settings_path(self, profile: ConnectionProfile) -> Path | None:
        """The profile's viewer settings file, when it has one this PC can trust."""
        if not profile.settings_file:
            return None
        path = self.folder / profile.settings_file
        if not path.is_file() or not winsec.made_by_trusted(path):
            log.warning("Settings file %s missing or made by another user: not used", path)
            return None
        return path

    def can_edit(self) -> bool:
        """Whether Windows lets this user create and change files in the profiles folder."""
        return can_create_files(self.folder)

    # ---- changing ----

    def save(self, profile: ConnectionProfile, settings: bytes | None = None) -> None:
        """Writes a profile, new or changed, and `settings` as its new settings file (already
        cleaned). A settings file the profile no longer names is deleted. Raises OSError."""
        old = self.find(profile.id)
        self._seed()
        if settings is not None and profile.settings_file:
            files.write_atomic(self.folder / profile.settings_file, settings)
        self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        if old is not None and old.settings_file not in ("", profile.settings_file):
            (self.folder / old.settings_file).unlink(missing_ok=True)
        log.info("Connection profile saved: %s (%s)", profile.id, profile.name)
        self.reload()

    def delete(self, profile_id: str) -> None:
        profile = self.find(profile_id)
        if profile is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._seed()
        (self.folder / f"{profile_id}.json").unlink(missing_ok=True)
        if profile.settings_file:
            (self.folder / profile.settings_file).unlink(missing_ok=True)
        log.info("Connection profile deleted: %s (%s)", profile_id, profile.name)
        self.reload()  # if it was the default, default_id() picks another

    def set_default(self, profile_id: str) -> None:
        if self.find(profile_id) is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._seed()
        self._write(self.folder / DEFAULT_FILE, {"schema": 1, "default_profile": profile_id})
        log.info("Default connection profile: %s", profile_id)

    def _seed(self) -> None:
        """Before the first change, the starters become real files, so they can be removed."""
        if self.folder.is_dir():
            return
        files.make_shared_folder(self.folder)
        for profile in self._profiles.values():
            self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        self._write(self.folder / STARTERS_FILE, {"schema": 1, "added": self._starter_ids()})

    def _starter_ids(self) -> list[str]:
        return sorted(p.stem for p in self._starters.glob("*.json"))

    def _add_new_starters(self) -> None:
        """Every tool gets its starter once, even in a folder made before the tool existed."""
        path = self.folder / STARTERS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            listed = data.get("added") if isinstance(data, dict) else None
            trusted = isinstance(listed, list) and winsec.made_by_trusted(path)
            added = {str(pid) for pid in listed} if trusted and isinstance(listed, list) else set()
        except (OSError, ValueError):
            added = set()
        new = [pid for pid in self._starter_ids() if pid not in added]
        if not new:
            return
        for pid in new:
            if pid in self._profiles:
                continue  # a profile already uses that id
            try:
                starter = profiles.load(self._starters / f"{pid}.json")
            except ProfileError as e:
                log.warning("Starter profile %s skipped: %s", pid, e)
                continue
            self._profiles[pid] = starter
            try:
                self._write(self.folder / f"{pid}.json", profiles.to_data(starter))
                log.info("Starter connection profile added: %s", pid)
            except OSError:
                return  # read-only here: shown, not written, and offered again next time
        try:
            self._write(path, {"schema": 1, "added": sorted(added | set(new))})
        except OSError as e:
            log.warning("Couldn't write %s: %s", path, e)

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        files.write_json(path, data)
