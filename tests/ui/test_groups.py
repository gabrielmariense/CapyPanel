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
from capypanel.core.hosts import listfile, locations
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.ui.groups import (
    HOSTS_MIME,
    ROLE_ID,
    TREE_INDENT,
    ManageGroupsDialog,
    TreeMenu,
    fill_move_menu,
)
from capypanel.ui.list_workspace import workspace as workspace_module
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.menus import label


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
    doc = window.hosts.document
    assert doc is not None
    return next(g.id for g in doc.hosts.groups if g.name == name)


def test_groups_keep_the_list_s_order_and_all_computers_is_pinned_above(
    window: MainWindow,
) -> None:
    root = window.hosts.nav.groups.invisibleRootItem()
    assert _names(root) == ["Zebra wing (1)", "alpha wing (1)"]  # not sorted A–Z
    everything = window.hosts.nav.everything.topLevelItem(0)
    assert everything is not None and everything.text(0) == "All hosts (2)"
    assert window.hosts.nav.current_filter().kind == "all"
    window.hosts.nav.select_group(_id(window, "Lab"))
    assert not everything.isSelected()  # one pick at a time across both lists


def test_dragging_a_group_saves_the_new_place(window: MainWindow) -> None:
    tree = window.hosts.nav.groups
    root = tree.invisibleRootItem()
    alpha = root.takeChild(1)  # what a drag above "Zebra wing" leaves behind
    assert alpha is not None
    root.insertChild(0, alpha)
    tree.rearranged.emit()
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["alpha wing", "Zebra wing"]
    assert listfile.load(doc.path).hosts == doc.hosts  # saved


def test_hosts_dropped_on_a_group_move_there(window: MainWindow) -> None:
    doc = window.hosts.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.hosts.nav.groups.hosts_dropped.emit([z01], _id(window, "Lab"))
    doc = window.hosts.document
    assert doc is not None
    assert doc.hosts.host(z01).group == _id(window, "Lab")  # type: ignore[union-attr]


def test_read_only_lists_cant_be_rearranged(window: MainWindow, office: Path) -> None:
    office.chmod(0o444)
    try:
        window.hosts.open_list(office)
        assert window.hosts.nav.groups.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
        assert not window.hosts.table.dragEnabled()
    finally:
        office.chmod(0o666)


def test_manage_groups_moves_sorts_and_applies_on_ok(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = window.hosts.document
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
    window.hosts.commands.manage_groups.trigger()
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["alpha wing", "Zebra wing"]
    lab = doc.hosts.group(_id(window, "Lab"))
    assert lab is not None and lab.parent == _id(window, "alpha wing")  # nesting kept
    item = window.hosts.nav.groups.invisibleRootItem().child(0)
    assert item is not None and item.data(0, ROLE_ID) == _id(window, "alpha wing")
    assert item.child(0) is not None and item.isExpanded()


def test_removing_a_group_can_keep_what_is_inside(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[int, int]] = []

    def keep(_group_id: str, groups: int, hosts: int) -> tuple[str, str | None]:
        asked.append((groups, hosts))
        return ("move", None)  # the top level: its parent

    monkeypatch.setattr(window.hosts, "_ask_how_to_remove", keep)
    window.hosts.remove_group(_id(window, "alpha wing"))
    doc = window.hosts.document
    assert doc is not None
    assert asked == [(1, 1)]  # Lab, and L-01 inside it
    assert {g.name: g.parent for g in doc.hosts.groups} == {"Zebra wing": None, "Lab": None}
    assert {h.name for h in doc.hosts.hosts} == {"Z-01", "L-01"}


def test_removing_a_group_can_remove_everything(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window.hosts, "_ask_how_to_remove", lambda *_args: ("all", None))
    window.hosts.remove_group(_id(window, "alpha wing"))
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.groups] == ["Zebra wing"]
    assert [h.name for h in doc.hosts.hosts] == ["Z-01"]


def _texts(menu: QMenu) -> list[str]:
    return [label(a) for a in menu.actions() if a.text()]


def _choose(menu: QMenu, text: str) -> None:
    next(a for a in menu.actions() if a.text().strip() == text).trigger()  # past the indent


def test_move_to_offers_groups_itself_first_and_never_the_group_itself(
    window: MainWindow,
) -> None:
    doc = window.hosts.document
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
    tree = window.hosts.nav.groups
    alpha = tree.invisibleRootItem().child(1)
    lab = alpha.child(0) if alpha is not None else None
    assert lab is not None
    monkeypatch.setattr(workspace_module, "QMenu", Choosing)
    window.hosts._group_menu(tree.visualItemRect(lab).center())
    doc = window.hosts.document
    assert doc is not None
    assert doc.hosts.group(_id(window, "Lab")).parent == _id(window, "Zebra wing")  # type: ignore[union-attr]
    assert listfile.load(doc.path).hosts == doc.hosts  # saved
    picked = window.hosts.nav.selected_group_id()
    assert picked == _id(window, "Lab")  # still picked, in its new place
    window.close()


def test_right_clicking_the_groups_heading_offers_new_and_manage(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    class Recorded(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            seen.extend(_texts(self))

    monkeypatch.setattr(workspace_module, "QMenu", Recorded)
    window.hosts.nav.groups_heading.customContextMenuRequested.emit(QPoint(5, 5))
    assert seen == ["Add &group…", "&Manage groups…"]


def test_add_group_from_the_heading_goes_to_the_top_level_even_with_a_group_picked(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Adding(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            _choose(self, "Add &group…")

    monkeypatch.setattr(workspace_module, "QMenu", Adding)
    monkeypatch.setattr(workspace_module.QInputDialog, "getText", lambda *_a, **_k: ("Annex", True))
    window.hosts.nav.select_group(_id(window, "Lab"))
    window.hosts.nav.groups_heading.customContextMenuRequested.emit(QPoint(5, 5))
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Annex"]


def test_a_group_dropped_on_the_groups_heading_goes_to_the_top_level(window: MainWindow) -> None:
    window.hosts.nav.groups_heading.group_dropped.emit(_id(window, "Lab"))
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Lab"]


def test_manage_groups_move_to_changes_only_its_working_copy(window: MainWindow) -> None:
    doc = window.hosts.document
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
    tree = window.hosts.nav.groups
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
    window.hosts.nav.groups_heading.dropEvent(drop)
    doc = window.hosts.document
    assert doc is not None
    assert doc.hosts.group(_id(window, "Lab")).parent is None  # type: ignore[union-attr]
    assert drop.dropAction() == Qt.DropAction.CopyAction  # the tree doesn't drop its own row


def test_the_plus_by_the_heading_adds_at_the_top_level(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace_module.QInputDialog, "getText", lambda *_a, **_k: ("Annex", True))
    window.hosts.nav.select_group(_id(window, "Lab"))
    window.hosts.nav.add_group_button.click()
    doc = window.hosts.document
    assert doc is not None
    assert [g.name for g in doc.hosts.children(None)] == ["Zebra wing", "alpha wing", "Annex"]


def test_a_group_closed_by_hand_stays_closed_after_a_change(window: MainWindow) -> None:
    alpha = window.hosts.nav.groups.invisibleRootItem().child(1)
    assert alpha is not None
    alpha.setExpanded(False)
    doc = window.hosts.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.hosts.move_items([z01], _id(window, "Lab"))  # any change rebuilds the tree
    alpha = window.hosts.nav.groups.invisibleRootItem().child(1)
    assert alpha is not None and alpha.childCount() and not alpha.isExpanded()


def test_hosts_with_no_group_show_under_no_group(window: MainWindow) -> None:
    nav = window.hosts.nav
    # Always there, so the first host can be dragged onto it too.
    assert not nav._no_group_item.isHidden() and nav._no_group_item.text(0) == "No group (0)"
    doc = window.hosts.document
    assert doc is not None
    z01 = next(h.id for h in doc.hosts.hosts if h.name == "Z-01")
    window.hosts.nav.everything.hosts_dropped.emit([z01], NO_GROUP)  # dragged onto "No group"
    doc = window.hosts.document
    assert doc is not None and doc.hosts.host(z01).group == NO_GROUP  # type: ignore[union-attr]
    assert nav._no_group_item.text(0) == "No group (1)"
    window.hosts.nav.select_group(NO_GROUP)
    window.hosts.table.select_ids([z01])
    assert nav.current_filter().kind == "nogroup"
    assert [window.hosts.table.topLevelItem(0).text(0)] == ["Z-01"]  # type: ignore[union-attr]
    assert window.hosts.details.shown_value("group") == "No group"


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
    doc = window.hosts.document
    assert doc is not None
    l01 = next(h.id for h in doc.hosts.hosts if h.name == "L-01")
    window.hosts.nav.select_group(doc.hosts.host(l01).group)  # type: ignore[union-attr]
    window.hosts.table.select_ids([l01])
    item = window.hosts.table.topLevelItem(0)
    assert item is not None
    monkeypatch.setattr(workspace_module, "QMenu", Choosing)
    window.hosts._item_menu(window.hosts.table.visualItemRect(item).center())
    doc = window.hosts.document
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

    monkeypatch.setattr(workspace_module.QMessageBox, "exec", pick_zebra)
    window.hosts.remove_group(_id(window, "alpha wing"))
    doc = window.hosts.document
    assert doc is not None
    lab = doc.hosts.group(_id(window, "Lab"))
    assert lab is not None and lab.parent == _id(window, "Zebra wing")


def test_hosts_dragged_over_a_group_light_it_without_leaving_where_they_are(
    window: MainWindow,
) -> None:
    window.show()
    QApplication.processEvents()
    tree = window.hosts.nav.groups
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
    assert window.hosts.nav.current_filter().kind == "all"  # but the table still shows all hosts
    tree.dragLeaveEvent(QDragLeaveEvent())
    assert not zebra.isSelected() and window.hosts.nav.current_filter().kind == "all"
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
    doc = window.hosts.document
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


def test_manage_groups_draws_tree_lines(window: MainWindow) -> None:
    doc = window.hosts.document
    assert doc is not None
    dialog = ManageGroupsDialog(None, doc.hosts)
    assert dialog.tree.tree_lines and not window.hosts.nav.groups.tree_lines  # only in this window
    dialog.show()
    QApplication.processEvents()
    assert not dialog.tree.viewport().grab().isNull()  # draws in any theme without failing
    dialog.close()


def _reopened(window: MainWindow, tmp_path: Path) -> MainWindow:
    """The app started again, with the settings the first window saved as it closed."""
    window.close()
    again = MainWindow(settings.resolve_paths(tmp_path), window.prefs)
    return again


def test_a_list_opens_on_all_hosts_where_it_was_left_or_its_chosen_group(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = _id(window, "Lab")
    window.hosts.nav.select_group(lab)
    again = _reopened(window, tmp_path)
    assert again.hosts.nav.current_filter().kind == "all"  # the default: All hosts
    path = again.hosts.document.path  # type: ignore[union-attr]
    locations.set_list_view(again.hosts.prefs, path, locations.ListView(show=locations.SHOW_LAST))
    again.hosts.nav.select_group(lab)
    third = _reopened(again, tmp_path)
    assert third.hosts.nav.selected_group_id() == lab  # where it was left
    assert [third.hosts.table.topLevelItem(0).text(0)] == ["L-01"]  # type: ignore[union-attr]

    class Ticking(QMenu):
        def exec(self, *_args: Any) -> None:  # type: ignore[override]
            _choose(self, "Show this group &first")

    monkeypatch.setattr(workspace_module, "QMenu", Ticking)
    zebra = _id(third, "Zebra wing")
    third.show()
    QApplication.processEvents()
    item = next(i for i in _walk_items(third.hosts.nav.groups) if i.data(0, ROLE_ID) == zebra)
    third.hosts._group_menu(third.hosts.nav.groups.visualItemRect(item).center())
    third.hosts.nav.select_group(lab)  # left on Lab, but Zebra wing is the chosen one
    fourth = _reopened(third, tmp_path)
    assert fourth.hosts.nav.selected_group_id() == zebra
    fourth.close()


def test_settings_chooses_what_the_open_list_shows_first(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    page = dialog.hosts
    assert page.show_first.text() == "All hosts"
    menu = page.show_first.menu()
    assert menu is not None
    menu.aboutToShow.emit()  # filled as it opens
    texts = [label(a) for a in menu.actions() if a.text()]
    assert texts == ["All hosts", "Where I left off", "A chosen &group"]
    chosen = menu.actions()[2].menu()
    assert isinstance(chosen, QMenu)
    # The groups as a tree, "No group" first, as in Move to.
    assert [a.text().strip() for a in chosen.actions() if a.text()] == [
        "No group", "Zebra wing", "alpha wing", "Lab"
    ]  # fmt: skip
    _choose(chosen, "alpha wing")
    assert page.show_first.text() == "Group: alpha wing"
    doc = window.hosts.document
    assert doc is not None
    view = locations.list_view(window.hosts.prefs, doc.path)
    assert (view.show, view.group) == (locations.SHOW_GROUP, _id(window, "alpha wing"))
