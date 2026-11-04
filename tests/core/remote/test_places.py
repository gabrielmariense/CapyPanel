import os
from pathlib import Path

import pytest

from capypanel.core.remote import places
from capypanel.core.remote.places import Console


def test_c_drive_and_startup_folder_paths() -> None:
    assert places.share("192.0.2.10") == "\\\\192.0.2.10\\C$"
    assert places.startup_folder("DESK-02") == (
        "\\\\DESK-02\\C$\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
    )


@pytest.mark.parametrize(
    ("typed", "opened"),
    [
        ("Users\\Public", "\\\\DESK-02\\C$\\Users\\Public"),
        ("\\Users\\Public\\", "\\\\DESK-02\\C$\\Users\\Public"),
        ("C:\\Users\\Public", "\\\\DESK-02\\C$\\Users\\Public"),
        ('"D:\\Logs\\App folder"', "\\\\DESK-02\\D$\\Logs\\App folder"),  # Copy as path
        ("  d$/Logs ", "\\\\DESK-02\\D$\\Logs"),
        ("e:", "\\\\DESK-02\\E$"),
        ("\\\\DESK-03\\D$\\Logs", "\\\\DESK-03\\D$\\Logs"),  # a full path stays as typed
    ],
)
def test_a_typed_path_becomes_one_on_the_pc(typed: str, opened: str) -> None:
    assert places.typed_path("DESK-02", typed) == opened


@pytest.mark.parametrize("typed", ["", "  ", '""', "\\"])
def test_an_empty_path_is_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        places.typed_path("DESK-02", typed)


@pytest.fixture
def users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the PC's C:\\Users folder."""
    monkeypatch.setattr(places, "share", lambda host, path="": str(tmp_path / path))
    (tmp_path / "Users").mkdir()
    return tmp_path / "Users"


def test_a_users_folder_is_found_by_their_name(users: Path) -> None:
    (users / "ana").mkdir()
    assert places.user_folder("DESK-02", "EXAMPLE\\ana") == str(users / "ana")


def test_a_second_profile_for_one_name_picks_the_newest(users: Path) -> None:
    for name, when in (("ana.EXAMPLE", 100), ("ana.000", 200), ("anabel", 300)):
        (users / name).mkdir()
        os.utime(users / name, (when, when))
    assert places.user_folder("DESK-02", "ana") == str(users / "ana.000")


def test_a_user_with_no_folder_says_so(users: Path) -> None:
    (users / "anabel").mkdir()
    with pytest.raises(FileNotFoundError):
        places.user_folder("DESK-02", "EXAMPLE\\ana")


def test_consoles_open_pointed_at_the_pc(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[tuple[str, str]] = []
    monkeypatch.setattr(
        places.os, "startfile", lambda file, arguments="": opened.append((file, arguments))
    )
    for console in Console:
        places.open_console("DESK-02", console)
    assert opened == [
        ("compmgmt.msc", "/computer=DESK-02"),
        ("eventvwr.exe", "\\\\DESK-02"),
        ("services.msc", "/computer=DESK-02"),
    ]
