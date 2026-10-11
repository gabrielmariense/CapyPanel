import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHeaderView,
    QMenu,
    QPushButton,
)

from capypanel.core import settings, winsec
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui.host_lists import HostListsDialog, HostListsView
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.themes import engine as themes


@pytest.fixture(autouse=True)
def drop_unsaved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing Settings with changes asks first; in tests, the answer is Discard."""
    monkeypatch.setattr(SettingsDialog, "_ask_unsaved", lambda *_a, **_k: "discard")


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


def _save_enabled(dialog: SettingsDialog) -> bool:
    return dialog.is_valid()  # a list that can't be opened can't be saved


def _answer_save_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_settings_is_in_the_file_menu_and_has_five_pages(window: MainWindow) -> None:
    assert window.commands.settings.shortcut().toString() == "Ctrl+,"
    [file_menu] = [a.menu() for a in window.menuBar().actions() if a.text() == "&File"]
    assert isinstance(file_menu, QMenu) and window.commands.settings in file_menu.actions()
    dialog = window.settings_dialog()
    titles = [p.title for p in dialog.pages.values()]
    assert titles == ["General", "Host lists", "Connections", "Appearance"]


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
        ("Default", "Read/write", False),  # the first start created it
        ("Personal", "Created when opened", False),
        ("Added", "Read/write", True),
    ]
    names = [view.tree.topLevelItem(i).text(0) for i in range(3)]  # type: ignore[union-attr]
    assert names == ["hosts.json", "hosts.json", "office.json (in use)"]
    os.chmod(office, stat.S_IREAD)
    try:
        assert _rows(window.settings_dialog().host_lists.view)[2][1] == "Read-only"
    finally:
        os.chmod(office, stat.S_IWRITE | stat.S_IREAD)


def test_a_default_list_another_user_made_cant_be_picked(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(winsec, "made_by_trusted", lambda _path: False)
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    assert _rows(view)[0][1] == "Not used: made by another user"
    view.select(window._default_list)
    assert not _save_enabled(dialog)


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


def test_save_needs_a_list_that_exists(window: MainWindow, tmp_path: Path) -> None:
    window._prefs["host_lists"] = [str(tmp_path / "nowhere.json")]
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.select(tmp_path / "nowhere.json")
    assert _rows(view)[2][1] == "File not found" and not _save_enabled(dialog)
    view.select(window._personal_list)  # created when it's opened
    assert _save_enabled(dialog)


def test_an_added_list_opens_on_save_and_cancel_changes_nothing(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_open_dialog(monkeypatch, office)
    before, prefs = window.document, dict(window._prefs)
    dialog = window.settings_dialog()
    dialog.host_lists.view.add_button.click()
    dialog.reject()
    assert window.document is before and window._prefs == prefs
    dialog = window.settings_dialog()
    dialog.host_lists.view.add_button.click()
    window.apply_settings(dialog.choices())
    assert window.document is not None and window.document.path == office
    assert window._prefs["host_lists"] == [str(office)]


def test_removing_a_list_forgets_it_but_never_deletes_the_file(
    window: MainWindow, office: Path
) -> None:
    window.open_list(office)
    dialog = window.settings_dialog()
    view = dialog.host_lists.view
    view.select(office)
    assert view.remove_button.isEnabled()
    view.remove_button.click()
    assert [r[0] for r in _rows(view)] == ["Default", "Personal"]
    view.select(window._default_list)
    assert not view.remove_button.isEnabled()  # the default and personal lists always stay
    window.apply_settings(dialog.choices())
    assert window._prefs["host_lists"] == [] and office.is_file()


def test_missing_personal_list_is_created_when_chosen(window: MainWindow) -> None:
    personal = window._personal_list
    assert not personal.exists()
    dialog = window.settings_dialog()
    dialog.host_lists.view.select(personal)
    window.apply_settings(dialog.choices())
    assert personal.exists() and window.document is not None
    assert [g.name for g in window.document.hosts.groups] == ["Default group"]


def test_copy_current_list_writes_it_and_save_opens_the_copy(
    window: MainWindow, office: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    copy = tmp_path / "copy.json"
    _answer_save_dialog(monkeypatch, copy)
    dialog = window.settings_dialog()
    dialog.host_lists.view.copy_button.click()
    assert listfile.load(copy).hosts == listfile.load(office).hosts
    assert dialog.host_lists.chosen() == copy
    window.apply_settings(dialog.choices())
    assert window.document is not None and window.document.path == copy


def test_new_empty_list_over_the_open_one_reopens_it(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    _answer_save_dialog(monkeypatch, office)  # the user confirmed replacing it
    dialog = window.settings_dialog()
    dialog.host_lists.view.new_button.click()
    choices = dialog.choices()
    assert choices.rewritten
    window.apply_settings(choices)
    assert window.document is not None
    assert [g.name for g in window.document.hosts.groups] == ["Default group"]
    assert not window.document.hosts.hosts


def test_file_host_lists_opens_a_list_and_remembers_what_was_added(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _answer_open_dialog(monkeypatch, office)

    def use(dialog: HostListsDialog) -> int:
        dialog.view.add_button.click()  # selects the added list
        assert dialog.open_button.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(HostListsDialog, "exec", use)
    window.commands.open_list.trigger()  # File > Host lists… (Ctrl+O)
    assert window.document is not None and window.document.path == office
    assert window._prefs["host_lists"] == [str(office)]


def test_menus_hold_only_what_fits_them(window: MainWindow) -> None:
    menus = {
        m.title(): [a.text() for a in m.actions() if a.text()]
        for a in window.menuBar().actions()
        if isinstance(m := a.menu(), QMenu)
    }
    assert menus["&File"][:2] == ["&New host list…", "&Host lists…"]
    assert menus["&Inventory"] == [
        "Add &host…", "Add &group…", "&Manage groups…", "&Import hosts…"
    ]  # fmt: skip
    assert menus["&Connect"] == [
        "&Manual connection…", "Connection &profiles…", "&Forget typed passwords"
    ]  # fmt: skip
    # Edit, Remove and Copy address are only in right-click menus, yet keep their shortcuts.
    a = window.commands
    assert {a.edit, a.remove, a.copy_address} <= set(window.actions())


def test_start_list_choice_is_opened_next_time(
    window: MainWindow, paths: settings.Paths, office: Path
) -> None:
    window.open_list(office)  # the last used list...
    dialog = window.settings_dialog()
    general = dialog.general.start_list
    assert general.currentData() == "last"
    assert [general.itemData(i) for i in range(general.count())] == [
        "last",
        "default",
        "personal",
        str(office),
    ]
    general.setCurrentIndex(general.findData("personal"))
    window.apply_settings(dialog.choices())
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


def test_appearance_applies_the_chosen_theme(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    [paper] = [b for b in dialog.appearance.buttons() if b.property("theme_id") == "paper"]
    paper.setChecked(True)
    window.apply_settings(dialog.choices())
    assert themes.current().id == "paper"
    assert settings.load_settings(window._paths.settings_file)["theme"] == "paper"


def test_the_path_is_in_the_tooltip_and_same_names_show_their_folder(
    window: MainWindow, tmp_path: Path
) -> None:
    a, b = tmp_path / "north" / "hosts.json", tmp_path / "south" / "hosts.json"
    window._prefs["host_lists"] = [str(a), str(b)]
    view = window.settings_dialog().host_lists.view
    names = [view.tree.topLevelItem(i).text(0) for i in range(4)]  # type: ignore[union-attr]
    assert names[2:] == ["hosts.json (north)", "hosts.json (south)"]
    item = view.tree.topLevelItem(2)
    assert item is not None and item.toolTip(0) == str(a) == item.toolTip(1)


@pytest.mark.parametrize("answer", ["stay", "discard", "save"])
def test_leaving_connections_with_changes_asks_first(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    dialog = window.settings_dialog()
    monkeypatch.setattr(type(dialog), "_ask_unsaved", lambda *_a, **_k: answer)
    connections_row = list(dialog.pages).index("connections")
    dialog.page_list.setCurrentRow(connections_row)
    page = dialog.connections
    page.default.setCurrentIndex(page.default.findData("realvnc"))  # an unsaved change
    assert page.has_changes()
    dialog.page_list.setCurrentRow(0)  # try to go to General
    store = page.store
    if answer == "stay":
        assert dialog.stack.currentWidget() is page and page.has_changes()
        assert dialog.page_list.currentRow() == connections_row
    elif answer == "discard":
        assert dialog.stack.currentIndex() == 0 and not page.has_changes()
        assert store.default_id() == "ultravnc"  # nothing written
    else:
        assert dialog.stack.currentIndex() == 0 and not page.has_changes()
        assert store.default_id() == "realvnc"  # written now, not only on Save


def test_save_applies_and_keeps_settings_open(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    dialog.saved.connect(lambda choices: window._settings_saved(dialog, choices))
    page = dialog.connections
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    dialog._update_save()  # what a click or key in the window does
    dialog.save_button.click()
    assert page.store.default_id() == "realvnc"  # applied now
    assert not page.has_changes() and dialog.result() == 0  # still open, nothing pending
    dialog.show()
    QApplication.processEvents()
    order = [b.text() for b in sorted(dialog.buttons.buttons(), key=lambda b: b.x())]
    assert order == ["&Save", "Close"]  # no OK: Save, then Close on the far right
    assert not dialog.save_button.isEnabled()  # just saved: nothing to save
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))
    page.default.setCurrentIndex(page.default.findData("ultravnc"))  # a change
    dialog._update_save()
    assert dialog.save_button.isEnabled() and dialog.unsaved()
    dialog.close()


def test_close_asks_before_dropping_changes(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = window.settings_dialog()
    dialog.saved.connect(lambda choices: window._settings_saved(dialog, choices))
    asked: list[str] = []

    def answer(_self: SettingsDialog, text: str, **_k: object) -> str:
        asked.append(text)
        return "stay" if len(asked) == 1 else "save"

    monkeypatch.setattr(SettingsDialog, "_ask_unsaved", answer)
    dialog.show()
    dialog.close_button.click()
    assert asked == [] and not dialog.isVisible()  # nothing changed: just closes
    dialog.show()
    dialog.general.auto_status.setChecked(True)
    dialog.close_button.click()
    assert asked == ["Some changes aren't saved yet."] and dialog.isVisible()  # Keep editing
    dialog.close_button.click()  # then Save changes
    assert not dialog.isVisible() and window._auto_status()[0]


def test_picking_a_language_switches_at_once_keeping_unsaved_choices(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str, bool, bool]] = []

    def run(dialog: SettingsDialog) -> int:
        dialog.show_page("general")
        dialog.general.auto_status.setChecked(True)  # not saved
        dialog.general.language.setCurrentIndex(dialog.general.language.findData("pt_BR"))
        QApplication.processEvents()  # the window follows once the dropdown has closed
        seen.append(
            (
                dialog.windowTitle(),
                dialog.current_page(),
                dialog.general.auto_status.isChecked(),
                dialog.unsaved(),
            )
        )
        return 0

    monkeypatch.setattr(SettingsDialog, "exec", run)
    window.open_settings()
    # Switched without Save: the app and Settings are in Portuguese; the unsaved tick stays.
    assert seen == [("Configurações", "general", True, True)]
    assert window.menuBar().actions()[0].text() == "&Arquivo"
    window.set_language("en")


def test_list_tables_have_grid_lines_and_resizable_columns(window: MainWindow) -> None:
    view = window.settings_dialog().host_lists.view
    assert view.tree.objectName() == window.table.objectName() == "grid"
    header = view.tree.header()
    assert all(header.sectionResizeMode(c) == QHeaderView.ResizeMode.Interactive for c in range(3))
