from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from capypanel.core.tools import definitions, detect
from capypanel.core.tools.definitions import Detect, ToolDefinition


def _tool(**changes: object) -> ToolDefinition:
    tool = definitions.from_data(
        {"schema": 1, "id": "viewer", "name": "Viewer", "kind": "vnc", "arguments": [["{address}"]]}
    )
    return replace(tool, **changes)  # type: ignore[arg-type]


def _exe(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "viewer.exe"
    exe.write_bytes(b"")
    return exe


def _programs(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[str, str, str]]) -> None:
    def fake() -> Iterator[tuple[str, str, str]]:
        yield from rows

    monkeypatch.setattr(detect, "_installed_programs", fake)


def test_found_where_windows_says_it_was_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # e.g. C:\Programas\UltraVNC: not a usual folder, but Windows recorded it.
    exe = _exe(tmp_path / "Programas" / "Viewer")
    _programs(monkeypatch, [("Other app", str(tmp_path), ""), ("Viewer 2.1", str(exe.parent), "")])
    tool = _tool(detect=Detect(installed_as=("Viewer",), exe="viewer.exe"))
    assert detect.find_executable(tool) == exe


def test_without_an_install_folder_the_uninstaller_s_folder_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _exe(tmp_path / "Viewer")
    uninstaller = f'"{exe.parent / "unins000.exe"}" /SILENT'
    _programs(monkeypatch, [("Viewer", "", uninstaller)])
    tool = _tool(detect=Detect(installed_as=("Viewer",), exe="viewer.exe"))
    assert detect.find_executable(tool) == exe


def test_usual_paths_expand_windows_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = _exe(tmp_path / "Viewer")
    _programs(monkeypatch, [])
    monkeypatch.setenv("CAPYPANEL_TEST_DIR", str(tmp_path))
    tool = _tool(detect=Detect(paths=("%CAPYPANEL_TEST_DIR%\\Viewer\\viewer.exe",)))
    assert detect.find_executable(tool) == exe


def test_a_path_the_user_set_is_final(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    installed = _exe(tmp_path / "Installed")
    _programs(monkeypatch, [("Viewer", str(installed.parent), "")])
    detect_rule = Detect(installed_as=("Viewer",), exe="viewer.exe")
    chosen = _exe(tmp_path / "Chosen")
    assert detect.find_executable(_tool(executable=str(chosen), detect=detect_rule)) == chosen
    # A missing chosen path is reported, not silently swapped for another copy.
    gone = str(tmp_path / "Gone" / "viewer.exe")
    assert detect.find_executable(_tool(executable=gone, detect=detect_rule)) is None
