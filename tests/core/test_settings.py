import json
from pathlib import Path

from capypanel.core import settings

ENV = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


def test_normal_mode_uses_profile_folders(tmp_path: Path) -> None:
    paths = settings.resolve_paths(tmp_path, ENV)
    assert not paths.portable
    assert paths.settings_dir == Path(ENV["APPDATA"]) / settings.APP_ID
    assert paths.log_dir == Path(ENV["LOCALAPPDATA"]) / settings.APP_ID


def test_marker_file_switches_to_portable_mode(tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path, ENV)
    assert paths.portable
    assert paths.settings_dir.is_relative_to(tmp_path)
    assert paths.log_dir.is_relative_to(tmp_path)


def test_first_run_creates_empty_user_folders(tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path, ENV)
    settings.ensure_dirs(paths)
    assert paths.user_tools_dir.is_dir() and not any(paths.user_tools_dir.iterdir())
    assert paths.user_profiles_dir.is_dir() and not any(paths.user_profiles_dir.iterdir())
    assert paths.log_dir.is_dir()


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert settings.load_settings(tmp_path / "settings.json") == {
        "schema": settings.SETTINGS_SCHEMA
    }


def test_round_trip_keeps_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    data = {"schema": 1, "language": "pt_BR", "from_a_newer_version": {"x": 1}}
    settings.save_settings(path, data)
    assert settings.load_settings(path) == data
    assert not path.with_name(path.name + ".tmp").exists()


def test_corrupt_file_is_set_aside_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert settings.load_settings(path) == {"schema": settings.SETTINGS_SCHEMA}
    broken = path.with_name(path.name + ".broken")
    assert broken.read_text(encoding="utf-8") == "{ not json"


def test_non_object_json_is_set_aside(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert settings.load_settings(path) == {"schema": settings.SETTINGS_SCHEMA}
    assert path.with_name(path.name + ".broken").exists()
