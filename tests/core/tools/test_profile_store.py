import json
import subprocess
from pathlib import Path

import pytest

from capypanel.core import winsec
from capypanel.core.tools.profile_store import ProfileStore
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError


def _profile(pid: str, name: str) -> ConnectionProfile:
    return ConnectionProfile(pid, "ultravnc", name=name)


def test_the_starters_show_until_the_folder_exists_then_become_files(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert [p.name for p in store.all()] == ["RealVNC", "UltraVNC"]
    assert not (tmp_path / "profiles").exists()  # nothing written just by looking
    store.save(_profile("clinics", "Clinics"))
    files = sorted(p.name for p in (tmp_path / "profiles").glob("*.json"))
    assert files == ["clinics.json", "realvnc.json", "ultravnc.json"]


def test_starters_are_ordinary_profiles_that_can_be_deleted(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.delete("realvnc")
    store.delete("ultravnc")
    assert store.all() == [] and store.default_id() == ""
    assert ProfileStore(tmp_path).all() == []  # deleted for good, not shipped back
    with pytest.raises(ProfileError):
        store.delete("ultravnc")


def test_the_default_lives_in_the_profiles_folder(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.default_id() == "ultravnc"  # the starter default
    store.save(_profile("clinics", "Clinics"))
    store.set_default("clinics")
    saved = json.loads((tmp_path / "profiles" / "_default.json").read_text(encoding="utf-8"))
    assert saved["default_profile"] == "clinics"
    assert ProfileStore(tmp_path).default_id() == "clinics"  # everyone using the folder
    assert "_default" not in {p.id for p in store.all()}  # not mistaken for a profile
    store.delete("clinics")
    assert store.default_id() == "ultravnc"  # deleting the default falls back


def test_ids_come_from_the_name_and_never_clash(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    assert store.new_id("Clínicas (SecureVNC)") == "clinicas-securevnc"
    assert store.new_id("UltraVNC") == "ultravnc-2"  # the starter's id is taken
    assert store.new_id("!!!") == "profile"


def test_a_broken_file_is_reported_and_the_rest_still_load(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path)
    store.save(_profile("good", "Good"))
    (tmp_path / "profiles" / "bad.json").write_text("{ nope", encoding="utf-8")
    store.reload()
    assert "good" in {p.id for p in store.all()}
    assert [path.name for path, _reason in store.problems] == ["bad.json"]


def test_editing_follows_windows_permissions(tmp_path: Path) -> None:
    assert ProfileStore(tmp_path / "not" / "made" / "yet").can_edit()  # made on the first save
    # CI runs as Administrator, who can write almost anywhere: deny this account explicitly.
    locked = tmp_path / "locked"
    locked.mkdir()
    deny = f"*{winsec.current_user_sid()}:(OI)(CI)(W,AD)"
    subprocess.run(["icacls", str(locked), "/deny", deny], check=True, capture_output=True)
    try:
        assert not ProfileStore(locked).can_edit()
    finally:
        remove = ["icacls", str(locked), "/remove:d", f"*{winsec.current_user_sid()}"]
        subprocess.run(remove, check=True, capture_output=True)
