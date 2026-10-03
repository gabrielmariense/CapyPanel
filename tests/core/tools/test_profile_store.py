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
    store = ProfileStore(tmp_path / "profiles")
    assert [p.name for p in store.all()] == ["RealVNC", "Remote Desktop", "UltraVNC"]
    assert not (tmp_path / "profiles").exists()  # nothing written just by looking
    store.save(_profile("clinics", "Clinics"))
    files = sorted(p.name for p in (tmp_path / "profiles").glob("*.json"))
    assert files == [
        "_starters.json", "clinics.json", "realvnc.json", "remote-desktop.json", "ultravnc.json"
    ]  # fmt: skip


def test_starters_are_ordinary_profiles_that_can_be_deleted(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    for starter in ("realvnc", "remote-desktop", "ultravnc"):
        store.delete(starter)
    assert store.all() == [] and store.default_id() == ""
    assert ProfileStore(tmp_path / "profiles").all() == []  # deleted for good, not shipped back
    with pytest.raises(ProfileError):
        store.delete("ultravnc")


def test_the_default_lives_in_the_profiles_folder(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    assert store.default_id() == "ultravnc"  # the starter default
    store.save(_profile("clinics", "Clinics"))
    store.set_default("clinics")
    saved = json.loads((tmp_path / "profiles" / "_default.json").read_text(encoding="utf-8"))
    assert saved["default_profile"] == "clinics"
    assert ProfileStore(tmp_path / "profiles").default_id() == "clinics"  # everyone on the PC
    assert "_default" not in {p.id for p in store.all()}  # not mistaken for a profile
    store.delete("clinics")
    assert store.default_id() == "ultravnc"  # deleting the default falls back


def test_ids_come_from_the_name_and_never_clash(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    assert store.new_id("Clínicas (SecureVNC)") == "clinicas-securevnc"
    assert store.new_id("UltraVNC") == "ultravnc-2"  # the starter's id is taken
    assert store.new_id("!!!") == "profile"


def test_a_broken_file_is_reported_and_the_rest_still_load(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    store.save(_profile("good", "Good"))
    (tmp_path / "profiles" / "bad.json").write_text("{ nope", encoding="utf-8")
    store.reload()
    assert "good" in {p.id for p in store.all()}
    assert [path.name for path, _reason in store.problems] == ["bad.json"]


def test_editing_follows_windows_permissions(tmp_path: Path) -> None:
    # The folder is made on the first save.
    assert ProfileStore(tmp_path / "not" / "made" / "yet" / "profiles").can_edit()
    # CI runs as Administrator, who can write almost anywhere: deny this account explicitly.
    locked = tmp_path / "locked"
    locked.mkdir()
    deny = f"*{winsec.current_user_sid()}:(OI)(CI)(W,AD)"
    subprocess.run(["icacls", str(locked), "/deny", deny], check=True, capture_output=True)
    try:
        assert not ProfileStore(locked / "profiles").can_edit()
    finally:
        remove = ["icacls", str(locked), "/remove:d", f"*{winsec.current_user_sid()}"]
        subprocess.run(remove, check=True, capture_output=True)


def test_files_another_user_made_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProfileStore(tmp_path / "profiles")
    store.save(_profile("clinics", "Clinics"))
    store.set_default("clinics")
    planted = {store.folder / "planted.json", store.folder / "_default.json"}
    (store.folder / "planted.json").write_text(
        json.dumps({"schema": 1, "id": "planted", "name": "Planted", "tool": "ultravnc"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(winsec, "made_by_trusted", lambda path: path not in planted)
    again = ProfileStore(tmp_path / "profiles")
    assert "planted" not in {p.id for p in again.all()}
    assert [p for p, _reason in again.problems] == [store.folder / "planted.json"]
    assert again.default_id() == "ultravnc"  # the planted default isn't followed either


def test_the_folder_is_read_only_for_other_users_once_made(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles")
    store.save(_profile("clinics", "Clinics"))
    acl = subprocess.run(
        ["icacls", str(store.folder)], capture_output=True, text=True, check=True
    ).stdout
    # Users may read (RX), and nothing is inherited, so ProgramData's "users can add files" is gone.
    assert "(OI)(CI)(RX)" in acl and "(I)" not in acl


def test_a_settings_file_is_kept_beside_its_profile_and_goes_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProfileStore(tmp_path / "profiles")
    clinics = ConnectionProfile("clinics", "ultravnc", name="Clinics", settings_file="clinics.vnc")
    store.save(clinics, b"[options]\r\nviewonly=1\r\n")
    path = store.folder / "clinics.vnc"
    assert store.settings_path(clinics) == path
    assert path.read_bytes() == b"[options]\r\nviewonly=1\r\n"
    store.save(clinics)  # no new content: the file stays
    assert path.exists()
    monkeypatch.setattr(winsec, "made_by_trusted", lambda p: p != path)
    assert store.settings_path(clinics) is None  # another user's file isn't used
    monkeypatch.undo()
    store.save(ConnectionProfile("clinics", "ultravnc", name="Clinics"))  # back to defaults
    assert not path.exists()
    store.save(clinics, b"[options]\r\na=1\r\n")
    store.delete("clinics")
    assert not path.exists()


def test_a_new_tool_s_starter_joins_an_existing_folder_once(tmp_path: Path) -> None:
    starters = tmp_path / "starters"
    starters.mkdir()
    for pid, tool in (("ultravnc", "ultravnc"), ("remote-desktop", "mstsc")):
        data = {"schema": 1, "id": pid, "name": pid.title(), "tool": tool, "login": "none"}
        (starters / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")
    folder = tmp_path / "profiles"
    folder.mkdir()  # a folder from an older version: only the UltraVNC starter, no record
    (folder / "ultravnc.json").write_bytes((starters / "ultravnc.json").read_bytes())
    store = ProfileStore(folder, starters)
    assert {p.id for p in store.all()} == {"ultravnc", "remote-desktop"}
    assert (folder / "remote-desktop.json").is_file()  # written, so it can be edited
    store.delete("remote-desktop")
    assert "remote-desktop" not in {p.id for p in ProfileStore(folder, starters).all()}
