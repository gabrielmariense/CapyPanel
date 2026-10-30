import json
import os
import stat
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSplitter, QWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.locations import recent_lists
from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.ui.hosts import HostDialog, group_choices
from capypanel.ui.hosts_tool import tool as hosts_module
from capypanel.ui.hosts_tool.table import HostTable
from capypanel.ui.list_workspace import workspace as workspace_module


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


@pytest.fixture
def office(tmp_path: Path) -> Path:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    hl, _ = hl.add_host("HQ-01", hq.id, address="10.0.0.1", tags=["kiosk"])
    hl, _ = hl.add_host("FIN-01", finance.id, tags=["floor-3"])
    hl, _ = hl.add_host("FIN-02", finance.id, tags=["floor-3", "kiosk"], notes="Reception")
    path = tmp_path / "office.json"
    listfile.save(path, hl, expected=None)
    return path


@pytest.fixture
def window(qapp: QApplication, paths: settings.Paths) -> Iterator[CapyWindow]:
    win = CapyWindow(paths, {"schema": 1})
    yield win
    win.close()


def test_add_host_keeps_every_host_of_a_list_with_no_groups(
    window: CapyWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hl, _ = HostList().add_host("LOOSE-01", NO_GROUP)
    hl, _ = hl.add_host("LOOSE-02", NO_GROUP)
    path = tmp_path / "loose.json"
    listfile.save(path, hl, expected=None)
    window.hosts.open_list(path)

    def fill(dialog: object) -> QDialog.DialogCode:
        assert isinstance(dialog, HostDialog)
        dialog.name.setText("NEW-01")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(hosts_module, "run_modal", fill)
    window.hosts.commands.add_host.trigger()
    names = [h.name for h in listfile.load(path).hosts.hosts]
    assert sorted(names) == ["LOOSE-01", "LOOSE-02", "NEW-01"]  # nothing lost


def test_another_tool_s_list_isn_t_opened_as_a_host_list(
    window: CapyWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "printers.json"
    listfile.save(path, HostList().add_group("Lab")[0], expected=None, kind="printers")
    shown: list[str] = []
    monkeypatch.setattr(
        workspace_module.QMessageBox, "warning", lambda _p, _t, text: shown.append(text)
    )
    before = window.hosts.document
    assert not window.hosts.open_list(path)
    assert shown == [f"“{path}” isn't a host list."] and window.hosts.document is before
    doc = window.hosts.document
    assert doc is not None and listfile.load(doc.path).kind == "hosts"  # saved with its kind


def _table_names(win: CapyWindow) -> set[str]:
    items = (win.hosts.table.topLevelItem(i) for i in range(win.hosts.table.topLevelItemCount()))
    return {item.text(0) for item in items if item is not None}


def test_first_start_creates_the_personal_list_with_a_hosts_group(window: CapyWindow) -> None:
    doc = window.hosts.document
    assert doc is not None and doc.path.name == "default.json" and doc.path.exists()
    assert [g.name for g in doc.hosts.groups] == ["Default group"]
    assert window.windowTitle().startswith("Default —")
    assert [a.text() for a in window.menuBar().actions()] == [
        "&File",
        "&View",
        "&Help",
    ]
    assert window.hosts.commands.add_host.isEnabled()


def test_opening_a_list_shows_its_hosts_and_remembers_it(window: CapyWindow, office: Path) -> None:
    assert window.hosts.open_list(office)
    assert _table_names(window) == {"HQ-01", "FIN-01", "FIN-02"}
    assert recent_lists(window.hosts.prefs)[0] == office


def test_picking_a_group_or_tag_filters_the_table(window: CapyWindow, office: Path) -> None:
    window.hosts.open_list(office)
    tree = window.hosts.nav.groups
    flags = Qt.MatchFlag.MatchStartsWith | Qt.MatchFlag.MatchRecursive
    [finance] = tree.findItems("Finance", flags)
    tree.setCurrentItem(finance)
    assert _table_names(window) == {"FIN-01", "FIN-02"}
    [kiosk] = window.hosts.nav.tags.findItems("kiosk", Qt.MatchFlag.MatchStartsWith)
    window.hosts.nav.tags.setCurrentItem(kiosk)  # narrows the group picked
    assert _table_names(window) == {"FIN-02"}
    [everything] = window.hosts.nav.everything.findItems("All hosts", Qt.MatchFlag.MatchStartsWith)
    window.hosts.nav.everything.setCurrentItem(everything)  # pinned above the groups tree
    assert _table_names(window) == {"HQ-01", "FIN-02"}  # the tag stays picked
    window.hosts.nav.clear_tags()
    assert len(_table_names(window)) == 3


def test_selecting_a_host_shows_its_details(window: CapyWindow, office: Path) -> None:
    window.hosts.open_list(office)
    doc = window.hosts.document
    assert doc is not None
    fin02 = next(h for h in doc.hosts.hosts if h.name == "FIN-02")
    window.hosts.table.select_ids([fin02.id])
    assert window.hosts.details.shown_value("group") == "Headquarters › Finance"
    assert window.hosts.details.shown_value("notes") == "Reception"


def test_read_only_files_disable_editing(window: CapyWindow, office: Path) -> None:
    os.chmod(office, stat.S_IREAD)
    try:
        window.hosts.open_list(office)
        doc = window.hosts.document
        assert doc is not None and doc.read_only
        assert not window.hosts.commands.add_host.isEnabled()
        assert not window.hosts.commands.remove.isEnabled()
    finally:
        os.chmod(office, stat.S_IWRITE | stat.S_IREAD)


def test_a_broken_file_is_reported_and_the_current_list_stays_open(
    window: CapyWindow, tmp_path: Path
) -> None:
    before = window.hosts.document
    broken = tmp_path / "broken.json"
    broken.write_text("{ nope", encoding="utf-8")
    assert not window.hosts.open_list(broken, quiet=True)
    assert window.hosts.document is before


def test_closing_saves_layout_and_keeps_other_settings(
    qapp: QApplication, paths: settings.Paths
) -> None:
    win = CapyWindow(paths, {"schema": 1, "kept": True})
    win.hosts.commands.show_details.setChecked(False)
    win.close()
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["kept"] is True
    hosts = saved["tools"]["hosts"]  # each tool's settings in its own section
    assert hosts["view"]["details"] is False and saved["view"]["toolbar"] is True
    assert isinstance(saved["window_geometry"], str) and isinstance(hosts["main_splitter"], str)


def test_host_dialog_cleans_values_and_shows_group_paths(qapp: QApplication) -> None:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    # Full paths, not indentation: the closed drop-down then reads left-aligned.
    assert [label for _, label in group_choices(hl)] == [
        "No group", "Headquarters", "Headquarters › Finance"
    ]  # fmt: skip
    dialog = HostDialog(None, hl, default_group=finance.id)
    assert dialog.group.currentText() == "Headquarters › Finance"
    dialog.name.setText("  PC-9 ")
    dialog.tags.add_text("kiosk, , floor-3, kiosk")
    values = dialog.values()
    assert (values.name, values.group, values.tags) == ("PC-9", finance.id, ("kiosk", "floor-3"))


def _drag(monkeypatch: pytest.MonkeyPatch, table: HostTable, column: int, width: int) -> None:
    """A column's edge dragged with the mouse (a plain resize isn't a drag)."""
    monkeypatch.setattr(QApplication, "mouseButtons", lambda: Qt.MouseButton.LeftButton)
    table.header().resizeSection(column, width)
    monkeypatch.undo()


def test_columns_keep_their_title_visible_and_can_be_hidden(
    window: CapyWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.open_list(office)
    table = window.hosts.table
    _drag(monkeypatch, table, table.USER, 5)  # almost shut
    assert table.columnWidth(table.USER) >= table.minimum_width(table.USER) > 5
    table._show_column(table.USER, False)
    assert table.isColumnHidden(table.USER)
    assert window.hosts.prefs["hidden_columns"] == ["user"]
    reopened = CapyWindow(window.paths, dict(window.prefs))
    assert reopened.hosts.table.isColumnHidden(reopened.hosts.table.USER)
    reopened.hosts.table.set_hidden_columns(["computer"])
    assert not reopened.hosts.table.isColumnHidden(0)  # the host name always shows
    reopened.close()


def _hosts(*names_and_addresses: tuple[str, str]) -> tuple[Host, ...]:
    hl, ward = HostList().add_group("Ward")
    for name, address in names_and_addresses:
        hl, _ = hl.add_host(name, ward.id, address=address)
    return hl.hosts


def _table(qapp: QApplication, hosts: tuple[Host, ...]) -> HostTable:
    table = HostTable()
    table.set_hidden_columns(["tags", "notes"])
    table.show_hosts(hosts, {})
    table.resize(1200, 300)
    table.show()
    qapp.processEvents()
    return table


def _fit_view(qapp: QApplication, table: HostTable, view: int) -> None:
    """Resized so its rows have `view` px (each theme frames the table its own way)."""
    table.resize(view + table.width() - table.viewport().width(), 300)
    qapp.processEvents()


def test_the_first_start_fits_every_column_to_its_full_text(qapp: QApplication) -> None:
    long = "a." * 150 + "example.internal"  # far wider than the old 260 px cap
    table = _table(qapp, _hosts(("Reception 01", long)))
    assert table.columnWidth(table.ADDRESS) >= table.sizeHintForColumn(table.ADDRESS)
    # Status and User are empty before a check: a starting width with room for one.
    assert table.columnWidth(table.USER) > table.minimum_width(table.USER)
    table.close()


def test_column_widths_belong_to_the_user(
    window: CapyWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.open_list(office)
    table = window.hosts.table
    _drag(monkeypatch, table, 0, 300)
    other = office.with_name("other.json")
    other.write_bytes(office.read_bytes())
    window.hosts.open_list(other)  # another list: same widths, one set for all lists
    window.hosts.nav.select_group(next(g.id for g in window.hosts.document.hosts.groups))  # type: ignore[union-attr]
    assert table.columnWidth(0) == 300
    window.close()  # saved across restarts
    reopened = CapyWindow(window.paths, dict(window.prefs))
    assert reopened.hosts.table.widths()["computer"] == 300
    reopened.close()


def test_fit_columns_to_content_fits_the_full_text_again(
    window: CapyWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.open_list(office)
    table = window.hosts.table
    _drag(monkeypatch, table, table.ADDRESS, 300)
    table.fit_columns()
    assert table.widths()["address"] == max(
        table.sizeHintForColumn(table.ADDRESS), table.minimum_width(table.ADDRESS)
    )


def test_panes_cant_be_dragged_too_narrow_to_read(window: CapyWindow) -> None:
    scale = window.hosts._scale()
    assert window.hosts.details.minimumWidth() == round(260 * scale)
    assert window.hosts.nav.minimumWidth() == round(180 * scale)


def test_settings_from_before_the_notes_column_went_load_cleanly(
    qapp: QApplication, paths: settings.Paths
) -> None:
    prefs = {"schema": 1, "hidden_columns": ["notes", "tags"], "column_widths": {"notes": 90}}
    window = CapyWindow(paths, prefs)
    assert window.hosts.table.isColumnHidden(window.hosts.table.TAGS)
    assert "notes" not in window.hosts.table.widths()
    window.close()


def test_the_last_column_fills_a_wide_window_and_a_narrow_one_scrolls(
    qapp: QApplication,
) -> None:
    table = _table(qapp, _hosts(("Reception 01", "PC-0142.corp.example.net")))
    _fit_view(qapp, table, 1400)
    shown = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
    assert sum(table.columnWidth(c) for c in shown) == table.viewport().width()  # no gap
    _fit_view(qapp, table, 200)
    assert table.horizontalScrollBar().isVisible()
    table.close()


def test_clicking_a_row_with_a_long_text_doesnt_scroll_sideways(qapp: QApplication) -> None:
    long = "a." * 150 + "example.internal"  # far wider than the view
    hosts = _hosts(*((f"Ward {n:02}", long) for n in range(40)))
    table = _table(qapp, hosts)
    _fit_view(qapp, table, 400)
    across = table.horizontalScrollBar()
    assert across.maximum() > 0 and across.value() == 0
    row = table.topLevelItem(0)
    assert row is not None
    # In the long cell, which starts in view and ends far past it.
    spot = QPoint(
        table.columnViewportPosition(table.ADDRESS) + 20, table.visualItemRect(row).center().y()
    )
    QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, pos=spot)
    QTest.qWait(QApplication.doubleClickInterval() + 200)  # Qt scrolls to a click that late
    assert table.selected_ids() == [hosts[0].id] and across.value() == 0
    # The keyboard still brings a row into view, up and down only.
    QTest.keyClick(table, Qt.Key.Key_End)
    qapp.processEvents()
    assert table.verticalScrollBar().value() > 0 and across.value() == 0
    table.close()


def test_the_tags_pane_can_be_hidden_and_stays_hidden(window: CapyWindow, office: Path) -> None:
    window.hosts.open_list(office)
    tag = window.hosts.nav.tags.topLevelItem(0)
    assert tag is not None
    window.hosts.nav.tags.setCurrentItem(tag)  # filtering by a tag
    window.hosts.commands.show_tags.setChecked(False)
    assert window.hosts.nav.tags.isHidden() and window.hosts.nav.picked_tags() == []
    window.close()
    assert window.hosts.prefs["view"]["tags"] is False


def test_the_groups_pane_fits_all_computers(window: CapyWindow, office: Path) -> None:
    window.hosts.open_list(office)
    window.show()
    QApplication.processEvents()
    everything = window.hosts.nav.everything
    assert everything.minimumWidth() >= everything.sizeHintForColumn(0)
    assert not window.hosts.splitter.childrenCollapsible()


def test_the_view_menu_stays_open_while_ticking(window: CapyWindow) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    menu = window._view_menu
    menu.popup(window.mapToGlobal(window.rect().center()))
    menu.setActiveAction(window.hosts.commands.show_tags)
    QApplication.sendEvent(
        menu, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    assert not window.hosts.commands.show_tags.isChecked() and menu.isVisible()
    menu.close()


def test_right_click_menus_dont_pile_up(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A menu is made per click; each one used to stay until the app closed.
    class Shown(QMenu):
        def exec(self, *_args: object) -> None:  # type: ignore[override]
            return None

    monkeypatch.setattr(workspace_module, "QMenu", Shown)
    before = len(window.findChildren(QMenu))
    for _ in range(3):
        window.hosts._item_menu(QPoint(5, 5))
        window.hosts._group_menu(QPoint(5, 5))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(window.findChildren(QMenu)) == before


def test_only_the_sorted_column_keeps_room_for_the_sort_arrow(qapp: QApplication) -> None:
    table = _table(qapp, _hosts(("PC 1", "10.0.0.1")))
    unsorted = table.minimum_width(table.STATUS)
    table.sortByColumn(table.STATUS, Qt.SortOrder.AscendingOrder)
    assert table.minimum_width(table.STATUS) > unsorted  # the arrow shows there now
    table.close()


def test_an_old_saved_layout_cant_drag_a_pane_out_of_sight(
    qapp: QApplication, paths: settings.Paths
) -> None:
    old = QSplitter()  # saved before 0.14.0, when panes could still collapse
    for _ in range(3):
        old.addWidget(QWidget())
    state = old.saveState().toBase64().toStdString()
    window = CapyWindow(paths, {"schema": 1, "main_splitter": state})
    assert not window.hosts.splitter.childrenCollapsible()
    window.close()


def test_double_clicking_the_host_table_s_right_edge_fits_it_to_its_columns(
    window: CapyWindow, office: Path
) -> None:
    window.hosts.open_list(office)
    window.resize(1600, 700)
    window.show()
    QApplication.processEvents()
    splitter = window.hosts.splitter  # pyright: ignore[reportPrivateUsage]
    edge = splitter.indexOf(window.hosts.details)
    before = splitter.sizes()
    QTest.mouseDClick(splitter.handle(edge), Qt.MouseButton.LeftButton)
    after = splitter.sizes()
    hosts = window.hosts
    assert after[edge - 1] == max(hosts.table.natural_width(), hosts.items_pane.minimumWidth())
    assert sum(after) == sum(before) and after[0] == before[0]  # only those two panes change
    window.close()


def test_double_clicking_the_groups_panel_s_right_edge_fits_it_to_its_groups(
    window: CapyWindow, office: Path
) -> None:
    window.hosts.open_list(office)
    window.resize(1600, 700)
    window.show()
    QApplication.processEvents()
    splitter = window.hosts.splitter  # pyright: ignore[reportPrivateUsage]
    before = splitter.sizes()
    QTest.mouseDClick(splitter.handle(1), Qt.MouseButton.LeftButton)
    after = splitter.sizes()
    assert after[0] == max(window.hosts.nav.natural_width(), window.hosts.nav.minimumWidth())
    assert after[0] + after[1] == before[0] + before[1] and after[2] == before[2]
    window.close()


def test_an_edit_keeps_the_table_where_it_was_scrolled(qapp: QApplication) -> None:
    hosts = _hosts(*((f"PC-{n:03}", f"192.0.2.{n}") for n in range(1, 81)))
    table = _table(qapp, hosts)
    bar = table.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    middle = bar.value()
    assert middle > 0
    table.select_ids([hosts[40].id])
    renamed = (*hosts[:40], replace(hosts[40], name="PC-040b"), *hosts[41:])
    table.show_hosts(renamed, {})  # what an edit does: the table is filled again
    qapp.processEvents()
    assert bar.value() == middle
    table.show_hosts(hosts[:5], {})  # another group: back to the top
    table.show_hosts(hosts, {})
    assert bar.value() == 0
    table.close()
