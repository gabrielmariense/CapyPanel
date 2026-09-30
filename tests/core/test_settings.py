import json
import subprocess
from pathlib import Path

import pytest

from capypanel.core import settings, winsec

ENV = {"PROGRAMDATA": r"C:\ProgramData"}


def test_everything_is_in_one_folder_per_computer(tmp_path: Path) -> None:
    paths = settings.resolve_paths(tmp_path, ENV, account="ana@CORP")
    root = Path(r"C:\ProgramData\CapyPanel")
    assert not paths.portable and paths.root == root
    assert paths.settings_file == root / "users" / "ana@CORP" / "settings.json"
    assert paths.personal_list == root / "users" / "ana@CORP" / "hosts.json"
    assert paths.log_file == root / "logs" / "ana@CORP.log"


def test_marker_file_switches_to_portable_mode(tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path, ENV, account="ana@CORP")
    assert paths.portable and paths.root == tmp_path / "userdata"
    assert paths.user_dir.is_relative_to(tmp_path) and paths.log_file.is_relative_to(tmp_path)


def test_account_names_are_safe_folder_names(tmp_path: Path) -> None:
    paths = settings.resolve_paths(tmp_path, ENV, account="odd:name?@PC")
    assert paths.account == "odd_name_@PC"


def test_real_account_is_user_at_domain(tmp_path: Path) -> None:
    user, _at, domain = winsec.account_name().partition("@")
    assert user and domain


def test_first_run_creates_empty_private_user_folders(tmp_path: Path) -> None:
    paths = settings.resolve_paths(tmp_path, ENV | {"PROGRAMDATA": str(tmp_path)})
    settings.ensure_dirs(paths)
    assert paths.user_tools_dir.is_dir() and not any(paths.user_tools_dir.iterdir())
    assert paths.user_profiles_dir.is_dir() and not any(paths.user_profiles_dir.iterdir())
    assert paths.log_dir.is_dir()
    # icacls /save writes the permissions as SDDL: the same text in any Windows language.
    saved = tmp_path / "acl.txt"
    subprocess.run(["icacls", str(paths.user_dir), "/save", str(saved)], check=True)
    sddl = saved.read_text(encoding="utf-16-le")
    me = winsec.current_user_sid()
    # "D:P": inheritance blocked, so the Users group's read access doesn't reach the folder.
    [dacl] = [line for line in sddl.splitlines() if line.startswith("D:")]
    assert dacl.startswith("D:P")
    assert dacl.endswith(f"(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{me})")
    assert dacl.count("(") == 3


def test_a_user_folder_made_by_someone_else_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = settings.resolve_paths(tmp_path, {"PROGRAMDATA": str(tmp_path)}, account="bob@CORP")
    monkeypatch.setattr(winsec, "owner_sid", lambda _path: "S-1-5-21-1-2-3-1234")
    with pytest.raises(settings.UserFolderError, match="another user"):
        settings.ensure_dirs(paths)


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
