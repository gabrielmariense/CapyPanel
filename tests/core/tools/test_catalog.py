import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from capypanel.core.tools.catalog import Catalog, Layer


def _write(folder: Path, tool_id: str, name: str, **extra: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1, "id": tool_id, "name": name, "kind": "vnc",
        "arguments": [["{address}"]], **extra,
    }  # fmt: skip
    (folder / f"{tool_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _catalog(tmp_path: Path) -> Catalog:
    return Catalog(tmp_path / "user", tmp_path / "company", tmp_path / "shipped")


def test_a_higher_layer_wins_for_the_same_tool(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "viewer", "Shipped viewer")
    _write(tmp_path / "shipped", "other", "Other")
    _write(tmp_path / "company", "viewer", "Company viewer")
    catalog = _catalog(tmp_path)
    entry = catalog.find("viewer")
    assert entry is not None and entry.tool.name == "Company viewer"
    assert entry.layer is Layer.COMPANY
    assert [e.tool.name for e in catalog.all()] == ["Company viewer", "Other"]  # by name


def test_a_broken_file_is_reported_and_the_rest_still_load(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "good", "Good")
    (tmp_path / "shipped" / "bad.json").write_text("{ nope", encoding="utf-8")
    catalog = _catalog(tmp_path)
    assert [e.tool.id for e in catalog.all()] == ["good"]
    assert [p.path.name for p in catalog.problems] == ["bad.json"]


def test_editing_saves_a_user_copy_and_reset_brings_back_the_original(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "viewer", "Viewer")
    catalog = _catalog(tmp_path)
    assert not (tmp_path / "user").exists()  # the user folder appears only when first used
    original = catalog.find("viewer")
    assert original is not None
    edited = catalog.save_user_copy(replace(original.tool, executable=r"D:\Apps\viewer.exe"))
    assert edited.layer is Layer.USER and edited.tool.executable == r"D:\Apps\viewer.exe"
    shipped_file = json.loads((tmp_path / "shipped" / "viewer.json").read_text(encoding="utf-8"))
    assert "executable" not in shipped_file  # the original is never touched
    catalog.reset("viewer")
    back = catalog.find("viewer")
    assert back is not None and back.layer is Layer.SHIPPED and not back.tool.executable
