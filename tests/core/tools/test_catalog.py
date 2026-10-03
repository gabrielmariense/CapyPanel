import json
from pathlib import Path
from typing import Any

import pytest

from capypanel.core import winsec
from capypanel.core.tools.catalog import PATHS_FILE, Layer, ToolCatalog


def _write(folder: Path, tool_id: str, name: str, **extra: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1, "id": tool_id, "name": name, "kind": "vnc",
        "arguments": [["{address}"]], **extra,
    }  # fmt: skip
    (folder / f"{tool_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _tools(tmp_path: Path) -> ToolCatalog:
    return ToolCatalog(tmp_path / "company", tmp_path / "shipped")


def test_the_company_s_definition_wins_for_the_same_tool(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "viewer", "Shipped viewer")
    _write(tmp_path / "shipped", "other", "Other")
    _write(tmp_path / "company", "viewer", "Company viewer")
    tools = _tools(tmp_path)
    entry = tools.find("viewer")
    assert entry is not None and entry.item.name == "Company viewer"
    assert entry.layer is Layer.COMPANY
    assert [e.item.id for e in tools.all()] == ["other", "viewer"]  # by id


def test_a_broken_file_is_reported_and_the_rest_still_load(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "good", "Good")
    (tmp_path / "shipped" / "bad.json").write_text("{ nope", encoding="utf-8")
    tools = _tools(tmp_path)
    assert [e.item.id for e in tools.all()] == ["good"]
    assert [p.path.name for p in tools.problems] == ["bad.json"]


def test_a_path_is_set_once_for_everyone_and_definitions_keep_their_updates(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "shipped", "viewer", "Viewer")
    tools = _tools(tmp_path)
    tools.set_paths({"viewer": r"D:\Apps\viewer.exe"})
    assert (tmp_path / "company" / PATHS_FILE).is_file()  # the PC's folder, not the user's
    # Later the shipped definition changes: the chosen path stays, and the change arrives.
    _write(tmp_path / "shipped", "viewer", "Viewer 2")
    again = _tools(tmp_path)
    entry = again.find("viewer")
    assert entry is not None and entry.item.name == "Viewer 2"
    assert entry.item.executable == r"D:\Apps\viewer.exe"
    again.set_paths({"viewer": ""})  # find it by itself again
    back = _tools(tmp_path).find("viewer")
    assert back is not None and not back.item.executable


def test_a_company_tool_or_path_another_user_made_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "shipped", "viewer", "Shipped viewer")
    _write(tmp_path / "company", "viewer", "Planted viewer", executable=r"C:\evil.exe")
    planted = tmp_path / "company" / "viewer.json"
    paths = tmp_path / "company" / PATHS_FILE
    paths.write_text(json.dumps({"schema": 1, "paths": {"viewer": r"C:\evil.exe"}}), "utf-8")
    monkeypatch.setattr(winsec, "made_by_trusted", lambda path: path not in (planted, paths))
    tools = _tools(tmp_path)
    entry = tools.find("viewer")
    assert entry is not None and entry.layer is Layer.SHIPPED  # never runs the planted program
    assert not entry.item.executable
    assert {p.path for p in tools.problems} == {planted, paths}
