import json
from pathlib import Path

import pytest

from capypanel.core.hosts import listfile
from capypanel.core.hosts.document import OpenList, ReadOnlyListError
from capypanel.core.hosts.listfile import HostListChangedError


def test_new_list_starts_with_one_group(tmp_path: Path) -> None:
    doc = OpenList.create(tmp_path / "hosts.json")
    assert [g.name for g in doc.hosts.groups] == ["Hosts"]
    assert listfile.load(doc.path).hosts == doc.hosts


def test_create_never_replaces_a_file_unless_asked(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    doc = OpenList.create(path)
    doc.commit(doc.hosts.add_host("PC1", doc.hosts.groups[0].id)[0])
    with pytest.raises(HostListChangedError):
        OpenList.create(path)
    assert OpenList.create(path, replace_existing=True).hosts.hosts == ()


def test_commit_saves_and_keeps_the_new_stamp(tmp_path: Path) -> None:
    doc = OpenList.create(tmp_path / "hosts.json")
    for name in ("PC1", "PC2"):
        doc.commit(doc.hosts.add_host(name, doc.hosts.groups[0].id)[0])
    assert [h.name for h in OpenList.open(doc.path).hosts.hosts] == ["PC1", "PC2"]


def test_conflict_leaves_both_sides_intact(tmp_path: Path) -> None:
    mine = OpenList.create(tmp_path / "hosts.json")
    theirs = OpenList.open(mine.path)
    theirs.commit(theirs.hosts.add_host("THEIRS", theirs.hosts.groups[0].id)[0])
    before = mine.hosts
    my_edit = mine.hosts.add_host("MINE", mine.hosts.groups[0].id)[0]
    with pytest.raises(HostListChangedError):
        mine.commit(my_edit)
    assert mine.hosts == before
    copy = OpenList.save_as(tmp_path / "mine.json", my_edit)
    assert [h.name for h in copy.hosts.hosts] == ["MINE"]
    mine.reload()
    assert [h.name for h in mine.hosts.hosts] == ["THEIRS"]


def test_read_only_lists_refuse_edits(tmp_path: Path) -> None:
    path = tmp_path / "hosts.json"
    OpenList.create(path)
    doc = OpenList.open(path, read_only=True)
    with pytest.raises(ReadOnlyListError):
        doc.commit(doc.hosts.add_host("PC1", doc.hosts.groups[0].id)[0])
    assert json.loads(path.read_text(encoding="utf-8"))["hosts"] == []
