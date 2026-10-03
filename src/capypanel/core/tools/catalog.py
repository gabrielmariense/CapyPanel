"""Tool definitions this user can use, from three layers: their own (user), the company's
(placed in ProgramData by an administrator) and the shipped presets. A higher layer wins for
the same id. Connection profiles live elsewhere: see profile_store."""

import json
import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from capypanel.core import settings, winsec
from capypanel.core.tools import definitions
from capypanel.core.tools.definitions import ToolDefinition, ToolDefinitionError
from capypanel.core.tools.profile_store import ProfileStore

log = logging.getLogger(__name__)
SHIPPED_DIR = Path(__file__).resolve().parent / "presets"


class Layer(StrEnum):
    USER = "user"
    COMPANY = "company"
    SHIPPED = "shipped"


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


@dataclass(frozen=True)
class Entry[T]:
    item: T
    layer: Layer
    path: Path


@dataclass(frozen=True)
class Problem:
    path: Path
    reason: str


class Catalog[T: _Identified]:
    def __init__(
        self,
        user_dir: Path,
        company_dir: Path,
        shipped_dir: Path,
        *,
        load: Callable[[Path], T],
        to_data: Callable[[T], dict[str, Any]],
        errors: tuple[type[Exception], ...],
    ) -> None:
        self.dirs = {Layer.USER: user_dir, Layer.COMPANY: company_dir, Layer.SHIPPED: shipped_dir}
        self._load, self._to_data, self._errors = load, to_data, errors
        self.problems: list[Problem] = []
        self._entries: dict[str, Entry[T]] = {}
        self.reload()

    def reload(self) -> None:
        self.problems = []
        entries: dict[str, Entry[T]] = {}
        # Lowest layer first, so a higher layer's file replaces it.
        for layer in (Layer.SHIPPED, Layer.COMPANY, Layer.USER):
            folder = self.dirs[layer]
            for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                if layer is Layer.COMPANY and not winsec.made_by_trusted(path):
                    # A tool names a program to run: another user's file must not choose it.
                    reason = "made by another user, so it isn't used"
                    self.problems.append(Problem(path, reason))
                    log.warning("%s skipped: %s", path, reason)
                    continue
                try:
                    item = self._load(path)
                except self._errors as e:
                    self.problems.append(Problem(path, str(e)))
                    log.warning("%s skipped: %s", path, e)
                    continue
                entries[item.id] = Entry(item, layer, path)
        self._entries = entries

    def all(self) -> list[Entry[T]]:
        return sorted(self._entries.values(), key=lambda e: e.item.id)

    def find(self, item_id: str) -> Entry[T] | None:
        return self._entries.get(item_id)

    def save_user_copy(self, item: T) -> Entry[T]:
        """Saves the user's own version; the company or shipped original is never changed."""
        folder = self.dirs[Layer.USER]
        folder.mkdir(parents=True, exist_ok=True)  # created on first use, not at start
        path = folder / f"{item.id}.json"
        tmp = folder / f".{item.id}.{uuid.uuid4().hex[:8]}.tmp"
        tmp.write_text(json.dumps(self._to_data(item), indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, path)
        self.reload()
        return self._entries[item.id]

    def reset(self, item_id: str) -> None:
        """Deletes the user's version, so the company or shipped one shows through again."""
        entry = self.find(item_id)
        if entry is not None and entry.layer is Layer.USER:
            entry.path.unlink(missing_ok=True)
            self.reload()


def tools(user_dir: Path, company_dir: Path, shipped_dir: Path) -> Catalog[ToolDefinition]:
    return Catalog(
        user_dir, company_dir, shipped_dir,
        load=definitions.load, to_data=definitions.to_data, errors=(ToolDefinitionError,),
    )  # fmt: skip


@dataclass(frozen=True)
class Catalogs:
    tools: Catalog[ToolDefinition]
    profiles: ProfileStore

    @classmethod
    def for_paths(cls, paths: settings.Paths) -> "Catalogs":
        return cls(
            tools(paths.user_tools_dir, paths.company_tools_dir, SHIPPED_DIR / "tools"),
            ProfileStore(paths.profiles_dir),
        )
