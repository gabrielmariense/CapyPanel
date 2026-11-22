import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from capypanel.core import files, settings, winsec
from capypanel.core.files import can_create_files
from capypanel.core.tools import definitions
from capypanel.core.tools.definitions import ToolDefinition, ToolDefinitionError
from capypanel.core.tools.profile_store import UNTRUSTED, ProfileStore

log = logging.getLogger(__name__)
SHIPPED_DIR = Path(__file__).resolve().parent / "presets"
PATHS_FILE = "_paths.json"  # tool id -> .exe; "_" can't start a tool id
READS_FILE = "_reads.json"
READS = ("auto", "direct", "powershell")


class Layer(StrEnum):
    COMPANY = "company"
    SHIPPED = "shipped"


@dataclass(frozen=True)
class Entry:
    item: ToolDefinition
    layer: Layer
    path: Path


def reads_of(folder: Path) -> str:
    """Only an administrator's file counts: another user's can't change how everyone connects."""
    path = folder / READS_FILE
    if not path.is_file() or not winsec.made_by_trusted(path):
        return "auto"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "auto"
    way = data.get("reads") if isinstance(data, dict) else None
    return way if way in READS else "auto"


@dataclass(frozen=True)
class Problem:
    path: Path
    reason: str


class ToolCatalog:
    def __init__(self, company_dir: Path, shipped_dir: Path) -> None:
        self.folder = company_dir
        self.dirs = {Layer.COMPANY: company_dir, Layer.SHIPPED: shipped_dir}
        self.problems: list[Problem] = []
        self._entries: dict[str, Entry] = {}
        self.reload()

    def reload(self) -> None:
        self.problems = []
        entries: dict[str, Entry] = {}
        for layer in (Layer.SHIPPED, Layer.COMPANY):
            folder = self.dirs[layer]
            for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                if path.name.startswith("_"):
                    continue
                if layer is Layer.COMPANY and not self._trusted(path):
                    continue
                try:
                    item = definitions.load(path)
                except ToolDefinitionError as e:
                    self.problems.append(Problem(path, str(e)))
                    log.warning("%s skipped: %s", path, e)
                    continue
                entries[item.id] = Entry(item, layer, path)
        for tool_id, executable in self.paths().items():
            entry = entries.get(tool_id)
            if entry is not None:
                entries[tool_id] = replace(entry, item=replace(entry.item, executable=executable))
        self._entries = entries

    def all(self) -> list[Entry]:
        return sorted(self._entries.values(), key=lambda e: e.item.id)

    def find(self, tool_id: str) -> Entry | None:
        return self._entries.get(tool_id)

    def paths(self) -> dict[str, str]:
        path = self.folder / PATHS_FILE
        if not path.is_file() or not self._trusted(path):
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            self.problems.append(Problem(path, str(e)))
            return {}
        chosen = data.get("paths") if isinstance(data, dict) else None
        if not isinstance(chosen, dict):
            return {}
        return {k: v for k, v in chosen.items() if isinstance(k, str) and isinstance(v, str) and v}

    def can_edit(self) -> bool:
        return can_create_files(self.folder)

    def set_paths(self, changes: Mapping[str, str]) -> None:
        chosen = self.paths()
        for tool_id, executable in changes.items():
            if executable:
                chosen[tool_id] = executable
            else:
                chosen.pop(tool_id, None)
        if not self.folder.is_dir():
            files.make_shared_folder(self.folder)
        files.write_json(self.folder / PATHS_FILE, {"schema": 1, "paths": chosen})
        log.info("Tool paths for this PC: %s", chosen)
        self.reload()

    def reads(self) -> str:
        return reads_of(self.folder)

    def set_reads(self, way: str) -> None:
        if way not in READS:
            raise ValueError(way)
        path = self.folder / READS_FILE
        if way == "auto":
            path.unlink(missing_ok=True)
        else:
            if not self.folder.is_dir():
                files.make_shared_folder(self.folder)
            files.write_json(path, {"schema": 1, "reads": way})
        log.info("Reads other PCs with: %s", way)

    def _trusted(self, path: Path) -> bool:
        # A tool names a program to run: another user's file must not choose it.
        if winsec.made_by_trusted(path):
            return True
        if not any(p.path == path for p in self.problems):
            self.problems.append(Problem(path, UNTRUSTED))
            log.warning("%s skipped: %s", path, UNTRUSTED)
        return False


@dataclass(frozen=True)
class Catalogs:
    tools: ToolCatalog
    profiles: ProfileStore

    @classmethod
    def for_paths(cls, paths: settings.Paths) -> "Catalogs":
        return cls(
            ToolCatalog(paths.company_tools_dir, SHIPPED_DIR / "tools"),
            ProfileStore(paths.profiles_dir),
        )
