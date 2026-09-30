from pathlib import Path

from capypanel.core import migration, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList


def _setup(tmp_path: Path) -> tuple[settings.Paths, dict[str, str], Path]:
    env = {"PROGRAMDATA": str(tmp_path / "ProgramData"), "APPDATA": str(tmp_path / "Roaming")}
    paths = settings.resolve_paths(tmp_path / "app", env, account="ana@CORP")
    paths.user_dir.mkdir(parents=True)
    return paths, env, tmp_path / "Documents"


def test_old_settings_and_personal_list_are_copied_once(tmp_path: Path) -> None:
    paths, env, documents = _setup(tmp_path)
    old_settings, old_list = migration.old_files(paths, env, documents)
    old_list.parent.mkdir(parents=True)
    listfile.save(old_list, HostList().add_group("Old hosts")[0], expected=None)
    shared = tmp_path / "share" / "team.json"
    settings.save_settings(
        old_settings,
        {"schema": 1, "theme": "paper", "recent_lists": [str(old_list), str(shared)],
         "start_list": str(old_list)},
    )  # fmt: skip

    copied = migration.migrate(paths, env, documents)

    assert len(copied) == 2
    assert old_settings.exists() and old_list.exists()  # copied, never moved
    assert [g.name for g in listfile.load(paths.personal_list).hosts.groups] == ["Old hosts"]
    prefs = settings.load_settings(paths.settings_file)
    assert prefs["theme"] == "paper"
    assert prefs["recent_lists"] == [str(paths.personal_list), str(shared)]
    assert prefs["start_list"] == "personal"
    assert migration.migrate(paths, env, documents) == []  # nothing left to do


def test_new_files_are_never_overwritten(tmp_path: Path) -> None:
    paths, env, documents = _setup(tmp_path)
    old_settings, _old_list = migration.old_files(paths, env, documents)
    settings.save_settings(old_settings, {"schema": 1, "theme": "paper"})
    settings.save_settings(paths.settings_file, {"schema": 1, "theme": "graphite"})
    assert migration.migrate(paths, env, documents) == []
    assert settings.load_settings(paths.settings_file)["theme"] == "graphite"


def test_portable_mode_copies_from_the_old_userdata_layout(tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path, {}, account="ana@CORP")
    paths.user_dir.mkdir(parents=True)
    settings.save_settings(paths.root / "settings.json", {"schema": 1, "theme": "paper"})
    assert len(migration.migrate(paths)) == 1
    assert settings.load_settings(paths.settings_file)["theme"] == "paper"


def test_documents_dir_is_a_real_folder() -> None:
    assert migration.documents_dir().is_dir()
