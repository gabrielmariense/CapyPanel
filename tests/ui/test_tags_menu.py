from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, ward = HostList().add_group("Ward A")
    hl, _a = hl.add_host("PC-1", ward.id, address="192.0.2.11", tags=["kiosk", "watch"])
    hl, _b = hl.add_host("PC-2", ward.id, address="192.0.2.12", tags=["kiosk"])
    hl, _c = hl.add_host("PC-3", ward.id, address="192.0.2.13", tags=["Lab"])
    path = tmp_path / "wards.json"
    listfile.save(path, hl, expected=None)
    yield CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(path)]})


def _select(win: CapyWindow, *names: str) -> list[str]:
    doc = win.hosts.document
    ids = [h.id for h in doc.hosts.hosts if h.name in names] if doc else []
    win.hosts.table.select_ids(ids)
    return ids


def _tags_menu(win: CapyWindow) -> QMenu:
    menu = QMenu(win)  # kept by the window, or its submenu goes with it
    win.hosts.fill_item_menu(menu, win.hosts.selected_items())
    titles = [a.text() for a in menu.actions()]
    at = titles.index("&Move to")
    tags = menu.actions()[at + 1].menu()  # right after Move to
    assert isinstance(tags, QMenu) and tags.title() == "&Tags"
    return tags


def _tags(win: CapyWindow, name: str) -> tuple[str, ...]:
    doc = win.hosts.document
    assert doc is not None
    return next(h.tags for h in doc.hosts.hosts if h.name == name)


def test_the_tags_submenu_ticks_shared_tags_and_counts_the_others(window: CapyWindow) -> None:
    _select(window, "PC-1", "PC-2")
    tags = _tags_menu(window)
    entries = [(a.text(), a.isChecked()) for a in tags.actions() if not a.isSeparator()]
    assert entries == [
        ("kiosk", True), ("Lab", False), ("watch (1 of 2)", False), ("&New tag…", False),
    ]  # fmt: skip
    assert tags.actions()[-2].isSeparator()
    [watch] = [a for a in tags.actions() if a.text().startswith("watch")]
    watch.trigger()  # only some had it: now both do
    assert _tags(window, "PC-2") == ("kiosk", "watch")
    [kiosk] = [a for a in _tags_menu(window).actions() if a.text() == "kiosk"]
    kiosk.trigger()  # both had it: taken from both
    assert _tags(window, "PC-1") == ("watch",) and _tags(window, "PC-2") == ("watch",)
    assert _tags(window, "PC-3") == ("Lab",)  # not selected: untouched


def test_a_new_tag_goes_to_every_selected_item_in_the_list_s_spelling(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _select(window, "PC-1", "PC-2")
    typed = iter([("  lab ", True), ("2nd floor", True), ("ignored", False)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(typed))
    new = _tags_menu(window).actions()[-1]
    new.trigger()
    assert _tags(window, "PC-2") == ("kiosk", "Lab")  # the list already spells it "Lab"
    _tags_menu(window).actions()[-1].trigger()
    assert _tags(window, "PC-1")[-1] == "2nd floor"
    _tags_menu(window).actions()[-1].trigger()  # cancelled: nothing changes
    assert _tags(window, "PC-1") == ("kiosk", "watch", "Lab", "2nd floor")
