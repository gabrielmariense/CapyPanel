import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from capypanel.core.hosts import listfile
from capypanel.core.hosts.listfile import (
    HostListChangedError,
    HostListFormatError,
    HostListTooNewError,
)
from capypanel.core.hosts.model import HostList

EXAMPLE: dict[str, Any] = {
    "schema": 1,
    "groups": [
        {"id": "g1", "name": "Headquarters", "parent": None},
        {"id": "g2", "name": "Finance", "parent": "g1", "color": "blue"},
    ],
    "hosts": [
        {
            "id": "h7",
            "name": "FIN-PC04",
            "address": "10.0.12.24",
            "group": "g2",
            "tags": ["floor-3", "contract-2025"],
            "notes": "Reception desk",
            "detected": {"os": "Windows 11"},
        }
    ],
    "written_by": "a newer tool",
}


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_round_trip_keeps_everything_including_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    _write(path, EXAMPLE)
    loaded = listfile.load(path)
    listfile.save(path, loaded.hosts, expected=loaded.stamp)
    assert json.loads(path.read_text(encoding="utf-8")) == EXAMPLE


def test_file_with_a_bom_opens(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(EXAMPLE).encode())
    assert listfile.load(path).hosts.host("h7") is not None


@pytest.mark.parametrize(
    "data",
    [
        "{ not json",
        [1, 2],
        {"groups": [], "hosts": []},  # no schema
        {"schema": "1"},
        {"schema": 1, "hosts": {}},
        {"schema": 1, "groups": [{"id": "g1", "name": "A"}, {"id": "g1", "name": "B"}]},
        {"schema": 1, "groups": [{"id": "g1", "name": "A", "parent": "nope"}]},
        {"schema": 1, "groups": [], "hosts": [{"id": "h1", "name": "PC", "group": "nope"}]},
        {
            "schema": 1,
            "groups": [{"id": "g1", "name": "A"}],
            "hosts": [{"id": "h1", "group": "g1", "tags": "x"}],
        },
    ],
)
def test_invalid_files_are_refused_with_a_message(tmp_path: Path, data: object) -> None:
    path = tmp_path / "hosts.json"
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        _write(path, data)
    with pytest.raises(HostListFormatError) as err:
        listfile.load(path)
    assert str(err.value)


def test_groups_nested_in_themselves_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    groups = [{"id": "a", "name": "A", "parent": "b"}, {"id": "b", "name": "B", "parent": "a"}]
    _write(path, {"schema": 1, "groups": groups})
    with pytest.raises(HostListFormatError):
        listfile.load(path)


def test_a_newer_schema_is_refused_not_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    _write(path, {**EXAMPLE, "schema": listfile.SCHEMA + 1})
    before = path.read_bytes()
    with pytest.raises(HostListTooNewError):
        listfile.load(path)
    assert path.read_bytes() == before


def test_save_refuses_when_someone_else_changed_the_file(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    _write(path, EXAMPLE)
    mine = listfile.load(path)
    _write(path, {**EXAMPLE, "hosts": []})  # a colleague saves in the meantime
    theirs = path.read_bytes()
    with pytest.raises(HostListChangedError):
        listfile.save(path, mine.hosts, expected=mine.stamp)
    assert path.read_bytes() == theirs


def test_save_as_new_file_refuses_to_replace_an_existing_one(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    _write(path, EXAMPLE)
    with pytest.raises(HostListChangedError):
        listfile.save(path, HostList(), expected=None)


def test_saving_leaves_no_temp_files_and_returns_the_new_stamp(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "hosts.json"
    stamp = listfile.save(path, HostList(), expected=None)
    assert [p.name for p in path.parent.iterdir()] == ["hosts.json"]
    assert listfile.stamp_of(path) == stamp
    listfile.save(path, HostList(), expected=stamp)  # saving again with the fresh stamp works


def test_can_write(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    assert listfile.can_write(path)  # new file in a writable folder
    _write(path, EXAMPLE)
    os.chmod(path, stat.S_IREAD)  # read-only attribute on Windows
    try:
        assert not listfile.can_write(path)
    finally:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    assert not listfile.can_write(tmp_path / "missing-folder" / "hosts.json")


def test_profiles_are_kept_and_written_only_when_set(tmp_path: Path) -> None:
    hl, group = HostList().add_group("Pis")
    hl = hl.set_group_profile(group.id, "realvnc-account")
    hl, pi = hl.add_host("PI-1", group.id, profile="realvnc-password")
    hl, plain = hl.add_host("PI-2", group.id)
    path = tmp_path / "list.json"
    listfile.save(path, hl, expected=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["groups"][0]["profile"] == "realvnc-account"
    hosts = {h["name"]: h for h in data["hosts"]}
    assert hosts["PI-1"]["profile"] == "realvnc-password" and "profile" not in hosts["PI-2"]
    assert listfile.load(path).hosts == hl
