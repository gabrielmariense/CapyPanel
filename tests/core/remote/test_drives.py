"""A person's saved network drives, read over WMI: this PC's own for real, others from an
answer written by hand."""

import getpass

import pytest

from capypanel.core.remote import drives, inventory
from capypanel.core.remote.drives import Drive, Person


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
