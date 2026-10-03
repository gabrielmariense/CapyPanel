"""Connection profiles live together in C:\\ProgramData\\CapyPanel\\profiles, next to the default
list: the same for everyone on the PC. Windows permissions on the folder decide who can change
them, and a file another standard user made is ignored. The app ships starter profiles (one per
tool) that fill the folder the first time it's written; after that they're ordinary profiles."""

import json
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from collections.abc import Collection
from pathlib import Path
from typing import Any

from capypanel.core import winsec
from capypanel.core.i18n import _
from capypanel.core.tools import profiles
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError

log = logging.getLogger(__name__)
STARTERS_DIR = Path(__file__).resolve().parent / "presets" / "profiles"
DEFAULT_FILE = "_default.json"  # in the profiles folder; "_" can't start a profile id


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
        """The folder's profiles; the starters until the folder exists."""
        self.problems = []
        source = self.folder if self.folder.is_dir() else self._starters
        self._profiles = {}
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

    # ---- changing ----

    def new_id(self, name: str) -> str:
        return make_id(name, self._profiles)

    def save(self, profile: ConnectionProfile) -> None:
        """Writes a profile, new or changed. Raises OSError."""
        self._seed()
        self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))
        log.info("Connection profile saved: %s (%s)", profile.id, profile.name)
        self.reload()

    def delete(self, profile_id: str) -> None:
        profile = self.find(profile_id)
        if profile is None:
            raise ProfileError(_("That profile doesn't exist."))
        self._seed()
        (self.folder / f"{profile_id}.json").unlink(missing_ok=True)
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
        self.folder.mkdir(parents=True)
        try:  # read-only for everyone else; ProgramData would let any user add files
            winsec.make_shared(self.folder, winsec.current_user_sid())
        except OSError as e:
            log.warning("Couldn't set permissions on %s: %s", self.folder, e)
        for profile in self._profiles.values():
            self._write(self.folder / f"{profile.id}.json", profiles.to_data(profile))

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
