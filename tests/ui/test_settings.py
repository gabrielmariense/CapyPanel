import os
import re
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
)

from capypanel.core import settings, winsec
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui import tables
from capypanel.ui.host_lists import HostListsView
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.menus import label
from capypanel.ui.settings.window import PAGE_TITLES, ROOM, SettingsDialog
from capypanel.ui.themes import engine as themes


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


@pytest.fixture
def office(tmp_path: Path) -> Path:
    hl, hq = HostList().add_group("Headquarters")
    hl, _ = hl.add_host("HQ-01", hq.id)
    path = tmp_path / "share" / "office.json"
    path.parent.mkdir()
    listfile.save(path, hl, expected=None)
    return path


@pytest.fixture
def window(qapp: QApplication, paths: settings.Paths) -> Iterator[MainWindow]:
    win = MainWindow(paths, {"schema": 1})
    yield win
    win.close()
    if themes.current() is not themes.DEFAULT_THEME:  # a theme switch restyles every window
        themes.apply(themes.DEFAULT_THEME)


def _answer_save_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_settings_has_the_app_s_pages_then_the_hosts_tool_s(window: MainWindow) -> None:
    assert window.commands.settings.shortcut().toString() == "Ctrl+,"
    [file_menu] = [a.menu() for a in window.menuBar().actions() if a.text() == "&File"]
    assert isinstance(file_menu, QMenu) and window.commands.settings in file_menu.actions()
    dialog = window.settings_dialog()
    rows = [dialog.page_list.item(i).text().strip() for i in range(dialog.page_list.count())]
    assert rows == [
        "CapyPanel",
        "General",
        "Files",
        "Hosts",
        "General",
        "Host lists",
        "Connections",
    ]
    assert dialog.current_page() == "general"


def test_page_list_rows_never_overlap(window: MainWindow) -> None:
    # The list once kept row positions from before the theme's padding arrived.
    window.show()
    window.set_theme("windows-light")
    window.set_theme("capypanel-dark")
    dialog = window.settings_dialog()
    dialog.show()
    QApplication.processEvents()
    pages = dialog.page_list
    rects = [pages.visualItemRect(pages.item(i)) for i in range(pages.count())]
    dialog.close()
    for above, below in zip(rects, rects[1:], strict=False):
        assert below.top() > above.bottom(), f"rows overlap: {above} and {below}"
    assert all(r.height() > pages.fontMetrics().height() for r in rects)


def _rows(view: HostListsView) -> list[tuple[str, str, bool]]:
    """Each row: its kind, its access, and whether it's the list open now (bold)."""
    rows = []
    for i in range(view.tree.topLevelItemCount()):
        item = view.tree.topLevelItem(i)
        assert item is not None
        rows.append((item.text(1), item.text(2), item.font(0).bold()))
    return rows


def _answer_open_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))


def test_host_lists_shows_every_list_with_the_open_one_in_bold(
    window: MainWindow, office: Path
) -> None:
    window.open_list(office)  # an opened list is added to Host lists from now on
    view = window.settings_dialog().host_lists.view
    assert _rows(view) == [
        ("Shared", "Read/write", False),  # the default list: the first start created it
        ("Yours", "Created when opened", False),  # the personal list
        ("Added", "Read/write", True),
    ]
    names = [view.tree.topLevelItem(i).text(0) for i in range(3)]  # type: ignore[union-attr]
    assert names == ["Default", "Personal", "office (in use)"]
    os.chmod(office, stat.S_IREAD)
    try:
        assert _rows(window.settings_dialog().host_lists.view)[2][1] == "Read-only"
    finally:
        os.chmod(office, stat.S_IWRITE | stat.S_IREAD)


def test_a_default_list_another_user_made_cant_be_picked(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(winsec, "made_by_trusted", lambda _path: False)
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    assert _rows(view)[0][1] == "Not used: made by another user"
    view.select(window._default_list)
    before = window.document
    view.open_picked()  # a double-click
    assert window.document is before and len(warned) == 1


def test_first_start_creates_and_opens_the_default_list(
    window: MainWindow, paths: settings.Paths
) -> None:
    assert window.document is not None and window.document.path == paths.default_list
    assert [g.name for g in window.document.hosts.groups] == ["Default group"]
    assert not paths.personal_list.exists()  # made only when someone chooses it


def test_a_default_list_another_user_made_is_not_opened(
    qapp: QApplication, paths: settings.Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths.default_list.parent.mkdir(parents=True, exist_ok=True)
    listfile.save(paths.default_list, HostList(), expected=None)
    monkeypatch.setattr(winsec, "made_by_trusted", lambda _path: False)
    win = MainWindow(paths, {"schema": 1})
    assert win.document is not None and win.document.path == paths.personal_list
    assert "another user" in win.statusBar().currentMessage()
    win.close()


def test_removing_a_list_forgets_it_but_never_deletes_the_file(
    window: MainWindow, office: Path
) -> None:
    window.open_list(office)
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.select(office)
    assert view.remove_button.isEnabled()
    view.remove_button.click()
    assert [r[0] for r in _rows(view)] == ["Shared", "Yours"]  # the default and personal lists
    view.select(window._default_list)
    assert not view.remove_button.isEnabled()  # the default and personal lists always stay
    assert window._prefs["host_lists"] == [] and office.is_file()


def test_missing_personal_list_is_created_when_chosen(window: MainWindow) -> None:
    personal = window._personal_list
    assert not personal.exists()
    view = window.settings_dialog().host_lists.view
    view.select(personal)
    view.open_picked()
    assert personal.exists() and window.document is not None
    assert [g.name for g in window.document.hosts.groups] == ["Default group"]


def test_new_empty_list_over_the_open_one_reopens_it(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    _answer_save_dialog(monkeypatch, office)  # the user confirmed replacing it
    dialog = window.settings_dialog()
    dialog.host_lists.view.new_button.click()  # a new list opens at once
    assert window.document is not None and window.document.path == office
    assert [g.name for g in window.document.hosts.groups] == ["Default group"]
    assert not window.document.hosts.hosts


def test_open_list_from_the_dropdown_opens_a_list_and_keeps_it_there(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_open_dialog(monkeypatch, office)
    window.commands.open_list.trigger()  # the list dropdown's Open list… (Ctrl+O)
    assert window.document is not None and window.document.path == office
    assert window._prefs["host_lists"] == [str(office)]
    window.list_picker.menu().aboutToShow.emit()  # filled as it opens
    texts = [label(a) for a in window.list_picker.menu().actions() if a.text()]
    assert texts[:3] == ["Default", "Personal", "office"]  # by file name
    assert texts[3:] == ["&New list…", "&Open list…", "&Manage host lists…"]
    assert window.list_picker.text() == "office" and window.windowTitle().startswith("office —")


def test_menus_hold_only_what_fits_them(window: MainWindow) -> None:
    menus = {
        m.title(): [label(a) for a in m.actions() if a.text()]
        for a in window.menuBar().actions()
        if isinstance(m := a.menu(), QMenu)
    }
    assert list(menus) == ["&File", "&View", "&Help"]  # the same for every tool
    assert menus["&File"] == ["&Settings…", "E&xit"]  # lists are in the list dropdown
    assert menus["&View"] == [
        "&Hosts", "&Groups pane", "T&ags pane", "&Details pane", "Show users' do&main",
        "T&oolbar", "&Status bar", "&Reset layout",
    ]  # fmt: skip
    # The tool's own commands are in its toolbar.
    inventory = [label(a) for a in window.toolbar.inventory_menu.actions() if a.text()]
    assert inventory == ["Add &host…", "Add &group…", "&Manage groups…", "&Import hosts…"]
    window._fill_connect_menu()  # pyright: ignore[reportPrivateUsage]
    connect = [label(a) for a in window.toolbar.connect_menu.actions() if a.text()][-3:]
    assert connect == ["&Manual connection…", "Connection &profiles…", "&Forget typed passwords"]
    # Commands outside the menu bar keep their shortcuts.
    a = window.commands
    shortcuts = {a.edit, a.remove, a.copy_address, a.add_host, a.add_group, a.manual_connect}
    assert shortcuts <= set(window.actions())


def test_start_list_choice_is_opened_next_time(
    window: MainWindow, paths: settings.Paths, office: Path
) -> None:
    window.open_list(office)  # the last used list...
    dialog = window.settings_dialog()
    general = dialog.hosts.start_list
    assert general.currentData() == "last"
    assert [general.itemData(i) for i in range(general.count())] == [
        "last",
        "default",
        "personal",
        str(office),
    ]
    general.setCurrentIndex(general.findData("personal"))  # kept at once, with no Save
    again = MainWindow(paths, settings.load_settings(paths.settings_file))
    assert again.document is not None and again.document.path == window._personal_list
    again.close()


def test_a_missing_start_list_falls_back_and_says_so(
    window: MainWindow, paths: settings.Paths, office: Path
) -> None:
    prefs = {"schema": 1, "start_list": str(office.with_name("gone.json"))}
    again = MainWindow(paths, prefs)
    assert again.document is not None and again.document.path == paths.default_list
    assert "gone.json" in again.statusBar().currentMessage()
    again.close()


def test_last_used_list_is_reopened(
    window: MainWindow, paths: settings.Paths, office: Path
) -> None:
    window.open_list(office)
    again = MainWindow(paths, settings.load_settings(paths.settings_file))
    assert again.document is not None and again.document.path == office
    assert not again.statusBar().currentMessage()
    again.close()


def test_picking_a_theme_applies_it_at_once(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    combo = dialog.general.theme
    combo.setCurrentIndex(combo.findData("paper"))  # the window shows it already
    assert themes.current().id == "paper"
    assert settings.load_settings(window._paths.settings_file)["theme"] == "paper"


def test_the_path_is_in_the_tooltip_and_same_names_show_their_folder(
    window: MainWindow, tmp_path: Path
) -> None:
    a, b = tmp_path / "north" / "hosts.json", tmp_path / "south" / "hosts.json"
    window._prefs["host_lists"] = [str(a), str(b)]
    view = window.settings_dialog().host_lists.view
    names = [view.tree.topLevelItem(i).text(0) for i in range(4)]  # type: ignore[union-attr]
    assert names[2:] == ["hosts (north)", "hosts (south)"]
    item = view.tree.topLevelItem(2)
    assert item is not None and item.toolTip(0) == str(a) == item.toolTip(1)


def test_list_tables_have_grid_lines_and_resizable_columns(window: MainWindow) -> None:
    view = window.settings_dialog().host_lists.view
    assert view.tree.objectName() == window.table.objectName() == "grid"
    header = view.tree.header()
    assert all(header.sectionResizeMode(c) == QHeaderView.ResizeMode.Interactive for c in range(3))


def test_the_page_list_keeps_its_width_in_every_language(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    assert [p.title for p in dialog.pages.values()] == list(PAGE_TITLES)  # sized from these
    width = dialog.page_list.width()
    dialog.general.language.setCurrentIndex(dialog.general.language.findData("pt_BR"))
    QApplication.processEvents()
    assert dialog.page_list.width() == width and dialog.general.title == "Geral"
    window.set_language("en")


def test_removing_the_open_list_switches_to_the_default_list(
    window: MainWindow, office: Path, paths: settings.Paths
) -> None:
    window.open_list(office)
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.select(office)
    view.remove_button.click()  # the default list opens in its place, at once
    assert window.document is not None and window.document.path == paths.default_list
    assert _rows(view)[0][2]  # marked in use


def test_the_search_shows_every_matching_section_on_one_page(window: MainWindow) -> None:
    dialog = window.settings_dialog()

    def listed() -> list[str]:
        rows = range(dialog.page_list.count())
        return [
            dialog.page_list.item(r).text().strip()  # type: ignore[union-attr]
            for r in rows
            if not dialog.page_list.isRowHidden(r)
        ]

    def results() -> list[str]:
        return [
            re.sub("<[^>]+>", "", w.text())  # the search's marks are rich text
            for w in dialog._results.findChildren(QLabel)  # pyright: ignore[reportPrivateUsage]
            if w.objectName() in ("hint", "detailsSection") and w.isVisibleTo(dialog._results)  # pyright: ignore[reportPrivateUsage]
        ]

    dialog.search.setText("th")  # too short: the pages as they were
    assert len(listed()) == dialog.page_list.count() and dialog.current_page() == "general"
    dialog.search.setText("theme")
    assert dialog.current_page() == "search" and listed() == ["CapyPanel", "General"]
    assert results()[:2] == ["CapyPanel › General", "Language and theme"]  # under its page
    marks = dialog._marks  # pyright: ignore[reportPrivateUsage]
    assert [w.objectName() for w in marks.marked_labels()][:1] == ["detailsSection"]
    dialog.search.setText("folder")  # in Files, a Host lists note, Connections. buttons
    assert listed() == ["CapyPanel", "Files", "Hosts", "Host lists", "Connections"]
    dialog.search.setText("syst")  # "follow system theme"; not a tool path's "System32"
    assert listed() == ["CapyPanel", "General"]
    dialog.show_page("files")  # picking a page ends the search: everything goes home
    assert dialog.search.text() == "" and dialog.current_page() == "files"
    assert dialog.files.findChildren(QLabel)  # its section is back on its page
    assert len(listed()) == dialog.page_list.count()


def test_a_list_in_a_lists_folder_can_be_removed_and_added_back(
    window: MainWindow, paths: settings.Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    branch = paths.shared_lists_dir / "branch.json"
    listfile.save(branch, HostList(), expected=None)
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.select(branch)
    assert view.remove_button.isEnabled()
    view.remove_button.click()
    assert len(_rows(view)) == 2 and branch.is_file()  # hidden here, the file stays
    window.list_picker.menu().aboutToShow.emit()
    assert "branch" not in [label(a) for a in window.list_picker.menu().actions()]
    view = window.settings_dialog().host_lists.view
    _answer_open_dialog(monkeypatch, branch)
    view.add_button.click()  # Add existing… brings it back
    assert len(_rows(view)) == 3 and view.hidden == [] and view.added == []


def test_open_folder_opens_the_picked_list_s_folder(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()))
    window.open_list(office)
    view = window.settings_dialog().host_lists.view
    view.select(office)
    menu = QMenu()
    view.fill_row_menu(menu)  # what a right-click on the row opens
    assert [label(a) for a in menu.actions() if a.text()] == [
        "&Open", "Save a &copy…", "Open &folder", "&Remove"
    ]  # fmt: skip
    [folder] = [a for a in menu.actions() if a.text() == "Open &folder"]
    folder.trigger()
    assert [Path(p) for p in opened] == [office.parent]


def test_list_tables_show_six_rows_at_most_and_pages_never_get_cut(
    window: MainWindow, paths: settings.Paths
) -> None:
    for name in "abcdefg":
        listfile.save(paths.shared_lists_dir / f"{name}.json", HostList(), expected=None)
    dialog = window.settings_dialog()
    dialog.show()
    dialog.show_page("host_lists")
    QApplication.processEvents()
    tree = dialog.host_lists.view.tree
    assert tree.viewport().height() == 6 * tree.sizeHintForRow(0)  # no 7th row peeking in
    page = dialog.host_lists
    assert page.width() >= page.minimumSizeHint().width() + ROOM  # widened, with room to spare
    dialog.close()


def test_search_marks_go_away_with_the_search(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    dialog.search.setText("theme")
    [heading, *_notes] = dialog._marks.marked_labels()  # pyright: ignore[reportPrivateUsage]
    assert "<span" in heading.text()
    dialog.search.clear()
    assert heading.text() == "Language and theme" and not dialog._marks.marked_labels()  # pyright: ignore[reportPrivateUsage]


def test_a_list_that_doesn_t_exist_can_t_be_opened(
    window: MainWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    warned: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warned.append(text))
    window._prefs["host_lists"] = [str(tmp_path / "nowhere.json")]
    view = window.settings_dialog().host_lists.view
    view.select(tmp_path / "nowhere.json")
    assert _rows(view)[2][1] == "File not found"
    view.open_picked()
    assert warned and window.document is not None
    assert window.document.path != tmp_path / "nowhere.json"


def test_an_added_list_is_kept_at_once_and_opens_on_a_double_click(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_open_dialog(monkeypatch, office)
    before = window.document
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.add_button.click()
    assert window._prefs["host_lists"] == [str(office)]  # kept, with no Save
    assert window.document is before  # adding a list doesn't open it
    view.open_picked()  # a double-click opens it
    assert window.document is not None and window.document.path == office
    assert _rows(view)[2][2]  # marked as the one in use now


def test_save_a_copy_writes_it_and_keeps_the_list_in_use(
    window: MainWindow, office: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    copy = tmp_path / "copy.json"
    _answer_save_dialog(monkeypatch, copy)
    view = window.settings_dialog().host_lists.view
    view.select(office)
    view.copy_picked()  # the row's right-click: Save a copy…
    assert listfile.load(copy).hosts == listfile.load(office).hosts
    assert view.selected() == copy and str(copy) in window._prefs["host_lists"]
    assert window.document is not None and window.document.path == office


def test_every_choice_applies_at_once_and_only_close_is_left(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    dialog.hosts.auto_status.setChecked(True)
    assert window._auto_status()[0]  # kept and running, with no Save
    page = dialog.connections.profiles
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    assert page.store.default_id() == "realvnc"  # written for everyone at once
    dialog.show()
    QApplication.processEvents()
    assert [b.text() for b in dialog.buttons.buttons()] == ["Close"]
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))
    dialog.close_button.click()  # nothing to ask: it just closes
    assert not dialog.isVisible()


def test_picking_a_language_switches_at_once_and_keeps_the_page(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, bool]] = []

    def run(dialog: SettingsDialog) -> int:
        dialog.show_page("general")
        dialog.hosts.auto_status.setChecked(True)
        dialog.general.language.setCurrentIndex(dialog.general.language.findData("pt_BR"))
        QApplication.processEvents()  # the window follows once the dropdown has closed
        seen.append(
            (dialog.windowTitle(), dialog.current_page(), dialog.hosts.auto_status.isChecked())
        )
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", run)
    window.open_settings()
    # The app and Settings are in Portuguese; the tick, applied already, still shows.
    assert seen == [("Configurações", "general", True)]
    assert window.menuBar().actions()[0].text() == "&Arquivo"
    window.set_language("en")


def test_the_settings_buttons_are_only_the_main_actions(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    for page_id, wanted in (
        ("files", ["Open folder"]),
        ("host_lists", ["&New…", "&Add existing…", "&Remove"]),
        ("connections", ["&Add…", "&Edit…", "&Delete…", "Change path…", "Download"]),
    ):
        page = dialog.pages[page_id]
        assert [b.text() for b in page.findChildren(QPushButton)] == wanted, page_id


def test_a_right_click_picks_the_row_and_opens_its_menu(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[list[str]] = []
    monkeypatch.setattr(
        tables,
        "popup",
        lambda menu, _at: shown.append([label(a) for a in menu.actions() if a.text()]),
    )
    window.open_list(office)
    dialog = window.settings_dialog()
    dialog.show()
    dialog.show_page("host_lists")
    QApplication.processEvents()
    tree = dialog.host_lists.view.tree
    office_row = tree.topLevelItem(2)
    assert office_row is not None
    tree.customContextMenuRequested.emit(tree.visualItemRect(office_row).center())
    assert tree.currentItem() is office_row  # picked by the right-click
    assert shown == [["&Open", "Save a &copy…", "Open &folder", "&Remove"]]
    dialog.close()
