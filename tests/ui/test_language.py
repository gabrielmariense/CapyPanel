from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMenu

from capypanel.core import i18n, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.ui import language
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, hq = HostList().add_group("Headquarters")
    hl, _host = hl.add_host("HQ-01", hq.id)
    office = tmp_path / "office.json"
    listfile.save(office, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1, "recent_lists": [str(office)]})
    yield win
    win.close()
    language.apply(i18n.DEFAULT_LANGUAGE)
    QApplication.processEvents()


def _menus(win: MainWindow) -> list[QMenu]:
    return [m for a in win.menuBar().actions() if isinstance(m := a.menu(), QMenu)]


def _switch(win: MainWindow, code: str) -> None:
    win.set_language(code)
    QApplication.processEvents()  # the LanguageChange event arrives through the event loop


def test_switching_language_updates_the_open_window_live(window: MainWindow) -> None:
    _switch(window, "pt_BR")
    assert [m.title() for m in _menus(window)] == [
        "&Arquivo",
        "&Inventário",
        "&Conectar",
        "E&xibir",
    ]
    assert window.commands.add_host.text() == "Adicionar &host…"
    assert window.table.headerItem().text(0) == "Computador"
    [everything] = window.nav.everything.findItems("Todos", Qt.MatchFlag.MatchStartsWith)
    assert everything.text(0) == "Todos os hosts (1)"
    assert "1 host" in window._list_label.text()
    _switch(window, "en")
    assert [m.title() for m in _menus(window)] == ["&File", "&Inventory", "&Connect", "&View"]
    assert window.table.headerItem().text(0) == "Computer"


def test_qt_own_buttons_are_translated_too(window: MainWindow) -> None:
    _switch(window, "pt_BR")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancelar"


def test_language_is_remembered(window: MainWindow) -> None:
    _switch(window, "pt_BR")
    saved = settings.load_settings(window._paths.settings_file)
    assert saved["language"] == "pt_BR"
    checked = [a.data() for a in window._language_group.actions() if a.isChecked()]
    assert checked == ["pt_BR"]


def test_the_language_dropdown_in_general_switches_on_save(window: MainWindow) -> None:
    dialog = window.settings_dialog()
    assert "language" not in dialog.pages  # just a dropdown on General now
    combo = dialog.general.language
    combo.setCurrentIndex(combo.findData("pt_BR"))
    window.apply_settings(dialog.choices())
    QApplication.processEvents()
    assert i18n.language() == "pt_BR" and _menus(window)[0].title() == "&Arquivo"


@pytest.mark.parametrize("code", list(i18n.LANGUAGES))
def test_access_keys_are_unique_in_every_menu(window: MainWindow, code: str) -> None:
    # Two items with the same underlined letter make Alt+letter ambiguous.
    _switch(window, code)
    for menu in [*_menus(window), window._theme_menu]:
        texts = [a.text() for a in menu.actions() if "&" in a.text()]
        keys = [t[t.index("&") + 1].lower() for t in texts]
        assert len(keys) == len(set(keys)), f"{menu.title()}: {texts}"
    bar = [m.title() for m in _menus(window)]
    keys = [t[t.index("&") + 1].lower() for t in bar]
    assert len(keys) == len(set(keys)), bar
