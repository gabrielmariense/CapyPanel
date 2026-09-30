from pathlib import Path
from typing import Any

from capypanel.core import settings
from capypanel.core.hosts import locations
from capypanel.core.hosts.locations import ListKind

ENV = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


def test_personal_list_is_in_documents_or_next_to_the_app_when_portable(tmp_path: Path) -> None:
    normal = settings.resolve_paths(tmp_path, ENV)
    docs = Path(r"D:\Docs")
    assert locations.personal_list_path(normal, docs) == docs / "CapyPanel" / "hosts.json"
    (tmp_path / settings.PORTABLE_MARKER).touch()
    portable = settings.resolve_paths(tmp_path, ENV)
    assert locations.personal_list_path(portable, docs).is_relative_to(tmp_path)


def test_default_list_is_in_the_app_data_folder(tmp_path: Path) -> None:
    assert locations.default_list_path(tmp_path) == tmp_path / "data" / "hosts.json"


def test_documents_dir_is_a_real_folder() -> None:
    assert locations.documents_dir().is_dir()


def test_list_kind(tmp_path: Path) -> None:
    default, personal = tmp_path / "data" / "hosts.json", tmp_path / "me" / "hosts.json"
    kinds = {
        "default": locations.list_kind(default, default=default, personal=personal),
        "personal": locations.list_kind(
            Path(str(personal).upper()), default=default, personal=personal
        ),
        "shared": locations.list_kind(
            Path(r"\\server\it\hosts.json"), default=default, personal=personal
        ),
    }
    assert kinds == {
        "default": ListKind.DEFAULT,
        "personal": ListKind.PERSONAL,
        "shared": ListKind.SHARED,
    }


def test_recent_lists_most_recent_first_without_duplicates() -> None:
    prefs: dict[str, Any] = {}
    for name in ["a", "b", "a"]:
        locations.remember_list(prefs, Path(rf"C:\lists\{name}.json"))
    assert locations.recent_lists(prefs) == [Path(r"C:\lists\a.json"), Path(r"C:\lists\b.json")]


def test_recent_lists_are_capped_and_can_forget() -> None:
    prefs: dict[str, Any] = {}
    for n in range(locations.RECENT_LIMIT + 5):
        locations.remember_list(prefs, Path(rf"C:\lists\{n}.json"))
    assert len(locations.recent_lists(prefs)) == locations.RECENT_LIMIT
    locations.forget_list(prefs, Path(r"C:\lists\14.json"))
    assert Path(r"C:\lists\14.json") not in locations.recent_lists(prefs)


def test_bad_recent_value_is_ignored() -> None:
    assert locations.recent_lists({"recent_lists": "oops"}) == []
