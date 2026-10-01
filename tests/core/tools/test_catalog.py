import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from capypanel.core.tools import catalog
from capypanel.core.tools.catalog import SHIPPED_DIR, Layer


def _write(folder: Path, tool_id: str, name: str, **extra: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": 1, "id": tool_id, "name": name, "kind": "vnc",
        "arguments": [["{address}"]], **extra,
    }  # fmt: skip
    (folder / f"{tool_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _tools(tmp_path: Path) -> catalog.Catalog[Any]:
    return catalog.tools(tmp_path / "user", tmp_path / "company", tmp_path / "shipped")


def test_a_higher_layer_wins_for_the_same_tool(tmp_path: Path) -> None:
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


def test_editing_saves_a_user_copy_and_reset_brings_back_the_original(tmp_path: Path) -> None:
    _write(tmp_path / "shipped", "viewer", "Viewer")
    tools = _tools(tmp_path)
    assert not (tmp_path / "user").exists()  # the user folder appears only when first used
    original = tools.find("viewer")
    assert original is not None
    edited = tools.save_user_copy(replace(original.item, executable=r"D:\Apps\viewer.exe"))
    assert edited.layer is Layer.USER and edited.item.executable == r"D:\Apps\viewer.exe"
    shipped_file = json.loads((tmp_path / "shipped" / "viewer.json").read_text(encoding="utf-8"))
    assert "executable" not in shipped_file  # the original is never touched
    tools.reset("viewer")
    back = tools.find("viewer")
    assert back is not None and back.layer is Layer.SHIPPED and not back.item.executable


def test_profiles_load_from_their_own_layers(tmp_path: Path) -> None:
    company = tmp_path / "company"
    company.mkdir()
    data = {"schema": 1, "id": "pis", "tool": "realvnc", "login": "account", "name": "Our Pis"}
    (company / "pis.json").write_text(json.dumps(data), encoding="utf-8")
    profiles = catalog.profiles_catalog(tmp_path / "user", company, SHIPPED_DIR / "profiles")
    pis = profiles.find("pis")
    assert pis is not None and pis.layer is Layer.COMPANY and pis.item.name == "Our Pis"
    assert profiles.find("ultravnc-password") is not None  # shipped ones are still there
