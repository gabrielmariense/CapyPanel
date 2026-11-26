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
from capypanel.core.tools import profiles, viewer_settings
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError

log = logging.getLogger(__name__)
STARTERS_DIR = Path(__file__).resolve().parent / "presets" / "profiles"
# Also the starters added once, so a deleted one stays deleted; "_" can't start a profile id.
SETTINGS_FILE = "_profiles.json"


def make_id(name: str, taken: Collection[str]) -> str:
    plain = unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:48] or "profile"
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    return candidate


UNTRUSTED = "made by another user, so it isn't used"


class ProfileStore:
    def __init__(self, folder: Path, starters_dir: Path = STARTERS_DIR) -> None:
        self.folder = folder
        self._starters = starters_dir
        self.problems: list[tuple[Path, str]] = []
        self._profiles: dict[str, ConnectionProfile] = {}
        self.reload()

    def reload(self) -> None:
        self.problems = []
        source = self.folder if self.folder.is_dir() else self._starters
        self._profiles = {}
        self._load_from(source)
        if source is self.folder:
            self._add_new_starters()

    def _load_from(self, source: Path) -> None:
        for path in sorted(source.glob("*.json")):
            if path.name.startswith("_"):
                continue
            if source is self.folder and not winsec.made_by_trusted(path):
                self.problems.append((path, UNTRUSTED))
                log.warning("Connection profile %s skipped: %s", path, UNTRUSTED)
                continue
            try:
                profile = profiles.load(path)
            except ProfileError as e:
                self.problems.append((path, str(e)))
                log.warning("Connection profile %s skipped: %s", path, e)
                continue
            self._profiles[profile.id] = profile

    def all(self) -> list[ConnectionProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.name.casefold())

    def find(self, profile_id: str) -> ConnectionProfile | None:
        return self._profiles.get(profile_id)

    def default_id(self) -> str:
        wanted = self._settings().get("default_profile")
        if isinstance(wanted, str) and wanted in self._profiles:
            return wanted
        starter = "ultravnc"
        if starter in self._profiles:
            return starter
        first = self.all()
        return first[0].id if first else ""

    def settings_path(self, profile: ConnectionProfile) -> Path | None:
        if not profile.settings_file:
            return None
        path = self.folder / profile.settings_file
        if not path.is_file() or not winsec.made_by_trusted(path):
            log.warning("Settings file %s missing or made by another user: not used", path)
            return None
        return path

    def can_edit(self) -> bool:
        return can_create_files(self.folder)

    def save(self, profile: ConnectionProfile, settings: bytes | None = None) -> None:
        old = self.find(profile.id)
        self._seed()
        if settings is not None and profile.settings_file:
            kept = viewer_settings.without_password(settings) or settings
            files.write_atomic(self.folder / profile.settings_file, kept)
        self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        if old is not None and old.settings_file not in ("", profile.settings_file):
            (self.folder / old.settings_file).unlink(missing_ok=True)
        log.info("Connection profile saved: %s (%s)", profile.id, profile.name)
        self.reload()

    def empty_saved_passwords(self) -> None:
        if not self.folder.is_dir() or not self.can_edit():
            return
        for profile in self._profiles.values():
            path = self.settings_path(profile)
            if path is None:
                continue
            try:
                emptied = viewer_settings.without_password(path.read_bytes())
                if emptied is not None:
                    files.write_atomic(path, emptied)
                    log.info("Saved password emptied in %s", path)
            except OSError as e:
                log.warning("Couldn't empty the saved password in %s: %s", path, e)

    def delete(self, profile_id: str) -> None:
        profile = self.find(profile_id)
        if profile is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._seed()
        (self.folder / f"{profile_id}.json").unlink(missing_ok=True)
        if profile.settings_file:
            (self.folder / profile.settings_file).unlink(missing_ok=True)
        log.info("Connection profile deleted: %s (%s)", profile_id, profile.name)
        self.reload()

    def set_default(self, profile_id: str) -> None:
        if self.find(profile_id) is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._seed()
        self._update_settings(default_profile=profile_id)
        log.info("Default connection profile: %s", profile_id)

    def place_starters(self) -> None:
        if self.folder.is_dir() or not self.can_edit():
            return
        self._seed()
        self.reload()
        log.info("Connection profiles placed in %s", self.folder)

    def missing_starters(self) -> list[ConnectionProfile]:
        if not self.folder.is_dir():
            return []
        missing: list[ConnectionProfile] = []
        for pid in self._starter_ids():
            if pid in self._profiles or (self.folder / f"{pid}.json").exists():
                continue
            try:
                missing.append(profiles.load(self._starters / f"{pid}.json"))
            except ProfileError as e:
                log.warning("Starter profile %s skipped: %s", pid, e)
        return sorted(missing, key=lambda p: p.name.casefold())

    def restore_starters(self) -> list[ConnectionProfile]:
        restored = self.missing_starters()
        for profile in restored:
            self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
            log.info("Built-in connection profile restored: %s", profile.id)
        self.reload()
        return restored

    def _seed(self) -> None:
        if self.folder.is_dir():
            return
        files.make_shared_folder(self.folder)
        for profile in self._profiles.values():
            self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        self._update_settings(starters_added=self._starter_ids())

    def _starter_ids(self) -> list[str]:
        return sorted(p.stem for p in self._starters.glob("*.json"))

    def _add_new_starters(self) -> None:
        listed = self._settings().get("starters_added")
        added = {str(pid) for pid in listed} if isinstance(listed, list) else set()
        new = [pid for pid in self._starter_ids() if pid not in added]
        if not new:
            return
        for pid in new:
            if pid in self._profiles:
                continue
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
                return
        try:
            self._update_settings(starters_added=sorted(added | set(new)))
        except OSError as e:
            log.warning("Couldn't write %s: %s", self.folder / SETTINGS_FILE, e)

    def _settings(self) -> dict[str, Any]:
        path = self.folder / SETTINGS_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and winsec.made_by_trusted(path) else {}

    def _update_settings(self, **changes: object) -> None:
        self._write(self.folder / SETTINGS_FILE, {**self._settings(), "schema": 1, **changes})

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        files.write_json(path, data)
