"""The tools this user can use, from three layers: their own (user), the company's (placed next
to the app by whoever manages it) and the shipped presets. A higher layer wins for the same id."""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from capypanel.core import settings
from capypanel.core.tools import definitions
from capypanel.core.tools.definitions import ToolDefinition, ToolDefinitionError

log = logging.getLogger(__name__)
SHIPPED_DIR = Path(__file__).resolve().parent / "presets"


class Layer(StrEnum):
    USER = "user"
    COMPANY = "company"
    SHIPPED = "shipped"


@dataclass(frozen=True)
class Entry:
    tool: ToolDefinition
    layer: Layer
    path: Path


@dataclass(frozen=True)
class Problem:
    path: Path
    reason: str


class Catalog:
    def __init__(self, user_dir: Path, company_dir: Path, shipped_dir: Path = SHIPPED_DIR) -> None:
        self.dirs = {Layer.USER: user_dir, Layer.COMPANY: company_dir, Layer.SHIPPED: shipped_dir}
        self.problems: list[Problem] = []
        self._entries: dict[str, Entry] = {}
        self.reload()

    @classmethod
    def for_paths(cls, paths: settings.Paths) -> "Catalog":
        return cls(paths.user_tools_dir, settings.app_dir() / "data" / "tools")

    def reload(self) -> None:
        self.problems = []
        entries: dict[str, Entry] = {}
        # Lowest layer first, so a higher layer's file replaces it.
        for layer in (Layer.SHIPPED, Layer.COMPANY, Layer.USER):
            folder = self.dirs[layer]
            for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                try:
                    tool = definitions.load(path)
                except ToolDefinitionError as e:
                    self.problems.append(Problem(path, str(e)))
                    log.warning("Tool definition %s skipped: %s", path, e)
                    continue
                entries[tool.id] = Entry(tool, layer, path)
        self._entries = entries

    def all(self) -> list[Entry]:
        return sorted(self._entries.values(), key=lambda e: e.tool.name.casefold())

    def find(self, tool_id: str) -> Entry | None:
        return self._entries.get(tool_id)

    def of_kind(self, kind: str) -> list[Entry]:
        return [e for e in self.all() if e.tool.kind == kind]

    def save_user_copy(self, tool: ToolDefinition) -> Entry:
        """Saves the user's own version; the company or shipped original is never changed."""
        folder = self.dirs[Layer.USER]
        folder.mkdir(parents=True, exist_ok=True)  # created on first use, not at start
        path = folder / f"{tool.id}.json"
        tmp = folder / f".{tool.id}.{uuid.uuid4().hex[:8]}.tmp"
        tmp.write_text(json.dumps(definitions.to_data(tool), indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, path)
        self.reload()
        entry = self._entries[tool.id]
        return entry

    def reset(self, tool_id: str) -> None:
        """Deletes the user's version, so the company or shipped one shows through again."""
        entry = self.find(tool_id)
        if entry is not None and entry.layer is Layer.USER:
            entry.path.unlink(missing_ok=True)
            self.reload()
