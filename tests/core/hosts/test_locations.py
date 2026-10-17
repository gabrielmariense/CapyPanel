from pathlib import Path
from typing import Any

import pytest

from capypanel.core import winsec
from capypanel.core.hosts import locations
from capypanel.core.hosts.locations import Access, ListKind

ENV = {"APPDATA": r"C:\Users\u\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


def test_a_shared_list_made_by_another_user_is_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hosts.json"
    path.write_text("{}", encoding="utf-8")
    assert locations.list_access(path, shared=True) is Access.READ_WRITE
    monkeypatch.setattr(winsec, "made_by_trusted", lambda _path: False)
    assert locations.list_access(path, shared=True) is Access.UNTRUSTED
    assert locations.list_access(path) is Access.READ_WRITE  # a list the user picked


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


def test_list_access_follows_windows_permissions(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    assert locations.list_access(path) is Access.MISSING
    path.write_text("{}")
    assert locations.list_access(path) is Access.READ_WRITE
    path.chmod(0o444)
    try:
        assert locations.list_access(path) is Access.READ_ONLY
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


def test_a_list_taken_out_is_forgotten_and_does_not_reopen() -> None:
    a, b = Path("C:/share/a.json"), Path("C:/share/b.json")
    prefs: dict[str, Any] = {}
    locations.set_added_lists(prefs, [a, b])
    locations.remember_list(prefs, b)
    locations.remember_list(prefs, a)  # a was open last: it would reopen at start
    locations.set_added_lists(prefs, [b])  # taken out in File > Host lists
    assert locations.recent_lists(prefs) == [b]
    assert locations.added_lists(prefs) == [b]


def test_lists_in_the_lists_folders_show_up_by_themselves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared, mine = tmp_path / "lists", tmp_path / "me" / "lists"
    for folder, names in ((shared, ("Wards", "branch")), (mine, ("my-lab",))):
        folder.mkdir(parents=True)
        for name in names:
            (folder / f"{name}.json").write_text("{}", encoding="utf-8")
    planted = shared / "planted.json"
    planted.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(winsec, "made_by_trusted", lambda path: path != planted)
    found = locations.found_lists(shared, mine)
    assert [p.name for p in found] == ["branch.json", "Wards.json", "my-lab.json"]  # no planted
    default, personal = tmp_path / "hosts.json", tmp_path / "me" / "hosts.json"
    added = tmp_path / "share" / "branch.json"
    prefs: dict[str, Any] = {locations.LISTS_KEY: [str(added), str(found[0])]}
    lists = locations.available_lists(prefs, default=default, personal=personal, found=found)
    assert lists == [default, personal, *found, added]  # each once
    names = locations.list_names(lists, default=default, personal=personal)
    assert names == [
        "Default", "Personal", "branch (lists)", "Wards", "my-lab", "branch (share)"
    ]  # fmt: skip
