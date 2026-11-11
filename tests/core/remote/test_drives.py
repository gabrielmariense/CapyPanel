"""A person's network drives and caches. The reads run here for real (this PC's own saved drives
over WMI, the session check through the real wrapper); Clear caches runs for real on a folder that
stands in for a profile. Mapping a drive changes the PC, so it's only checked, never run."""

import getpass
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from capypanel.core.remote import drives, inventory
from capypanel.core.remote.access import Account
from capypanel.core.remote.drives import App, CacheState, Cleared, Drive, Person
from capypanel.core.remote.run import Engine, Job, Runner, RunResult, Script


def _run_here(folder: Path, script: Script) -> RunResult:
    """Runs `script` through the real wrapper with this PC's own PowerShell, in `folder`."""

    def start(host: str, command: Sequence[str], account: Account | None, _job: Job) -> None:
        subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW)

    runs = Runner(
        lambda: None,
        starters={engine: start for engine in Engine},
        folder_of=lambda host: folder,
        listens=lambda host, port: True,
        reachable=lambda host: None,
        remote_folder=str(folder),
    )
    return runs.run("DESK-01", script, timeout=60)


def test_this_pcs_signed_in_people_read_over_wmi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drives, "check_reachable", lambda host: None)
    people = drives.saved_drives("localhost")
    assert getpass.getuser().casefold() in {p.user.casefold() for p in people}
    assert all(d.letter.endswith(":") for p in people for d in p.drives)


def test_saved_drives_are_sorted_with_their_letters_written_as_windows_shows_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = [
        {"user": "rui", "domain": "EXAMPLE", "drives": []},
        {"user": "ana", "domain": "EXAMPLE", "drives": [
            {"letter": "s", "path": "\\\\FS01\\Setores"}, {"letter": "H", "path": "\\\\FS01\\ana"},
        ]},
        {"user": "", "domain": "", "drives": []},  # a hive with no one: never listed
    ]  # fmt: skip
    monkeypatch.setattr(drives, "check_reachable", lambda host: None)
    monkeypatch.setattr(inventory, "run_cim", lambda script, host, account: answer)
    assert drives.saved_drives("192.0.2.10") == [
        Person("ana", "EXAMPLE", (Drive("H:", "\\\\FS01\\ana"), Drive("S:", "\\\\FS01\\Setores"))),
        Person("rui", "EXAMPLE", ()),
    ]
    assert Person("ana", "EXAMPLE", ()).account == "EXAMPLE\\ana"


def test_the_session_check_runs_and_says_what_it_found(tmp_path: Path) -> None:
    result = _run_here(tmp_path, drives.LIVE_SCRIPT)
    assert result.exit_code == 0, result.errors
    found = drives.live_drives(result.output)
    assert all(d.letter.endswith(":") and d.status for d in found)


def test_session_lines_are_read_by_letter() -> None:
    said = ("CAPYPANEL-DRIVE\tS:\t\\\\FS01\\Setores\tOK\n"
            "noise\nCAPYPANEL-DRIVE\th:\t\\\\FS01\\ana\tUnavailable\n")  # fmt: skip
    found = drives.live_drives(said)
    assert found == [Drive("H:", "\\\\FS01\\ana", "Unavailable"),
                     Drive("S:", "\\\\FS01\\Setores", "OK")]  # fmt: skip
    assert [drives.connected(d) for d in found] == [False, True]


def test_only_a_letter_and_a_share_can_be_mapped() -> None:
    script = drives.map_script("S:", "\\\\FS01\\Setores\\")
    assert script.arguments == ("S:", "\\\\FS01\\Setores")
    for letter, path in [("C:", "\\\\FS01\\x"), ("S", "\\\\FS01\\x"), ("S:", "C:\\Users"),
                         ("S:", "\\\\FS01"), ("S:", "http://example.com/x"),
                         ("S:", "\\\\FS01\\x\" & calc")]:  # fmt: skip
        with pytest.raises(ValueError):
            drives.map_script(letter, path)


def _file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_clear_caches_empties_only_the_cache_folders(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    teams = profile / "AppData/Roaming/Microsoft/Teams"
    _file(teams / "Cache/data_1", 100)
    _file(teams / "IndexedDB/x.db", 50)
    edge = profile / "AppData/Local/Microsoft/Edge/User Data"
    _file(edge / "Default/Preferences", 10)
    _file(edge / "Default/Cache/Cache_Data/f_1", 200)
    _file(edge / "Default/Bookmarks", 10)  # not a cache: stays
    _file(edge / "Default/Cookies", 10)  # stays
    person = Person("nobody-here", "EXAMPLE", ())
    script = drives.clear_script(person, (App.TEAMS, App.EDGE, App.CHROME), str(profile))
    result = _run_here(tmp_path / "run", script)
    assert result.exit_code == 0, result.errors
    assert drives.cleared(result.output) == [
        Cleared(App.TEAMS, CacheState.CLEARED, 150, 0),
        Cleared(App.EDGE, CacheState.CLEARED, 200, 0),
        Cleared(App.CHROME, CacheState.NONE),
    ]
    assert teams.is_dir() and not any(teams.iterdir())
    assert (edge / "Default/Bookmarks").exists() and (edge / "Default/Cookies").exists()
    assert not any((edge / "Default/Cache").iterdir())


def test_cache_lines_name_what_stayed_open() -> None:
    said = "CAPYPANEL-CACHE teams open 0 0\nCAPYPANEL-CACHE chrome cleared 2048 3\n"
    assert drives.cleared(said) == [
        Cleared(App.TEAMS, CacheState.OPEN), Cleared(App.CHROME, CacheState.CLEARED, 2048, 3),
    ]  # fmt: skip
