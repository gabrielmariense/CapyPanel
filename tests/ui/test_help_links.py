"""Help from where you are (ui/help_links.py): F1 and the ? open the docs at a window's own part,
and a warning or error links its own line, in CapyPanel's language. The docs' side, every place
on its page in both languages, is tests/docs/test_help_places.py."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

from capypanel.core import i18n, settings
from capypanel.ui import about, help_links
from capypanel.ui.settings.shortcuts_page import FIXED_ROLE, KEY, KeyCatcher

SITE = "https://gabrielmariense.github.io/CapyPanel/"
SRC = Path(__file__).resolve().parents[2] / "src" / "capypanel"


@pytest.fixture
def paths(tmp_path: Path) -> settings.Paths:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    return settings.resolve_paths(tmp_path)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every address help opens, instead of a browser."""
    urls: list[str] = []
    monkeypatch.setattr(about, "open_url", urls.append)
    return urls


@pytest.fixture
def back_to_english() -> Iterator[None]:
    yield
    i18n.set_language("en")


def test_a_place_opens_its_line_and_a_page_its_top_in_capypanel_s_language(
    back_to_english: None,
) -> None:
    i18n.set_language("en")
    assert (
        help_links.url("settings-ssh-general") == f"{SITE}settings-and-files/#settings-ssh-general"
    )
    assert help_links.url("ssh/ssh/") == f"{SITE}ssh/ssh/"
    i18n.set_language("pt_BR")  # the same id on the Portuguese page
    assert help_links.url("settings-ssh-general") == (
        f"{SITE}pt-BR/settings-and-files/#settings-ssh-general"
    )
    with pytest.raises(KeyError):
        help_links.url("settings-ssh")  # a typo fails here, never as a dead link


def test_a_link_takes_the_text_colour_where_the_theme_s_own_hardly_shows() -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#4c2a85"))  # a dark purple accent
    assert help_links.link_color(palette).name() == "#f0f0f0"
    palette.setColor(QPalette.ColorRole.Link, QColor("#8ab4f8"))  # reads on the dark window
    assert help_links.link_color(palette).name() == "#8ab4f8"


def _box(place: str) -> QMessageBox:
    box = QMessageBox(QMessageBox.Icon.Warning, "CapyPanel", "Couldn't save “a.csv”: in use.")
    help_links.add_link(box, place)
    return box


def test_a_warning_box_links_its_line_and_stays_open_when_it_s_clicked(
    qapp: QApplication, opened: list[str]
) -> None:
    box = _box("commands-the-commands-window")
    box.show()
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    assert label is not None and "What does this mean?" in label.text()
    assert label.toolTip() == f"{SITE}hosts/commands/#commands-the-commands-window"
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByKeyboard
    label.linkActivated.emit(label.toolTip())
    assert opened == [f"{SITE}hosts/commands/#commands-the-commands-window"]
    assert box.isVisible()  # read the line, then answer the box
    box.close()


def test_f1_in_a_warning_box_opens_its_line(qapp: QApplication, opened: list[str]) -> None:
    box = _box("connecting-forget-a-saved-password")
    box.show()
    box.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(box, Qt.Key.Key_F1)
    assert opened == [f"{SITE}hosts/connecting/#connecting-forget-a-saved-password"]
    box.close()


def test_a_box_keeps_its_own_details_above_the_link(qapp: QApplication) -> None:
    box = QMessageBox(QMessageBox.Icon.Warning, "CapyPanel", "Couldn't save.")
    box.setInformativeText("C:\\Lists\\a<b>.json")
    help_links.add_link(box, "host-lists-switch-make-and-share-lists")
    text = box.informativeText()
    assert text.startswith("C:\\Lists\\a&lt;b&gt;.json<br><br><a href=")  # read as text, not tags


def test_the_question_mark_opens_its_window_s_part_by_click_and_by_f1(
    qapp: QApplication, opened: list[str]
) -> None:
    window = QWidget()
    shown = ["settings-hosts-general"]
    button = help_links.HelpButton(lambda: shown[0])
    button.setParent(window)
    assert button.toolTip() == "Help for this screen (F1)"
    assert button.accessibleName() == "Help for this screen"
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    button.click()
    shown[0] = "settings-ssh-general"  # the page shown changed
    QTest.keyClick(window, Qt.Key.Key_F1)
    QTest.qWait(250)  # a button's key clicks it a moment later, as a mouse click looks
    assert opened == [
        f"{SITE}settings-and-files/#settings-hosts-general",
        f"{SITE}settings-and-files/#settings-ssh-general",
    ]
    window.close()


def test_a_strip_s_link_shows_only_with_a_message_that_has_a_line(
    qapp: QApplication, opened: list[str]
) -> None:
    link = help_links.HelpLink()
    assert link.isHidden()
    link.set_place("connecting-connect-to-a-host")
    assert not link.isHidden() and "What does this mean?" in link.text()
    link.linkActivated.emit("")
    link.set_place("")  # a message that worked: no line
    assert link.isHidden()
    assert opened == [f"{SITE}hosts/connecting/#connecting-connect-to-a-host"]


def test_every_place_the_code_names_is_in_the_list() -> None:
    """Places are written where they're used (place="…", HELP_PLACE = "…"): each must be in
    help_links' list, which the docs check reads."""
    named = re.compile(r'(?:place=|HELP_PLACE = |help_links\.\w+\()"([^"]+)"')
    known = set(help_links.PLACES) | set(help_links.TOPS)
    unknown = [
        f"{path.relative_to(SRC)}: {place}"
        for path in SRC.rglob("*.py")
        for place in named.findall(path.read_text(encoding="utf-8"))
        if place not in known
    ]
    assert unknown == []


def test_f1_and_the_rail_s_question_mark_open_the_part_for_what_s_shown(
    qapp: QApplication, paths: settings.Paths, opened: list[str]
) -> None:
    window = CapyWindow(paths, {"schema": 1})
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    rail = window.rail
    # Bottom left like every window's ?: above the gear, an action that takes no tile.
    assert rail.help_button.y() < rail.settings_button.y() and not rail.help_button.isCheckable()
    assert rail.help_button.toolTip() == "Help for this screen (F1)"
    assert rail.help_button.accessibleName() == "Help for this screen"
    window.show_home()
    window.commands.help_screen.trigger()
    assert window.show_tool("hosts")
    QTest.keyClick(window, Qt.Key.Key_F1)
    assert window.show_tool("ssh")
    rail.help_button.click()
    assert opened == [
        f"{SITE}getting-started/#start-run-capypanel",
        f"{SITE}hosts/host-lists/",
        f"{SITE}ssh/ssh/",
    ]
    window.close()


def test_the_help_menu_s_new_line_sits_above_documentation_with_f1(
    qapp: QApplication, paths: settings.Paths
) -> None:
    window = CapyWindow(paths, {"schema": 1})
    a = window.commands
    lines = window._help_menu.actions()
    assert lines.index(a.help_screen) == lines.index(a.documentation) - 1
    assert a.help_screen.text().startswith("&Help for this screen")
    assert a.help_screen.shortcut().toString() == "F1"
    window.close()


def test_f1_s_row_is_greyed_and_a_kept_key_never_takes_its_place(
    qapp: QApplication, paths: settings.Paths
) -> None:
    window = CapyWindow(paths, {"schema": 1, "shortcuts": {"app.help_screen": "Ctrl+H"}})
    assert window.commands.help_screen.shortcut().toString() == "F1"  # a hand-edited file
    page = window.settings_dialog().shortcuts
    item = page.item_of("app.help_screen")
    assert item.text(KEY) == "F1" and item.flags() == Qt.ItemFlag.NoItemFlags
    assert item.data(0, FIXED_ROLE) and "can't be changed" in item.toolTip(KEY)
    page.change(item)  # a double-click on it waits for no key
    assert page.table.itemWidget(item, KEY) is None
    window.close()


def test_each_of_settings_pages_opens_its_own_part(
    qapp: QApplication, paths: settings.Paths
) -> None:
    window = CapyWindow(paths, {"schema": 1})
    pages = window.settings_dialog().pages
    assert {page_id: pages[page_id].place for page_id in MY_SETTINGS_PAGES} == MY_SETTINGS_PAGES
    window.close()


MY_SETTINGS_PAGES = {
    "general": "settings-capypanel-general",
    "shortcuts": "settings-capypanel-keyboard-shortcuts",
    "hosts": "settings-hosts-general",
    "connections": "settings-hosts-connecting",
    "accounts": "settings-hosts-credentials",
    "ssh": "settings-ssh-general",
    "about": "settings-about",
}


def test_settings_question_mark_sits_under_the_pages_and_opens_the_page_shown(
    qapp: QApplication, paths: settings.Paths, opened: list[str]
) -> None:
    window = CapyWindow(paths, {"schema": 1})
    dialog = window.settings_dialog()
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    button, pinned = dialog.help_button, dialog.pinned_list
    # On its own line under the page list (About is its last row), at the search's left edge.
    top_left = button.mapTo(dialog, QPoint(0, 0))
    assert top_left.y() >= pinned.mapTo(dialog, QPoint(0, pinned.height())).y()
    assert top_left.x() == dialog.search.mapTo(dialog, QPoint(0, 0)).x()
    button.click()  # General, as Settings opens
    dialog.show_page("ssh")
    QTest.keyClick(dialog, Qt.Key.Key_F1)
    QTest.qWait(250)  # a button's key clicks it a moment later
    dialog.search.setText("theme")  # the search's results
    button.click()
    dialog.search.clear()
    dialog.show_page("about")
    dialog.pages["about"].place = ""  # a page with no part of its own: the page's top
    button.click()
    assert opened == [
        f"{SITE}settings-and-files/#settings-capypanel-general",
        f"{SITE}settings-and-files/#settings-ssh-general",
        f"{SITE}settings-and-files/#settings-find-a-setting",
        f"{SITE}settings-and-files/",
    ]
    dialog.close()
    window.close()


def test_f1_while_a_key_is_awaited_is_that_key_refused_not_help(
    qapp: QApplication, paths: settings.Paths, opened: list[str]
) -> None:
    window = CapyWindow(paths, {"schema": 1})
    dialog = window.settings_dialog()
    dialog.show_page("shortcuts")
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    page = dialog.shortcuts
    item = page.item_of("command.services")
    page.change(item)
    catcher = page.table.itemWidget(item, KEY)
    assert isinstance(catcher, KeyCatcher)
    QTest.keyClick(catcher, Qt.Key.Key_F1)
    QTest.qWait(250)
    assert catcher.property("refused") is True  # "Kept for CapyPanel itself: F1 is for help…"
    assert opened == []
    dialog.close()
    window.close()
