import json
import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QMenu, QSplitter, QWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.locations import recent_lists
from capypanel.core.hosts.model import Host, HostList
from capypanel.ui.hosts import HostDialog, group_choices
from capypanel.ui.main_window import window as window_module
from capypanel.ui.main_window.host_views import HostTable
from capypanel.ui.main_window.window import MainWindow


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
def window(qapp: QApplication, paths: settings.Paths) -> Iterator[MainWindow]:
    win = MainWindow(paths, {"schema": 1})
    yield win
    win.close()


def _table_names(win: MainWindow) -> set[str]:
    items = (win.table.topLevelItem(i) for i in range(win.table.topLevelItemCount()))
    return {item.text(0) for item in items if item is not None}


def test_first_start_creates_the_personal_list_with_a_hosts_group(window: MainWindow) -> None:
    doc = window.document
    assert doc is not None and doc.path.name == "hosts.json" and doc.path.exists()
    assert [g.name for g in doc.hosts.groups] == ["Default group"]
    assert window.windowTitle().startswith("hosts.json")
    assert [a.text() for a in window.menuBar().actions()] == [
        "&File",
        "&Inventory",
        "&Connect",
        "&View",
    ]
    assert window.commands.add_host.isEnabled()


def test_opening_a_list_shows_its_hosts_and_remembers_it(window: MainWindow, office: Path) -> None:
    assert window.open_list(office)
    assert _table_names(window) == {"HQ-01", "FIN-01", "FIN-02"}
    assert recent_lists(window._prefs)[0] == office


def test_picking_a_group_or_tag_filters_the_table(window: MainWindow, office: Path) -> None:
    window.open_list(office)
    tree = window.nav.groups
    flags = Qt.MatchFlag.MatchStartsWith | Qt.MatchFlag.MatchRecursive
    [finance] = tree.findItems("Finance", flags)
    tree.setCurrentItem(finance)
    assert _table_names(window) == {"FIN-01", "FIN-02"}
    [kiosk] = window.nav.tags.findItems("kiosk", Qt.MatchFlag.MatchStartsWith)
    window.nav.tags.setCurrentItem(kiosk)
    assert _table_names(window) == {"HQ-01", "FIN-02"}
    [everything] = window.nav.everything.findItems("All hosts", Qt.MatchFlag.MatchStartsWith)
    window.nav.everything.setCurrentItem(everything)  # pinned above the groups tree
    assert len(_table_names(window)) == 3


def test_selecting_a_host_shows_its_details(window: MainWindow, office: Path) -> None:
    window.open_list(office)
    doc = window.document
    assert doc is not None
    fin02 = next(h for h in doc.hosts.hosts if h.name == "FIN-02")
    window.table.select_ids([fin02.id])
    assert window.details.shown_value("group") == "Headquarters › Finance"
    assert window.details.shown_value("notes") == "Reception"


def test_read_only_files_disable_editing(window: MainWindow, office: Path) -> None:
    os.chmod(office, stat.S_IREAD)
    try:
        window.open_list(office)
        doc = window.document
        assert doc is not None and doc.read_only
        assert not window.commands.add_host.isEnabled()
        assert not window.commands.remove.isEnabled()
    finally:
        os.chmod(office, stat.S_IWRITE | stat.S_IREAD)


def test_a_broken_file_is_reported_and_the_current_list_stays_open(
    window: MainWindow, tmp_path: Path
) -> None:
    before = window.document
    broken = tmp_path / "broken.json"
    broken.write_text("{ nope", encoding="utf-8")
    assert not window.open_list(broken, quiet=True)
    assert window.document is before


def test_closing_saves_layout_and_keeps_other_settings(
    qapp: QApplication, paths: settings.Paths
) -> None:
    win = MainWindow(paths, {"schema": 1, "kept": True})
    win.commands.show_details.setChecked(False)
    win.close()
    saved = json.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved["kept"] is True
    assert saved["view"]["details"] is False
    assert isinstance(saved["window_geometry"], str) and isinstance(saved["main_splitter"], str)


def test_host_dialog_cleans_values_and_shows_group_paths(qapp: QApplication) -> None:
    hl, hq = HostList().add_group("Headquarters")
    hl, finance = hl.add_group("Finance", parent=hq.id)
    # Full paths, not indentation: the closed drop-down then reads left-aligned.
    assert [label for _, label in group_choices(hl)] == ["Headquarters", "Headquarters › Finance"]
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
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    table = window.table
    _drag(monkeypatch, table, table.USER, 5)  # almost shut
    assert table.columnWidth(table.USER) >= table.minimum_width(table.USER) > 5
    table._show_column(table.USER, False)
    assert table.isColumnHidden(table.USER)
    assert window._prefs["hidden_columns"] == ["user"]
    reopened = MainWindow(window._paths, dict(window._prefs))
    assert reopened.table.isColumnHidden(reopened.table.USER)
    reopened.table.set_hidden_columns(["computer"])
    assert not reopened.table.isColumnHidden(0)  # the host name always shows
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
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    table = window.table
    _drag(monkeypatch, table, 0, 300)
    other = office.with_name("other.json")
    other.write_bytes(office.read_bytes())
    window.open_list(other)  # another list: same widths, one set for all lists
    window.nav.select_group(next(g.id for g in window.document.hosts.groups))  # type: ignore[union-attr]
    assert table.columnWidth(0) == 300
    window.close()  # saved across restarts
    reopened = MainWindow(window._paths, dict(window._prefs))
    assert reopened.table.widths()["computer"] == 300
    reopened.close()


def test_fit_columns_to_content_fits_the_full_text_again(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    table = window.table
    _drag(monkeypatch, table, table.ADDRESS, 300)
    table.fit_columns()
    assert table.widths()["address"] == max(
        table.sizeHintForColumn(table.ADDRESS), table.minimum_width(table.ADDRESS)
    )


def test_reset_layout_brings_back_panes_columns_and_default_widths(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    window.show()
    QApplication.processEvents()
    a = window.commands
    a.show_details.setChecked(False)
    a.show_status_bar.setChecked(False)
    window.table._show_column(window.table.TAGS, False)
    _drag(monkeypatch, window.table, 0, 400)
    size = window.size()
    a.show_domains.setChecked(False)
    a.reset_layout.trigger()
    QApplication.processEvents()
    assert a.show_details.isChecked() and window.details.isVisible()
    assert a.show_status_bar.isChecked()
    assert not window.table.isColumnHidden(window.table.TAGS)
    assert window.table.columnWidth(0) < 400  # fitted again
    assert window.size() == size and not a.show_domains.isChecked()  # left alone
    groups, _table_pane, details = window._splitter.sizes()
    assert abs(details - round(340 * window._scale())) <= 2
    window.close()


def test_panes_cant_be_dragged_too_narrow_to_read(window: MainWindow) -> None:
    scale = window._scale()
    assert window.details.minimumWidth() == round(260 * scale)
    assert window.nav.minimumWidth() == round(180 * scale)


def test_settings_from_before_the_notes_column_went_load_cleanly(
    qapp: QApplication, paths: settings.Paths
) -> None:
    prefs = {"schema": 1, "hidden_columns": ["notes", "tags"], "column_widths": {"notes": 90}}
    window = MainWindow(paths, prefs)
    assert window.table.isColumnHidden(window.table.TAGS)
    assert "notes" not in window.table.widths()
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


def test_the_tags_pane_can_be_hidden_and_stays_hidden(window: MainWindow, office: Path) -> None:
    window.open_list(office)
    tag = window.nav.tags.topLevelItem(0)
    assert tag is not None
    window.nav.tags.setCurrentItem(tag)  # filtering by a tag
    window.commands.show_tags.setChecked(False)
    assert window.nav.tags.isHidden() and window.nav.current_filter().kind == "all"
    window.close()
    assert window._prefs["view"]["tags"] is False


def test_the_groups_pane_fits_all_computers(window: MainWindow, office: Path) -> None:
    window.open_list(office)
    window.show()
    QApplication.processEvents()
    everything = window.nav.everything
    assert everything.minimumWidth() >= everything.sizeHintForColumn(0)
    assert not window._splitter.childrenCollapsible()


def test_the_view_menu_stays_open_while_ticking(window: MainWindow) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    menu = window._view_menu
    menu.popup(window.mapToGlobal(window.rect().center()))
    menu.setActiveAction(window.commands.show_tags)
    QApplication.sendEvent(
        menu, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    assert not window.commands.show_tags.isChecked() and menu.isVisible()
    menu.close()


def test_right_click_menus_dont_pile_up(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A menu is made per click; each one used to stay until the app closed.
    class Shown(QMenu):
        def exec(self, *_args: object) -> None:  # type: ignore[override]
            return None

    monkeypatch.setattr(window_module, "QMenu", Shown)
    before = len(window.findChildren(QMenu))
    for _ in range(3):
        window._host_menu(QPoint(5, 5))
        window._group_menu(QPoint(5, 5))
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
    window = MainWindow(paths, {"schema": 1, "main_splitter": state})
    assert not window._splitter.childrenCollapsible()
    window.close()
