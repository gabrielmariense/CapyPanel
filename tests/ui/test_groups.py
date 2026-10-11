from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QMenu,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
)

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.ui.groups import (
    HOSTS_MIME,
    ROLE_ID,
    TREE_INDENT,
    ManageGroupsDialog,
    TreeMenu,
    fill_move_menu,
)
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
    tops = dialog.tree.invisibleRootItem()
    assert _names(tops) == ["Groups"]  # everything hangs from it; drop a group on it to un-nest
    root = dialog.tree.top()
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
        alpha = d.tree.top().child(1)
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

    def keep(_group_id: str, groups: int, hosts: int) -> tuple[str, str | None]:
        asked.append((groups, hosts))
        return ("move", None)  # the top level: its parent

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
    monkeypatch.setattr(window, "_ask_how_to_remove", lambda *_args: ("all", None))
    window.remove_group(_id(window, "alpha wing"))
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.groups] == ["Zebra wing"]
    assert [h.name for h in doc.hosts.hosts] == ["Z-01"]


def _texts(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def _choose(menu: QMenu, text: str) -> None:
    next(a for a in menu.actions() if a.text().strip() == text).trigger()  # past the indent


def test_move_to_offers_groups_itself_first_and_never_the_group_itself(
    window: MainWindow,
) -> None:
    doc = window.document
    assert doc is not None
    chosen: list[str | None] = []
    menu = TreeMenu()
    fill_move_menu(menu, doc.hosts, _id(window, "alpha wing"), chosen.append)
    # "Groups": directly under the pane's heading, in no other group.
    assert _texts(menu) == ["Groups", TREE_INDENT + "Zebra wing"]  # not alpha wing, nor its Lab
    assert menu.actions()[0].isChecked()  # where it is now
    assert menu.marked is menu.actions()[0]  # tinted too, easy to spot in a long menu
    _choose(menu, "Groups")
    assert chosen == []  # already there
    _choose(menu, "Zebra wing")
    assert chosen == [_id(window, "Zebra wing")]
    menu = TreeMenu()
    fill_move_menu(menu, doc.hosts, _id(window, "Zebra wing"), chosen.append)
    assert _texts(menu) == ["Groups", TREE_INDENT + "alpha wing", TREE_INDENT * 2 + "Lab"]


def test_move_to_draws_the_tree_s_lines(qapp: QApplication) -> None:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    hl, _ = hl.add_group("Payroll", parent=finance.id)
    hl, _ = hl.add_group("Reports", parent=hq.id)
    hl, annex = hl.add_group("Annex")
    menu = TreeMenu()
    fill_move_menu(menu, hl, annex.id, lambda _p: None)
    rows = {a.text().strip(): menu.branches(a) for a in menu.actions() if a.text()}
    # Everything hangs from "Groups". Finance's line carries on past Payroll down to Reports,
    # the last one under Headquarters.
    assert rows == {
        "Groups": (),
        "Headquarters": (True,),
        "Finance": (True, False),
        "Payroll": (True, False, True),
        "Reports": (True, True),
    }
    menu.adjustSize()
    assert not menu.grab().isNull()  # draws its lines in any theme without failing


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


def test_add_group_from_the_heading_goes_to_the_top_level_even_with_a_group_picked(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Adding(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            _choose(self, "Add &group…")

    monkeypatch.setattr(window_module, "QMenu", Adding)
    monkeypatch.setattr(window_module.QInputDialog, "getText", lambda *_a, **_k: ("Annex", True))
    window.nav.select_group(_id(window, "Lab"))
    window.nav.groups_heading.customContextMenuRequested.emit(QPoint(5, 5))
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Annex"]


def test_a_group_dropped_on_the_groups_heading_goes_to_the_top_level(window: MainWindow) -> None:
    window.nav.groups_heading.group_dropped.emit(_id(window, "Lab"))
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Lab"]


def test_manage_groups_move_to_changes_only_its_working_copy(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None
    dialog = ManageGroupsDialog(None, doc.hosts)
    root = dialog.tree.top()
    alpha = root.child(1)
    assert alpha is not None
    lab = alpha.child(0)
    assert lab is not None
    dialog.tree.setCurrentItem(lab)

    _choose(dialog.move_menu(), "Groups")
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


def test_the_plus_by_the_heading_adds_at_the_top_level(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window_module.QInputDialog, "getText", lambda *_a, **_k: ("Annex", True))
    window.nav.select_group(_id(window, "Lab"))
    window.nav.add_group_button.click()
    doc = window.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Annex"]


def test_a_group_closed_by_hand_stays_closed_after_a_change(window: MainWindow) -> None:
    alpha = window.nav.groups.invisibleRootItem().child(1)
    assert alpha is not None
    alpha.setExpanded(False)
    doc = window.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.move_hosts([z01], _id(window, "Lab"))  # any change rebuilds the tree
    alpha = window.nav.groups.invisibleRootItem().child(1)
    assert alpha is not None and alpha.childCount() and not alpha.isExpanded()


def test_hosts_with_no_group_show_under_no_group(window: MainWindow) -> None:
    nav = window.nav
    # Always there, so the first host can be dragged onto it too.
    assert not nav._no_group_item.isHidden() and nav._no_group_item.text(0) == "No group (0)"
    doc = window.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.nav.everything.hosts_dropped.emit([z01], NO_GROUP)  # dragged onto "No group"
    doc = window.document
    assert doc is not None and doc.hosts.host(z01).group == NO_GROUP  # type: ignore[union-attr]
    assert nav._no_group_item.text(0) == "No group (1)"
    window.show_in_group(z01)
    assert nav.current_filter().kind == "nogroup"
    assert [window.table.topLevelItem(0).text(0)] == ["Z-01"]  # type: ignore[union-attr]
    assert window.details.shown_value("group") == "No group"


def test_hosts_right_click_move_to_any_group_or_none(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Choosing(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            move = next(a for a in self.actions() if a.text() == "&Move to").menu()
            assert isinstance(move, QMenu)
            texts = [a.text().strip() for a in move.actions() if a.text()]
            assert texts == ["No group", "Zebra wing", "alpha wing", "Lab"]
            _choose(move, "No group")

    window.show()
    QApplication.processEvents()
    doc = window.document
    assert doc is not None
    l01 = next(h.id for h in doc.hosts.hosts if h.name == "L-01")
    window.show_in_group(l01)
    item = window.table.topLevelItem(0)
    assert item is not None
    monkeypatch.setattr(window_module, "QMenu", Choosing)
    window._host_menu(window.table.visualItemRect(item).center())
    doc = window.document
    assert doc is not None and doc.hosts.host(l01).group == NO_GROUP  # type: ignore[union-attr]
    window.close()


def test_removing_a_group_offers_where_its_contents_go(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    def pick_zebra(box: QMessageBox) -> int:
        move = next(b for b in box.buttons() if b.text() == "&Move them to")
        menu = move.menu()  # type: ignore[attr-defined]
        assert isinstance(menu, QMenu)
        texts = [a.text().strip() for a in menu.actions() if a.text()]
        # The hosts' own Move to, without alpha wing itself and its Lab.
        assert texts == ["No group", "Zebra wing"]
        assert menu.actions()[0].isChecked()  # its parent: the top level
        _choose(menu, "Zebra wing")
        return 0

    monkeypatch.setattr(window_module.QMessageBox, "exec", pick_zebra)
    window.remove_group(_id(window, "alpha wing"))
    doc = window.document
    assert doc is not None
    lab = doc.hosts.group(_id(window, "Lab"))
    assert lab is not None and lab.parent == _id(window, "Zebra wing")


def test_hosts_dragged_over_a_group_light_it_without_leaving_where_they_are(
    window: MainWindow,
) -> None:
    window.show()
    QApplication.processEvents()
    tree = window.nav.groups
    zebra = next(i for i in _walk_items(tree) if i.data(0, ROLE_ID) == _id(window, "Zebra wing"))
    data = QMimeData()
    data.setData(HOSTS_MIME, b"some-host")
    point = QPointF(tree.visualItemRect(zebra).center())
    actions = Qt.DropAction.MoveAction
    tree.dragMoveEvent(
        QDragMoveEvent(point.toPoint(), actions, data, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    )  # fmt: skip
    assert zebra.isSelected()  # shows where they'd go
    assert window.nav.current_filter().kind == "all"  # but the table still shows all hosts
    tree.dragLeaveEvent(QDragLeaveEvent())
    assert not zebra.isSelected() and window.nav.current_filter().kind == "all"
    window.close()


def _walk_items(tree: QTreeWidget) -> list[QTreeWidgetItem]:
    found: list[QTreeWidgetItem] = []

    def walk(item: QTreeWidgetItem) -> None:
        for index in range(item.childCount()):
            child = item.child(index)
            if child is not None:
                found.append(child)
                walk(child)

    walk(tree.invisibleRootItem())
    return found


def test_a_group_dropped_below_the_last_row_goes_under_groups(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None
    dialog = ManageGroupsDialog(None, doc.hosts)
    dialog.resize(460, 480)
    dialog.show()
    QApplication.processEvents()
    tree = dialog.tree
    lab = next(i for i in _walk_items(tree) if i.data(0, ROLE_ID) == _id(window, "Lab"))
    below = QPointF(20, tree.viewport().height() - 5)  # empty space under the rows
    drop = QDropEvent(below, Qt.DropAction.MoveAction, tree.mimeData([lab]),
                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)  # fmt: skip
    # Qt moves the group as if it were dropped onto "Groups" (a real drag needs a real mouse).
    onto = tree.onto_root(drop)
    assert tree.itemAt(onto.position().toPoint()) is tree.top()
    assert onto.mimeData() is drop.mimeData()
    dialog.close()
