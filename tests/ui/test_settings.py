import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog, QMenu

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.settings.window import SettingsDialog
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
    themes.apply(themes.DEFAULT_THEME)


def _save_enabled(dialog: SettingsDialog) -> bool:
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Save).isEnabled()


def _answer_save_dialog(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_settings_is_in_the_file_menu_and_has_three_pages(window: MainWindow) -> None:
    assert window.commands.settings.shortcut().toString() == "Ctrl+,"
    [file_menu] = [a.menu() for a in window.menuBar().actions() if a.text() == "&File"]
    assert isinstance(file_menu, QMenu) and window.commands.settings in file_menu.actions()
    dialog = window.settings_dialog()
    assert [p.title for p in dialog.pages.values()] == ["General", "Host lists", "Appearance"]


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


def test_host_lists_page_shows_the_open_list_and_what_can_be_done_with_it(
    window: MainWindow, office: Path
) -> None:
    window.open_list(office)
    page = window.settings_dialog().host_lists
    assert page.other_choice.isChecked() and Path(page.other_path.text()) == office
    assert page.other_state.text() == "Read-write"
    assert page.personal_state.text() == "Read-write"  # the first start created it
    os.chmod(office, stat.S_IREAD)
    try:
        page = window.settings_dialog().host_lists
        assert page.other_state.text() == "Read-only"
    finally:
        os.chmod(office, stat.S_IWRITE | stat.S_IREAD)


def test_default_list_can_only_be_picked_when_it_exists(
    qapp: QApplication, paths: settings.Paths, tmp_path: Path
) -> None:
    default = tmp_path / "data" / "hosts.json"

    def dialog() -> SettingsDialog:
        return SettingsDialog(
            None,
            paths=paths,
            start_list="last",
            default_list=default,
            personal_list=tmp_path / "me.json",
            document=None,
            recent=[],
            registry=themes.Registry(),
        )

    first = dialog()
    page = first.host_lists
    assert not page.default_choice.isEnabled() and page.default_state.text() == "Not found"
    assert page.personal_choice.isChecked()
    assert page.personal_state.text() == "Created when opened"
    default.parent.mkdir()
    listfile.save(default, HostList(), expected=None)
    second = dialog()
    page = second.host_lists
    # Whoever can write the app folder (an admin, or anyone in a team without one) can edit it.
    assert page.default_choice.isEnabled() and page.default_state.text() == "Read-write"
    os.chmod(default, stat.S_IREAD)
    try:
        third = dialog()
        assert third.host_lists.default_state.text() == "Read-only"
    finally:
        os.chmod(default, stat.S_IWRITE | stat.S_IREAD)


def test_save_needs_a_list_that_exists(window: MainWindow, tmp_path: Path) -> None:
    dialog = window.settings_dialog()
    page = dialog.host_lists
    page.other_path.setText(str(tmp_path / "nowhere.json"))
    page.other_choice.setChecked(True)
    page.other_path.editingFinished.emit()
    assert not _save_enabled(dialog) and page.other_state.text() == "File not found"
    page.personal_choice.setChecked(True)
    assert _save_enabled(dialog)


def test_saving_opens_the_chosen_list(window: MainWindow, office: Path) -> None:
    dialog = window.settings_dialog()
    dialog.host_lists.other_path.setText(str(office))
    dialog.host_lists.other_choice.setChecked(True)
    window.apply_settings(dialog.choices())
    assert window.document is not None and window.document.path == office


def test_cancel_changes_nothing(window: MainWindow, office: Path) -> None:
    before = window.document.path if window.document else None
    prefs = dict(window._prefs)
    dialog = window.settings_dialog()
    dialog.host_lists.other_path.setText(str(office))
    dialog.host_lists.other_choice.setChecked(True)
    dialog.general.start_list.setCurrentIndex(dialog.general.start_list.count() - 1)
    dialog.reject()
    assert window.document is not None and window.document.path == before
    assert window._prefs == prefs


def test_missing_personal_list_is_created_when_chosen(window: MainWindow, office: Path) -> None:
    window.open_list(office)
    personal = window._personal_list
    personal.unlink()
    dialog = window.settings_dialog()
    dialog.host_lists.personal_choice.setChecked(True)
    window.apply_settings(dialog.choices())
    assert personal.exists() and window.document is not None
    assert [g.name for g in window.document.hosts.groups] == ["Hosts"]


def test_copy_current_list_writes_it_and_save_opens_the_copy(
    window: MainWindow, office: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    copy = tmp_path / "copy.json"
    _answer_save_dialog(monkeypatch, copy)
    dialog = window.settings_dialog()
    dialog.host_lists.copy_button.click()
    assert listfile.load(copy).hosts == listfile.load(office).hosts
    assert dialog.host_lists.other_choice.isChecked()
    assert Path(dialog.host_lists.other_path.text()) == copy
    window.apply_settings(dialog.choices())
    assert window.document is not None and window.document.path == copy


def test_new_empty_list_over_the_open_one_reopens_it(
    window: MainWindow, office: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.open_list(office)
    _answer_save_dialog(monkeypatch, office)  # the user confirmed replacing it
    dialog = window.settings_dialog()
    dialog.host_lists.new_button.click()
    choices = dialog.choices()
    assert choices.rewritten
    window.apply_settings(choices)
    assert window.document is not None
    assert [g.name for g in window.document.hosts.groups] == ["Hosts"]
    assert not window.document.hosts.hosts


def test_start_list_choice_is_opened_next_time(
    window: MainWindow, paths: settings.Paths, office: Path
) -> None:
    window.open_list(office)  # the last used list...
    dialog = window.settings_dialog()
    general = dialog.general.start_list
    assert general.currentData() == "last"
    assert [general.itemData(i) for i in range(general.count())] == [
        "last",
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
    assert again.document is not None and again.document.path == window._personal_list
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
