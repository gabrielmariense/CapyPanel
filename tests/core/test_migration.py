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
    assert [g.name for g in listfile.load(paths.lists("hosts").personal).hosts.groups] == [
        "Old hosts"
    ]
    prefs = settings.load_settings(paths.settings_file)
    assert prefs["theme"] == "paper"
    assert prefs["recent_lists"] == [str(paths.lists("hosts").personal), str(shared)]
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


def test_lists_from_before_0_19_are_copied_into_the_lists_folders(tmp_path: Path) -> None:
    paths, env, documents = _setup(tmp_path)
    old_default, old_personal = paths.root / "hosts.json", paths.user_dir / "hosts.json"
    listfile.save(old_default, HostList().add_group("Shared hosts")[0], expected=None)
    listfile.save(old_personal, HostList().add_group("My hosts")[0], expected=None)
    settings.save_settings(
        paths.settings_file,
        {"schema": 1, "recent_lists": [str(old_personal)], "start_list": str(old_default)},
    )
    copied = migration.migrate(paths, env, documents)
    assert len(copied) == 2 and old_default.exists() and old_personal.exists()  # copies
    assert [g.name for g in listfile.load(paths.lists("hosts").default).hosts.groups] == [
        "Shared hosts"
    ]
    assert [g.name for g in listfile.load(paths.lists("hosts").personal).hosts.groups] == [
        "My hosts"
    ]
    prefs = settings.load_settings(paths.settings_file)
    assert prefs["recent_lists"] == [str(paths.lists("hosts").personal)]
    assert prefs["start_list"] == str(paths.lists("hosts").default)
    assert migration.migrate(paths, env, documents) == []  # once


def test_0_19_lists_are_copied_into_hosts_folders_and_its_settings_follow(tmp_path: Path) -> None:
    paths, env, documents = _setup(tmp_path)
    shared, mine = paths.lists_dir / "office.json", paths.user_lists_dir / "personal.json"
    for path in (shared, mine, paths.lists_dir / "default.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        listfile.save(path, HostList().add_group(path.stem)[0], expected=None)
    elsewhere = tmp_path / "share" / "team.json"
    top = {
        "schema": 1, "theme": "paper", "recent_lists": [str(shared), str(elsewhere)],
        "host_lists": [str(elsewhere)], "start_list": str(shared), "hidden_lists": [str(shared)],
    }  # fmt: skip
    settings.save_settings(paths.settings_file, top)
    copied = migration.migrate(paths, env, documents)
    hosts = paths.lists("hosts")
    assert len(copied) == 3 and shared.exists() and mine.exists()  # copies, never moves
    assert listfile.load(hosts.shared_dir / "office.json").hosts.groups[0].name == "office"
    assert hosts.default.exists() and hosts.personal.exists()
    prefs = settings.load_settings(paths.settings_file)
    section = prefs["tools"]["hosts"]
    new_office = str(hosts.shared_dir / "office.json")
    assert section["recent_lists"] == [new_office, str(elsewhere)]  # a list elsewhere stays
    assert section["start_list"] == new_office and section["hidden_lists"] == [new_office]
    assert prefs["recent_lists"] == top["recent_lists"]  # 0.19 still reads its own
    assert migration.migrate(paths, env, documents) == []  # once: the folders exist now
