"""The user profiles on a PC. The read runs here for real (this PC's own profiles over WMI); the
rules that sort profiles into states run on a folder that stands in for a PC's drive, with the
WMI answer written by hand. Deleting a real profile only ever happens on CI's throwaway machine,
on an account the test makes for it."""

import _winapi
import contextlib
import ctypes
import getpass
import os
import secrets
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from capypanel.core import winsec
from capypanel.core.remote import inventory, user_profiles
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.user_profiles import (
    Deleted,
    Kind,
    Outcome,
    Profile,
    Scan,
    State,
    Why,
)

DOMAIN = "S-1-5-21-1004336348-1177238915-682003330"
ENTRA = "S-1-12-1-2535252497-1114326289-2412693642-1264021683"
NAMES = {
    f"{DOMAIN}-1101": "EXAMPLE\\ana",
    f"{DOMAIN}-1102": "EXAMPLE\\rui",
    f"{DOMAIN}-500": "DESK-01\\Administrator",
    f"{DOMAIN}-1105": "EXAMPLE\\caio",
    ENTRA: "AzureAD\\eva",
}


def _here(path: str) -> str:
    """A path on this PC, in the long form the tool opens the PC's paths in."""
    return "\\\\?\\" + path


def _pc(tmp_path: Path, *folders: str) -> Callable[[str], str]:
    """A folder standing in for a PC's C: drive, with these folders in its Users; and the way
    to open the PC's paths (C:\\Users\\ana) there."""
    for name in folders:
        (tmp_path / "Users" / name).mkdir(parents=True)
    return lambda path: _here(str(tmp_path / path[3:]))


def _key(sid: str, folder: str, **more: Any) -> dict[str, Any]:
    path = folder if ":" in folder else f"C:\\Users\\{folder}"
    return {"name": sid, "path": path, **more}


def _stamp(which: str, when: datetime) -> dict[str, int]:
    """A time as the registry keeps it: two halves of a count of 100 ns steps since 1601."""
    ticks = int((when - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds()) * 10_000_000
    return {f"{which}_high": ticks >> 32, f"{which}_low": ticks & 0xFFFFFFFF}


def _facts(keys: list[dict[str, Any]], **more: Any) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "root": "C:\\Users", "windows": "C:\\Windows", "admin": "Administrator", "console": "",
        "keys": keys, "profiles": [], "hives": [],
    }  # fmt: skip
    return {**facts, **more}


def _combine(facts: dict[str, Any], opened: Callable[[str], str]) -> dict[str, Profile]:
    found = user_profiles._combine("DESK-01", facts, opened, lambda sid: NAMES.get(sid, ""))
    return {p.path.rpartition("\\")[2] or p.sid: p for p in found.profiles}


# ---- reading ----


def test_this_pcs_own_profiles_read_over_wmi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_profiles, "check_reachable", lambda host: None)
    found = user_profiles.scan("localhost", opened=_here)
    mine = next(p for p in found.profiles if p.sid == winsec.current_user_sid())
    # CI runs as the built-in Administrator, whose profile is Windows' own before it's in use.
    state = State.PROTECTED if mine.sid.endswith("-500") else State.IN_USE
    assert (mine.kind, mine.state, mine.known) == (Kind.PROFILE, state, True)
    assert mine.user.rpartition("\\")[2].casefold() == getpass.getuser().casefold()
    assert mine.path.casefold() == os.environ["USERPROFILE"].casefold()
    assert mine.last_used is not None and mine.modified is not None
    shared = f"{found.root}\\public".casefold()
    public = next(p for p in found.profiles if p.path.casefold() == shared)
    assert (public.kind, public.state) == (Kind.FOLDER, State.PROTECTED)


def test_asking_this_pc_to_delete_what_isnt_there_says_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two delete scripts run for real against this PC, on a SID nobody has: they read,
    find nothing, and stop."""
    monkeypatch.setattr(user_profiles, "check_reachable", lambda host: None)
    sid = f"S-1-5-21-1111111111-222222222-333333333-{secrets.randbelow(80000) + 10000}"
    scanned = Scan("localhost", "C:\\Users", ())
    nobody = f"C:\\Users\\capypanel-nobody-{secrets.token_hex(3)}"
    for kind in (Kind.PROFILE, Kind.ENTRY):
        profile = Profile(sid, sid, "nobody", False, nobody, kind, State.READY)
        done = user_profiles.delete(scanned, profile, opened=_here)
        assert (done.outcome, done.why, done.detail) == (Outcome.SKIPPED, Why.GONE, "")


def test_each_profile_gets_the_first_state_that_applies(tmp_path: Path) -> None:
    opened = _pc(tmp_path, "ana", "rui", "Administrator", "caio", "eva", "Public", "Default")
    facts = _facts(
        [
            _key(f"{DOMAIN}-1101", "ana"),
            _key(f"{DOMAIN}-1102", "rui"),
            _key(f"{DOMAIN}-500", "Administrator"),
            _key(f"{DOMAIN}-1103", "bia"),  # its folder is gone
            _key(f"{DOMAIN}-1105.bak", "caio"),
            _key(f"{DOMAIN}-1106", "D:\\Perfis\\dora"),
            _key(ENTRA, "eva"),
            _key("S-1-5-18", "C:\\Windows\\system32\\config\\systemprofile"),
        ],
        hives=[{"sid": f"{DOMAIN}-1102", "user": "rui", "folder": "C:\\Users\\rui"}],
        profiles=[{"sid": ENTRA, "path": "C:\\Users\\eva", "loaded": True, "special": False}],
    )
    found = _combine(facts, opened)
    assert {name: (p.kind, p.state) for name, p in found.items()} == {
        "ana": (Kind.PROFILE, State.READY),
        "rui": (Kind.PROFILE, State.IN_USE),
        "Administrator": (Kind.PROFILE, State.PROTECTED),
        "bia": (Kind.ENTRY, State.READY),
        "caio": (Kind.BACKUP, State.REVIEW),
        "dora": (Kind.ENTRY, State.OUTSIDE),
        "eva": (Kind.PROFILE, State.IN_USE),  # Windows' list says so, with no hive seen
        "Public": (Kind.FOLDER, State.PROTECTED),
        "Default": (Kind.FOLDER, State.PROTECTED),
    }
    assert (found["ana"].user, found["ana"].known) == ("EXAMPLE\\ana", True)
    assert (found["bia"].user, found["bia"].known) == ("bia", False)  # the account is gone
    assert found["caio"].key == f"{DOMAIN}-1105.bak" and found["caio"].sid == f"{DOMAIN}-1105"
    assert found["ana"].modified is not None and found["bia"].modified is None


def test_a_folder_no_entry_names_is_a_leftover_unless_someone_signed_in_has_its_name(
    tmp_path: Path,
) -> None:
    opened = _pc(tmp_path, "ana", "old.rui", "eva", "chefe", "TEMP")
    (tmp_path / "Users" / "desktop.ini").write_text("")  # a file: never a row
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(tmp_path / "Users" / "Todos"))
    facts = _facts(
        [_key(f"{DOMAIN}-1101", "ana")],
        admin="chefe",  # the built-in Administrator, renamed
        console="EXAMPLE\\eva",
        hives=[{"sid": f"{DOMAIN}-1109", "user": "temp", "folder": "C:\\Users\\TEMP"}],
    )
    found = _combine(facts, opened)
    assert {name: (p.kind, p.state) for name, p in found.items()} == {
        "ana": (Kind.PROFILE, State.READY),
        "old.rui": (Kind.FOLDER, State.READY),
        "eva": (Kind.FOLDER, State.IN_USE),
        "TEMP": (Kind.FOLDER, State.IN_USE),
        "chefe": (Kind.FOLDER, State.PROTECTED),
        "Todos": (Kind.FOLDER, State.PROTECTED),  # a link: its files live somewhere else
    }
    assert found["old.rui"].sid == "" and not found["old.rui"].known


def test_a_profile_listed_by_windows_with_no_entry_is_still_a_row(tmp_path: Path) -> None:
    opened = _pc(tmp_path, "ana")
    profiles = [
        {"sid": f"{DOMAIN}-1101", "path": "C:\\Users\\ana", "loaded": False, "special": False},
        {"sid": "S-1-5-19", "path": "C:\\Windows\\ServiceProfiles\\LocalService", "special": True},
    ]
    found = _combine(_facts([], profiles=profiles), opened)
    assert list(found) == ["ana"]
    assert (found["ana"].kind, found["ana"].state, found["ana"].key) == (
        Kind.PROFILE, State.READY, "",
    )  # fmt: skip


def test_last_used_is_the_later_of_the_last_sign_in_and_sign_out(tmp_path: Path) -> None:
    opened = _pc(tmp_path, "ana", "rui")
    sign_in = _stamp("load", datetime(2025, 10, 1, 8, 0, tzinfo=UTC))
    sign_out = _stamp("unload", datetime(2025, 10, 31, 17, 30, tzinfo=UTC))
    facts = _facts(
        [_key(f"{DOMAIN}-1101", "ana", **sign_in, **sign_out), _key(f"{DOMAIN}-1102", "rui")]
    )
    found = _combine(facts, opened)
    used = found["ana"].last_used
    assert used == datetime(2025, 10, 31, 17, 30, tzinfo=UTC)  # the sign-out, the later one
    assert found["rui"].last_used is None  # an old Windows that doesn't write them


def test_rows_come_sorted_by_name_and_one_profile_alone_is_still_a_list(tmp_path: Path) -> None:
    opened = _pc(tmp_path, "rui", "ana")
    facts = _facts([_key(f"{DOMAIN}-1102", "rui"), _key(f"{DOMAIN}-1101", "ana")])
    found = user_profiles._combine("DESK-01", facts, opened, lambda sid: NAMES.get(sid, ""))
    assert [p.user for p in found.profiles] == ["EXAMPLE\\ana", "EXAMPLE\\rui"]
    alone = _facts([])
    alone["keys"] = _key(f"{DOMAIN}-1101", "ana")  # PowerShell writes a list of one this way
    assert list(_combine(alone, opened)) == ["ana", "rui"]


def test_a_drive_share_that_cant_be_read_stops_the_scan(tmp_path: Path) -> None:
    with pytest.raises(RemoteError) as e:
        _combine(_facts([_key(f"{DOMAIN}-1101", "ana")]), _pc(tmp_path))  # no Users folder
    assert e.value.reason is Reason.OTHER


def test_the_pcs_paths_open_through_its_drive_share_in_the_long_form() -> None:
    assert user_profiles.share_path("DESK-01", "C:\\Users\\ana") == (
        "\\\\?\\UNC\\DESK-01\\C$\\Users\\ana"
    )
    other_drive = user_profiles.share_path("192.0.2.10", "d:\\Perfis\\")
    assert other_drive == "\\\\?\\UNC\\192.0.2.10\\d$\\Perfis"
    with pytest.raises(ValueError):
        user_profiles.share_path("DESK-01", "\\\\FS01\\perfis\\ana")


def test_typing_the_pcs_name_confirms_whatever_its_case() -> None:
    assert user_profiles.confirmed(" desk-01 ", "DESK-01")
    assert not user_profiles.confirmed("DESK-0", "DESK-01")
    assert not user_profiles.confirmed("", "")


# ---- sizes ----


def test_a_folders_size_counts_its_files_and_never_follows_a_link(tmp_path: Path) -> None:
    profile = tmp_path / "ana"
    (profile / "Documents" / "deep").mkdir(parents=True)
    (profile / "ntuser.dat").write_bytes(b"x" * 1000)
    (profile / "Documents" / "deep" / "a.txt").write_bytes(b"x" * 234)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"x" * 50_000)
    _winapi.CreateJunction(str(outside), str(profile / "Application Data"))
    assert user_profiles.folder_size(_here(str(profile))) == 1234
    assert user_profiles.folder_size(_here(str(profile)), stop=lambda: True) is None
    with pytest.raises(OSError):
        user_profiles.folder_size(_here(str(tmp_path / "nobody")))


def test_a_profiles_size_is_read_where_the_pc_keeps_it(tmp_path: Path) -> None:
    opened = _pc(tmp_path, "ana")
    (tmp_path / "Users" / "ana" / "a.txt").write_bytes(b"x" * 77)
    found = _combine(_facts([_key(f"{DOMAIN}-1101", "ana"), _key(f"{DOMAIN}-1103", "bia")]), opened)
    scanned = Scan("DESK-01", "C:\\Users", tuple(found.values()))
    assert user_profiles.profile_size(scanned, found["ana"], opened=opened) == 77
    assert user_profiles.profile_size(scanned, found["bia"], opened=opened) is None  # no folder


# ---- deleting ----


def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("nothing may reach the PC")

    monkeypatch.setattr(user_profiles, "check_reachable", never)
    monkeypatch.setattr(inventory, "run_cim", never)


def _answers(monkeypatch: pytest.MonkeyPatch, answer: object) -> list[tuple[str, dict[str, str]]]:
    """The PC answers every WMI script with `answer` (raised, if it's an error); the scripts
    asked and their values are kept."""
    asked: list[tuple[str, dict[str, str]]] = []

    def run_cim(script: str, host: str, account: Account | None, **more: Any) -> object:
        asked.append((script, dict(more.get("values") or {})))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(user_profiles, "check_reachable", lambda host: None)
    monkeypatch.setattr(inventory, "run_cim", run_cim)
    return asked


def _ana(state: State = State.READY, kind: Kind = Kind.PROFILE) -> Profile:
    sid = f"{DOMAIN}-1101"
    return Profile(sid, sid, "EXAMPLE\\ana", True, "C:\\Users\\ana", kind, state)


SCANNED = Scan("DESK-01", "C:\\Users", ())


@pytest.mark.parametrize("state", [s for s in State if s is not State.READY])
def test_only_a_ready_profile_is_ever_sent_to_the_pc(
    state: State, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_network(monkeypatch)
    done = user_profiles.delete(SCANNED, _ana(state))
    assert (done.outcome, done.why) == (Outcome.SKIPPED, Why.NOT_READY)


def test_a_profile_is_removed_by_windows_after_its_own_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _answers(monkeypatch, {"outcome": "deleted"})
    done = user_profiles.delete(SCANNED, _ana())
    assert done == Deleted(_ana(), Outcome.DELETED)
    [(script, values)] = asked
    assert script == user_profiles._DELETE_PROFILE and "Remove-CimInstance" in script
    assert (values["sid"], values["path"]) == (f"{DOMAIN}-1101", "C:\\Users\\ana")


@pytest.mark.parametrize(
    ("said", "why"),
    [("in-use", Why.IN_USE), ("gone", Why.GONE), ("changed", Why.CHANGED),
     ("protected", Why.PROTECTED)],
)  # fmt: skip
def test_what_the_check_on_the_pc_finds_skips_the_delete(
    said: str, why: Why, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answers(monkeypatch, {"outcome": said})
    done = user_profiles.delete(SCANNED, _ana())
    assert (done.outcome, done.why) == (Outcome.SKIPPED, why)


def test_windows_refusing_or_the_pc_not_answering_is_a_failure_with_its_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answers(monkeypatch, {"outcome": "failed", "text": " The process cannot access the file. "})
    done = user_profiles.delete(SCANNED, _ana())
    assert (done.outcome, done.why, done.detail) == (
        Outcome.FAILED, Why.ERROR, "The process cannot access the file.",
    )  # fmt: skip
    _answers(monkeypatch, RemoteError(Reason.UNREACHABLE))
    done = user_profiles.delete(SCANNED, _ana())
    assert (done.outcome, done.why, done.detail) == (Outcome.FAILED, Why.ERROR, "unreachable")
    _answers(monkeypatch, TimeoutError("WMI didn't answer within 3660 s"))
    assert user_profiles.delete(SCANNED, _ana()).outcome is Outcome.FAILED


def test_a_sid_that_isnt_one_never_reaches_the_wmi_query(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = _answers(monkeypatch, {"outcome": "deleted"})
    path = "C:\\Users\\x"
    odd = Profile("S-1-5-21-1' OR '1'='1", "", "x", False, path, Kind.PROFILE, State.READY)
    assert user_profiles.delete(SCANNED, odd).outcome is Outcome.SKIPPED
    entry = Profile("S-1-5-21-1", "..\\ProfileGuid", "x", False, "", Kind.ENTRY, State.READY)
    assert user_profiles.delete(SCANNED, entry).outcome is Outcome.SKIPPED
    assert asked == []


def test_an_entry_goes_only_while_its_folder_is_still_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = _pc(tmp_path)
    sid = f"{DOMAIN}-1103"
    bia = Profile(sid, sid, "bia", False, "C:\\Users\\bia", Kind.ENTRY, State.READY)
    asked = _answers(monkeypatch, {"outcome": "deleted", "kept": '{"Flags":0}'})
    log_file = tmp_path / "logs" / "ana.user-profiles.log"
    done = user_profiles.delete(SCANNED, bia, log_file=log_file, opened=opened)
    assert (done.outcome, done.detail) == (Outcome.DELETED, 'it held {"Flags":0}')
    [(script, values)] = asked
    assert script == user_profiles._DELETE_ENTRY
    assert values == {"key": sid, "sid": sid, "path": "C:\\Users\\bia"}
    assert '{"Flags":0}' in log_file.read_text(encoding="utf-8")  # what it held, kept
    (tmp_path / "Users" / "bia").mkdir(parents=True)  # the folder is back: a profile again
    done = user_profiles.delete(SCANNED, bia, opened=opened)
    assert (done.outcome, done.why) == (Outcome.SKIPPED, Why.CHANGED)
    assert len(asked) == 1


def _leftover(tmp_path: Path) -> tuple[Callable[[str], str], Scan, Profile]:
    opened = _pc(tmp_path, "ana", "old.rui")
    (tmp_path / "Users" / "old.rui" / "Desktop").mkdir()
    (tmp_path / "Users" / "old.rui" / "Desktop" / "a.txt").write_text("x")
    found = _combine(_facts([_key(f"{DOMAIN}-1101", "ana")]), opened)
    return opened, Scan("DESK-01", "C:\\Users", tuple(found.values())), found["old.rui"]


def _delete_leftover(
    opened: Callable[[str], str], scanned: Scan, profile: Profile, log_file: Path | None = None
) -> Deleted:
    return user_profiles.delete(
        scanned, profile, opened=opened, name_of=lambda sid: NAMES.get(sid, ""), log_file=log_file
    )


def test_a_leftover_folder_is_scanned_again_and_then_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened, scanned, old = _leftover(tmp_path)
    asked = _answers(monkeypatch, _facts([_key(f"{DOMAIN}-1101", "ana")]))
    log_file = tmp_path / "ana.user-profiles.log"
    done = _delete_leftover(opened, scanned, old, log_file)
    assert done == Deleted(old, Outcome.DELETED)
    assert not (tmp_path / "Users" / "old.rui").exists() and (tmp_path / "Users" / "ana").is_dir()
    assert asked[0][0] == user_profiles._FACTS
    when, *rest = log_file.read_text(encoding="utf-8").rstrip("\n").split("\t")
    assert rest == [
        "DESK-01", "(your Windows account)", "old.rui", "-", "C:\\Users\\old.rui", "folder",
        "deleted",
    ]  # fmt: skip
    assert datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    again = _delete_leftover(opened, scanned, old)
    assert (again.outcome, again.why) == (Outcome.SKIPPED, Why.GONE)


@pytest.mark.parametrize(
    ("now", "why"),
    [
        ({"keys": [_key(f"{DOMAIN}-1102", "old.rui")]}, Why.CHANGED),  # an entry names it again
        ({"console": "EXAMPLE\\old.rui"}, Why.IN_USE),  # someone by that name signed in
        ({"admin": "old.rui"}, Why.PROTECTED),
    ],
)
def test_a_leftover_folder_that_changed_since_the_scan_stays(
    now: dict[str, Any], why: Why, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened, scanned, old = _leftover(tmp_path)
    _answers(monkeypatch, _facts([_key(f"{DOMAIN}-1101", "ana")]) | now)
    done = _delete_leftover(opened, scanned, old)
    assert (done.outcome, done.why) == (Outcome.SKIPPED, why)
    assert (tmp_path / "Users" / "old.rui" / "Desktop" / "a.txt").exists()


def test_only_a_folder_directly_in_users_can_be_a_leftover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened, scanned, _old = _leftover(tmp_path)
    asked = _answers(monkeypatch, _facts([]))
    for path in ("C:\\Users\\ana\\Documents", "C:\\Windows", "C:\\Users"):
        inner = Profile("", "", "x", False, path, Kind.FOLDER, State.READY)
        done = _delete_leftover(opened, scanned, inner)
        assert (done.outcome, done.why) == (Outcome.SKIPPED, Why.CHANGED)
    assert asked == [] and (tmp_path / "Users" / "ana").is_dir()


def test_removing_a_folder_takes_read_only_files_and_leaves_what_links_point_at(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "old.rui"
    (folder / "AppData" / "Local").mkdir(parents=True)
    locked = folder / "AppData" / "locked.txt"
    locked.write_text("x")
    locked.chmod(0o444)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    _winapi.CreateJunction(str(outside), str(folder / "AppData" / "Local" / "Link"))
    assert user_profiles.remove_tree(_here(str(folder))) == []
    assert not folder.exists()
    assert (outside / "keep.txt").read_text() == "keep"


def test_a_folder_that_is_a_link_itself_is_never_removed(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    _winapi.CreateJunction(str(outside), str(link))
    [failed] = user_profiles.remove_tree(_here(str(link)))
    assert failed.endswith(": a link") and outside.is_dir() and link.exists()


def test_what_couldnt_be_removed_is_named_and_the_delete_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened, scanned, old = _leftover(tmp_path)
    _answers(monkeypatch, _facts([_key(f"{DOMAIN}-1101", "ana")]))
    with (tmp_path / "Users" / "old.rui" / "Desktop" / "a.txt").open("rb"):  # a file in use
        done = _delete_leftover(opened, scanned, old)
    assert (done.outcome, done.why) == (Outcome.FAILED, Why.LEFT)
    assert "a.txt" in done.detail


# ---- for real, on CI only ----

_userenv = ctypes.WinDLL("userenv", use_last_error=True)
_userenv.CreateProfile.restype = ctypes.c_long
_userenv.CreateProfile.argtypes = [
    ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong,
]  # fmt: skip
_PROFILE_LIST = "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList"


def _quiet(*command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


@pytest.mark.skipif(
    not os.environ.get("GITHUB_ACTIONS"),
    reason="makes a Windows account and deletes its profile: only on CI's throwaway machine",
)
def test_a_real_profile_an_entry_and_a_leftover_folder_are_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(user_profiles, "check_reachable", lambda host: None)
    name = f"capy{secrets.token_hex(3)}"
    gone_sid = f"S-1-5-21-1111111111-222222222-333333333-{secrets.randbelow(80000) + 10000}"
    gone_key = f"{_PROFILE_LIST}\\{gone_sid}"
    leftover: Path | None = None
    # 14 characters: past that, net user stops to ask about old versions of Windows.
    made = _quiet("net", "user", name, secrets.token_urlsafe(8)[:10] + "aA1!", "/add")
    created, said = made.returncode == 0, made.stderr  # the password stays out of the report
    assert created, said
    try:
        sid = _quiet(
            "powershell", "-NoProfile", "-Command",
            f"(New-Object Security.Principal.NTAccount('{name}')).Translate("
            "[Security.Principal.SecurityIdentifier]).Value",
        ).stdout.strip()  # fmt: skip
        folder_name = ctypes.create_unicode_buffer(260)
        assert _userenv.CreateProfile(sid, name, folder_name, 260) == 0
        folder = Path(folder_name.value)
        (folder / "Desktop" / "note.txt").write_text("x")
        leftover = folder.with_name(f"{name}.old")
        (leftover / "Documents").mkdir(parents=True)
        (leftover / "Documents" / "a.txt").write_text("x")
        added = _quiet(
            "reg", "add", gone_key, "/v", "ProfileImagePath", "/t", "REG_EXPAND_SZ", "/d",
            f"%SystemDrive%\\Users\\{name}.gone", "/f",
        )  # fmt: skip
        assert added.returncode == 0, added.stderr

        found = user_profiles.scan("localhost", opened=_here)
        by_path = {p.path.casefold(): p for p in found.profiles}
        real = by_path[str(folder).casefold()]
        entry = next(p for p in found.profiles if p.sid == gone_sid)
        old = by_path[str(leftover).casefold()]
        assert (real.kind, real.state, real.known) == (Kind.PROFILE, State.READY, True)
        assert real.user.casefold().endswith(f"\\{name}")
        assert (entry.kind, entry.state) == (Kind.ENTRY, State.READY)
        assert (old.kind, old.state) == (Kind.FOLDER, State.READY)
        assert user_profiles.profile_size(found, real, opened=_here)

        log_file = tmp_path / "ci.user-profiles.log"
        for profile in (real, entry, old):
            done = user_profiles.delete(found, profile, log_file=log_file, opened=_here)
            assert done.outcome is Outcome.DELETED, done
        assert not folder.exists() and not leftover.exists()
        assert _quiet("reg", "query", gone_key).returncode != 0
        after = {p.ident for p in user_profiles.scan("localhost", opened=_here).profiles}
        assert not after & {real.ident, entry.ident, old.ident}
        assert len(log_file.read_text(encoding="utf-8").splitlines()) == 3
        # Asked again, each says it's gone instead of failing.
        assert user_profiles.delete(found, real, opened=_here).why is Why.GONE
        assert user_profiles.delete(found, entry, opened=_here).why is Why.GONE
    finally:
        _quiet("net", "user", name, "/delete")
        _quiet("reg", "delete", gone_key, "/f")
        if leftover is not None:
            shutil.rmtree(leftover, ignore_errors=True)


def test_a_folder_count_says_how_far_it_is_after_each_folder(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.bin").write_bytes(b"x" * 10)
    (tmp_path / "two.bin").write_bytes(b"x" * 5)
    heard: list[int] = []
    assert user_profiles.folder_size(str(tmp_path), progress=heard.append) == 15
    assert heard == [5, 15]  # the folder itself, then the one inside it


def test_a_folder_is_counted_by_several_threads_each_as_the_account(tmp_path: Path) -> None:
    expected = 0
    for a in range(6):
        for b in range(5):
            deep = tmp_path / f"a{a}" / f"b{b}" / "c"
            deep.mkdir(parents=True)
            (deep / "file.bin").write_bytes(b"x" * (a * 10 + b + 1))
            expected += a * 10 + b + 1
    entered: set[int] = set()

    @contextlib.contextmanager
    def identity() -> Iterator[None]:
        entered.add(threading.get_ident())
        yield

    counted = user_profiles.folder_size(str(tmp_path), walkers=4, identity=identity)
    assert counted == expected == user_profiles.folder_size(str(tmp_path), walkers=1)
    assert len(entered) == 4 and threading.get_ident() not in entered  # each thread signs in

    seen = 0

    def stop() -> bool:  # stopped part-way: no number, and the threads end
        nonlocal seen
        seen += 1
        return seen > 5

    assert user_profiles.folder_size(str(tmp_path), stop=stop, walkers=4) is None

    @contextlib.contextmanager
    def refused() -> Iterator[None]:
        raise RemoteError(Reason.REJECTED, 1326)
        yield

    with pytest.raises(RemoteError):  # a thread that can't sign in: told, never a hang
        user_profiles.folder_size(str(tmp_path), identity=refused)


def test_a_time_no_profile_can_have_is_unknown_not_a_date(tmp_path: Path) -> None:
    """A half-written registry value reads as 1601 or the far future, and a date before 1970
    can't even be shown in local time on Windows: both read as unknown ("—")."""
    opened = _pc(tmp_path, "ana", "rui", "eva")
    old = {"load_high": 0, "load_low": 5}  # a few ticks after 1601
    future = _stamp("load", datetime.now(UTC) + timedelta(days=400))
    good = _stamp("load", datetime(2025, 3, 11, tzinfo=UTC))
    found = _combine(
        _facts([
            _key(f"{DOMAIN}-1101", "ana", **old),
            _key(f"{DOMAIN}-1102", "rui", **future),
            _key(f"{DOMAIN}-1103", "eva", **good),
        ]),
        opened,
    )  # fmt: skip
    assert found["ana"].last_used is None and found["rui"].last_used is None
    assert found["eva"].last_used == datetime(2025, 3, 11, tzinfo=UTC)
    assert user_profiles._modified(-86_400 * 365 * 400) is None  # a folder time before 1980
    assert user_profiles._modified(1_700_000_000) is not None
