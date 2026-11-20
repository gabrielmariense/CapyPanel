from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QMenu,
    QTabBar,
    QTreeWidget,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui import language
from capypanel.ui.menus import label


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, hq = HostList().add_group("Headquarters")
    hl, _host = hl.add_host("HQ-01", hq.id)
    office = tmp_path / "office.json"
    listfile.save(office, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(office)]})
    yield win
    win.close()
    language.apply(i18n.DEFAULT_LANGUAGE)
    QApplication.processEvents()


def _menus(win: CapyWindow) -> list[QMenu]:
    return [m for a in win.menuBar().actions() if isinstance(m := a.menu(), QMenu)]


def _switch(win: CapyWindow, code: str) -> None:
    win.set_language(code)
    QApplication.processEvents()  # the LanguageChange event arrives through the event loop


def test_switching_language_updates_the_open_window_live(window: CapyWindow) -> None:
    _switch(window, "pt_BR")
    assert [m.title() for m in _menus(window)] == [
        "&Arquivo",
        "E&xibir",
        "Aj&uda",
    ]
    assert label(window.hosts.commands.add_host) == "Adicionar &host…"
    assert window.hosts.table.headerItem().text(0) == "Nome"
    [everything] = window.hosts.nav.everything.findItems("Todos", Qt.MatchFlag.MatchStartsWith)
    assert everything.text(0) == "Todos os hosts (1)"
    assert "1 host" in window.hosts.status_label.text()
    _switch(window, "en")
    assert [m.title() for m in _menus(window)] == [
        "&File", "&View", "&Help"
    ]  # fmt: skip
    assert window.hosts.table.headerItem().text(0) == "Name"


def _texts(win: CapyWindow) -> list[str]:
    """Every text the window holds: widgets, actions, combo items, tabs, headers and rows."""
    found = []
    for widget in [win, *win.findChildren(QWidget)]:
        found += [widget.windowTitle(), widget.toolTip()]
        for name in ("text", "title", "placeholderText"):
            value = getattr(widget, name, None)
            if callable(value):
                found.append(str(value()))
        if isinstance(widget, QComboBox):
            found += [widget.itemText(i) for i in range(widget.count())]
        if isinstance(widget, QTabBar):
            found += [widget.tabText(i) for i in range(widget.count())]
        if isinstance(widget, QTreeWidget):
            header = widget.headerItem()
            found += [header.text(c) for c in range(header.columnCount())]
            for row in range(widget.topLevelItemCount()):
                item = widget.topLevelItem(row)
                found += [item.text(c) for c in range(item.columnCount())]
    for action in win.findChildren(QAction):
        found += [action.text(), action.toolTip()]
    return found


def test_a_window_is_built_in_its_language(qapp: QApplication, tmp_path: Path) -> None:
    # At start the language is set before the window exists, and nothing translates the window
    # again once it's built: every text must be there from the start.
    language.apply("pt_BR")
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, hq = HostList().add_group("Headquarters")
    hl, _host = hl.add_host("HQ-01", hq.id)
    office = tmp_path / "office.json"
    listfile.save(office, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(office)]})
    try:
        again: list[int] = []
        retranslate = win.retranslate
        win.retranslate = lambda: again.append(1)  # type: ignore[method-assign]
        for _round in range(3):  # Qt passes the app's event on to each window as a new one
            QApplication.processEvents()
        assert again == []  # the start's LanguageChange never reaches it
        assert _menus(win)[0].title() == "&Arquivo"
        # A note's old buttons wait for deleteLater: gone first, so only today's are counted.
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        built = _texts(win)
        retranslate()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert _texts(win) == built
    finally:
        win.close()
        language.apply(i18n.DEFAULT_LANGUAGE)
        QApplication.processEvents()


def test_qt_own_buttons_are_translated_too(window: CapyWindow) -> None:
    _switch(window, "pt_BR")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancelar"


def test_language_is_remembered(window: CapyWindow) -> None:
    _switch(window, "pt_BR")
    saved = settings.load_settings(window.paths.settings_file)
    assert saved["language"] == "pt_BR"


def test_the_language_dropdown_in_appearance_switches_at_once(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    assert "language" not in dialog.pages  # just a dropdown on General now
    dialog.language_picked.connect(window.set_language)
    combo = dialog.general.language
    combo.setCurrentIndex(combo.findData("pt_BR"))  # no Save needed
    QApplication.processEvents()
    assert i18n.language() == "pt_BR" and _menus(window)[0].title() == "&Arquivo"


@pytest.mark.parametrize("code", list(i18n.LANGUAGES))
def test_access_keys_are_unique_in_every_menu(window: CapyWindow, code: str) -> None:
    # Two items with the same underlined letter make Alt+letter ambiguous.
    _switch(window, code)
    for menu in [*_menus(window), window.hosts.toolbar.inventory_menu]:
        texts = [label(a) for a in menu.actions() if "&" in a.text()]
        keys = [t[t.index("&") + 1].lower() for t in texts]
        assert len(keys) == len(set(keys)), f"{menu.title()}: {texts}"
    bar = [m.title() for m in _menus(window)]
    keys = [t[t.index("&") + 1].lower() for t in bar]
    assert len(keys) == len(set(keys)), bar
