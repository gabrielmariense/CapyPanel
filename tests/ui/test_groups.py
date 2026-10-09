from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QApplication, QDialog, QMenu, QTreeWidgetItem

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui.groups import MENU_INDENT, ROLE_ID, ManageGroupsDialog, fill_move_menu
from capypanel.ui.main_window import window as window_module
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def office(tmp_path: Path) -> Path:
    # Made in this order on purpose: not alphabetical.
    hl, zebra = HostList().add_group("Zebra wing")
    hl, alpha = hl.add_group("alpha wing")
    hl, lab = hl.add_group("Lab", parent=alpha.id)
    hl, _ = hl.add_host("Z-01", zebra.id)
    hl, _ = hl.add_host("L-01", lab.id)
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    return path


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path, office: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(office)]})
    yield win
    win.close()


def _names(item: QTreeWidgetItem) -> list[str]:
    return [item.child(i).text(0) for i in range(item.childCount())]  # type: ignore[union-attr]


def _id(window: MainWindow, name: str) -> str:
    doc = window.document
    assert doc is not None
    return next(g.id for g in doc.hosts.groups if g.name == name)


def test_groups_keep_the_list_s_order_and_all_computers_is_pinned_above(
    window: MainWindow,
) -> None:
    root = window.nav.groups.invisibleRootItem()
    assert _names(root) == ["Zebra wing (1)", "alpha wing (1)"]  # not sorted A–Z
    everything = window.nav.everything.topLevelItem(0)
    assert everything is not None and everything.text(0) == "All hosts (2)"
    assert window.nav.current_filter().kind == "all"
    window.nav.select_group(_id(window, "Lab"))
    assert not everything.isSelected()  # one pick at a time across both lists


def test_dragging_a_group_saves_the_new_place(window: MainWindow) -> None:
    tree = window.nav.groups
    root = tree.invisibleRootItem()
    alpha = root.takeChild(1)  # what a drag above "Zebra wing" leaves behind
    assert alpha is not None
    root.insertChild(0, alpha)
    tree.rearranged.emit()
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["alpha wing", "Zebra wing"]
    assert listfile.load(doc.path).hosts == doc.hosts  # saved


def test_hosts_dropped_on_a_group_move_there(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.nav.groups.hosts_dropped.emit([z01], _id(window, "Lab"))
    doc = window.document
    assert doc is not None
    assert doc.hosts.host(z01).group == _id(window, "Lab")  # type: ignore[union-attr]


def test_read_only_lists_cant_be_rearranged(window: MainWindow, office: Path) -> None:
    office.chmod(0o444)
    try:
        window.open_list(office)
        assert window.nav.groups.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
        assert not window.table.dragEnabled()
    finally:
        office.chmod(0o666)


def test_manage_groups_moves_sorts_and_applies_on_ok(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = window.document
    assert doc is not None
    dialog = ManageGroupsDialog(None, doc.hosts)
    root = dialog.tree.invisibleRootItem()
    assert _names(root) == ["Zebra wing", "alpha wing"]
    dialog.sort_button.click()
    assert _names(root) == ["alpha wing", "Zebra wing"]  # A–Z ignores upper and lower case
    alpha = root.child(0)
    assert alpha is not None and alpha.isExpanded()  # its subgroups stay in view
    zebra = root.child(1)
    assert zebra is not None
    dialog.tree.setCurrentItem(zebra)
    assert dialog.up_button.isEnabled() and not dialog.down_button.isEnabled()
    dialog.up_button.click()
    assert _names(root) == ["Zebra wing", "alpha wing"]

    def use(d: ManageGroupsDialog) -> int:
        alpha = d.tree.invisibleRootItem().child(1)
        assert alpha is not None
        d.tree.setCurrentItem(alpha)
        d.up_button.click()  # alpha wing first
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ManageGroupsDialog, "exec", use)
    window.commands.manage_groups.trigger()
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["alpha wing", "Zebra wing"]
    lab = doc.hosts.group(_id(window, "Lab"))
    assert lab is not None and lab.parent == _id(window, "alpha wing")  # nesting kept
    item = window.nav.groups.invisibleRootItem().child(0)
    assert item is not None and item.data(0, ROLE_ID) == _id(window, "alpha wing")
    assert item.child(0) is not None and item.isExpanded()


def test_removing_a_group_can_keep_what_is_inside(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[int, int]] = []

    def keep(_group_id: str, groups: int, hosts: int) -> str:
        asked.append((groups, hosts))
        return "keep"

    monkeypatch.setattr(window, "_ask_how_to_remove", keep)
    window.remove_group(_id(window, "alpha wing"))
    doc = window.document
    assert doc is not None
    assert asked == [(1, 1)]  # Lab, and L-01 inside it
    assert {g.name: g.parent for g in doc.hosts.groups} == {"Zebra wing": None, "Lab": None}
    assert {h.name for h in doc.hosts.hosts} == {"Z-01", "L-01"}


def test_removing_a_group_can_remove_everything(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window, "_ask_how_to_remove", lambda *_args: "all")
    window.remove_group(_id(window, "alpha wing"))
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.groups] == ["Zebra wing"]
    assert [h.name for h in doc.hosts.hosts] == ["Z-01"]


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def _choose(menu: QMenu, text: str) -> None:
    next(a for a in menu.actions() if a.text() == text).trigger()


def test_move_to_offers_the_top_level_first_and_never_the_group_itself(
    window: MainWindow,
) -> None:
    doc = window.document
    assert doc is not None
    chosen: list[str | None] = []
    menu = QMenu()
    fill_move_menu(menu, doc.hosts, _id(window, "alpha wing"), chosen.append)
    assert _texts(menu) == ["Top level", "Zebra wing"]  # not alpha wing, nor its Lab
    assert menu.actions()[0].isChecked()  # where it is now
    _choose(menu, "Top level")
    assert chosen == []  # already there
    _choose(menu, "Zebra wing")
    assert chosen == [_id(window, "Zebra wing")]
    menu = QMenu()
    fill_move_menu(menu, doc.hosts, _id(window, "Zebra wing"), chosen.append)
    assert _texts(menu) == ["Top level", "alpha wing", MENU_INDENT + "Lab"]  # nesting shows


def test_right_click_move_to_puts_the_group_inside_another(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Choosing(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            move = next(a for a in self.actions() if a.text() == "&Move to").menu()
            assert isinstance(move, QMenu)
            _choose(move, "Zebra wing")

    window.show()
    QApplication.processEvents()
    tree = window.nav.groups
    alpha = tree.invisibleRootItem().child(1)
    lab = alpha.child(0) if alpha is not None else None
    assert lab is not None
    monkeypatch.setattr(window_module, "QMenu", Choosing)
    window._group_menu(tree.visualItemRect(lab).center())
    doc = window.document
    assert doc is not None
    assert doc.hosts.group(_id(window, "Lab")).parent == _id(window, "Zebra wing")  # type: ignore[union-attr]
    assert listfile.load(doc.path).hosts == doc.hosts  # saved
    assert window.nav.selected_group_id() == _id(window, "Lab")  # still picked, in its new place
    window.close()


def test_right_clicking_the_groups_heading_offers_new_and_manage(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    class Recorded(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            seen.extend(_texts(self))

    monkeypatch.setattr(window_module, "QMenu", Recorded)
    window.nav.groups_heading.customContextMenuRequested.emit(QPoint(5, 5))
    assert seen == ["Add &group…", "&Manage groups…"]


def test_a_group_dropped_on_the_groups_heading_goes_to_the_top_level(window: MainWindow) -> None:
    window.nav.groups_heading.group_dropped.emit(_id(window, "Lab"))
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Lab"]


def test_manage_groups_move_to_changes_only_its_working_copy(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None
    dialog = ManageGroupsDialog(None, doc.hosts)
    root = dialog.tree.invisibleRootItem()
    alpha = root.child(1)
    assert alpha is not None
    lab = alpha.child(0)
    assert lab is not None
    dialog.tree.setCurrentItem(lab)

    _choose(dialog.move_menu(), "Top level")
    assert _names(root) == ["Zebra wing", "alpha wing", "Lab"]
    assert dict(dialog.order())[_id(window, "Lab")] is None
    saved = doc.hosts.group(_id(window, "Lab"))
    assert saved is not None and saved.parent is not None  # nothing saved before OK


def test_the_tree_s_drag_data_drops_on_the_heading(window: MainWindow) -> None:
    tree = window.nav.groups
    alpha = tree.invisibleRootItem().child(1)
    lab = alpha.child(0) if alpha is not None else None
    assert lab is not None
    data = tree.mimeData([lab])  # what dragging "Lab" carries
    drop = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.MoveAction | Qt.DropAction.CopyAction,  # what the tree offers
        data,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.nav.groups_heading.dropEvent(drop)
    doc = window.document
    assert doc is not None
    assert doc.hosts.group(_id(window, "Lab")).parent is None  # type: ignore[union-attr]
    assert drop.dropAction() == Qt.DropAction.CopyAction  # the tree doesn't drop its own row
