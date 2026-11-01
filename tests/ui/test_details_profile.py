import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    paths.profiles_dir.mkdir(parents=True)
    for pid, name in (("offices", "Offices"), ("pis", "Pis")):
        data = {"schema": 1, "id": pid, "name": name, "tool": "ultravnc", "login": "account",
                "options": []}  # fmt: skip
        (paths.profiles_dir / f"{pid}.json").write_text(json.dumps(data), encoding="utf-8")
    hl, offices = HostList().add_group("Offices")
    hl = hl.set_group_profile(offices.id, "offices")
    hl, _a = hl.add_host("PC-A", offices.id, address="192.0.2.10")
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    yield CapyWindow(paths, {"schema": 1, "recent_lists": [str(path)]})


def _pick(win: CapyWindow) -> str:
    doc = win.hosts.document
    assert doc is not None
    host_id = doc.hosts.hosts[0].id
    win.hosts.table.select_ids([host_id])
    return host_id


def test_the_profile_in_details_has_an_arrow_with_the_group_s_choices(window: CapyWindow) -> None:
    hosts = window.hosts
    host_id = _pick(window)
    assert hosts.details.shown_value("profile") == "Offices"  # from its group
    menu = hosts.details.profile_menu
    menu.aboutToShow.emit()  # what opening it by the arrow does
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[0] == "From group “Offices”: Offices"  # follow the group, checked
    assert menu.actions()[0].isChecked() and "Pis" in texts
    [pis] = [a for a in menu.actions() if a.text() == "Pis"]
    pis.trigger()
    doc = hosts.document
    assert doc is not None and doc.hosts.host(host_id).profile == "pis"  # type: ignore[union-attr]
    assert hosts.details.shown_value("profile") == "Pis"
    menu.aboutToShow.emit()
    [follow] = [a for a in menu.actions() if a.text().startswith("From group")]
    follow.trigger()  # back to following the group
    doc = hosts.document
    assert doc is not None and doc.hosts.host(host_id).profile == ""  # type: ignore[union-attr]
