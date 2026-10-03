import json
from pathlib import Path

import pytest

from capypanel.core.tools.profile_store import BUILT_IN_DEFAULT, Origin, ProfileStore
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError


def _profile(pid: str, name: str, **changes: object) -> ConnectionProfile:
    return ConnectionProfile(pid, "ultravnc", name=name, **changes)  # type: ignore[arg-type]


def test_built_ins_first_then_shared_profiles_by_name(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save(_profile("zeta", "Zeta"))
    store.save(_profile("alpha", "Alpha"))
    assert [(s.profile.id, s.origin) for s in store.all()] == [
        ("realvnc", Origin.BUILT_IN), ("ultravnc", Origin.BUILT_IN),
        ("alpha", Origin.SHARED), ("zeta", Origin.SHARED),
    ]  # fmt: skip
    assert (tmp_path / "profiles" / "alpha.json").is_file()  # next to the default list


def test_built_ins_cannot_be_changed_replaced_or_deleted(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileError):
        store.save(_profile("ultravnc", "Mine"))
    with pytest.raises(ProfileError):
        store.delete("ultravnc")
    # A file dropped in the folder under a built-in id is ignored and reported.
    folder = tmp_path / "profiles"
    folder.mkdir()
    data = {"schema": 1, "id": "ultravnc", "name": "Fake", "tool": "ultravnc"}
    (folder / "ultravnc.json").write_text(json.dumps(data), encoding="utf-8")
    store.reload()
    found = store.find("ultravnc")
    assert found is not None and found.profile.name == "UltraVNC" and store.problems


def test_profiles_from_version_0_8_still_resolve_but_are_not_offered(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    old = store.find("ultravnc-account-securevnc")
    assert old is not None and old.origin is Origin.RETIRED and not old.editable
    assert old.profile.options == ("securevnc",) and old.profile.login == "account"
    assert "ultravnc-account-securevnc" not in {s.profile.id for s in store.all()}


def test_ids_come_from_the_name_and_never_clash(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.new_id("Clínicas (SecureVNC)") == "clinicas-securevnc"
    assert store.new_id("UltraVNC") == "ultravnc-2"  # the built-in's id is taken
    assert store.new_id("!!!") == "profile"


def test_the_default_is_shared_and_falls_back_to_the_built_in(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.default_id() == BUILT_IN_DEFAULT
    store.save(_profile("clinics", "Clinics"))
    store.set_default("clinics")
    assert ProfileStore(tmp_path).default_id() == "clinics"  # everyone using the folder sees it
    store.delete("clinics")
    assert store.default_id() == BUILT_IN_DEFAULT  # deleting the default falls back


def test_editing_follows_windows_permissions(tmp_path: Path) -> None:
    assert ProfileStore(tmp_path / "not" / "made" / "yet").can_edit()  # made on the first save
    assert not ProfileStore(Path(r"C:\Windows\System32")).can_edit()
