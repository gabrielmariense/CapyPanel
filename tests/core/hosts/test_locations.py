from pathlib import Path
from typing import Any

from capypanel.core.hosts import locations
from capypanel.core.hosts.locations import Access, ListKind

ENV = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


def test_default_list_is_in_the_app_data_folder(tmp_path: Path) -> None:
    assert locations.default_list_path(tmp_path) == tmp_path / "data" / "hosts.json"


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


def test_list_access(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    assert locations.list_access(path, ListKind.PERSONAL) is Access.MISSING
    path.write_text("{}")
    assert locations.list_access(path, ListKind.SHARED) is Access.READ_WRITE
    assert locations.list_access(path, ListKind.DEFAULT) is Access.READ_ONLY
    path.chmod(0o444)
    try:
        assert locations.list_access(path, ListKind.SHARED) is Access.READ_ONLY
    finally:
        path.chmod(0o666)


def test_startup_order_tries_the_choice_then_default_then_personal() -> None:
    default, personal = Path(r"C:\app\data\hosts.json"), Path(r"C:\me\hosts.json")
    shared = Path(r"\\server\it\hosts.json")

    def order(prefs: dict[str, Any]) -> list[Path]:
        return locations.startup_order(prefs, default=default, personal=personal)

    assert order({}) == [default, personal]  # first start: nothing used yet
    last = {"recent_lists": [str(shared)]}
    assert order(last) == [shared, default, personal]
    assert order({**last, "start_list": "personal"}) == [personal, default]
    assert order({**last, "start_list": "default"}) == [default, personal]
    assert order({"start_list": str(shared)}) == [shared, default, personal]
    assert order({"start_list": 42}) == [default, personal]  # a broken value means "last used"
