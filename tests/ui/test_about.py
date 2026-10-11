from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton

from capypanel import BUILD
from capypanel.core import i18n, settings
from capypanel.ui import about, branding, language
from capypanel.ui.about import AboutDialog
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    yield win
    win.close()
    language.apply(i18n.DEFAULT_LANGUAGE)


def test_the_help_menu_has_the_website_a_problem_report_and_about(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    menus = [m for a in window.menuBar().actions() if isinstance(m := a.menu(), QMenu)]
    help_menu = menus[-1]
    assert help_menu.title() == "&Help"
    texts = [a.text() for a in help_menu.actions() if a.text()]
    assert texts == ["&Documentation", "&Report a problem", "&About CapyPanel"]
    opened: list[str] = []
    monkeypatch.setattr(about, "open_url", opened.append)
    window.commands.documentation.trigger()
    window.commands.report_problem.trigger()
    assert opened[0] == "https://gabrielmariense.github.io/CapyPanel/"
    assert opened[1].startswith("https://github.com/gabrielmariense/CapyPanel/issues/new?body=")
    assert f"CapyPanel {BUILD}" in unquote(opened[1])  # the version, ready in the report


def test_the_website_opens_in_the_app_s_language(qapp: QApplication) -> None:
    language.apply("pt_BR")
    try:
        assert about.docs_url().endswith("/CapyPanel/pt-BR/")
    finally:
        language.apply(i18n.DEFAULT_LANGUAGE)


def test_about_names_the_creator_the_version_and_the_license(qapp: QApplication) -> None:
    dialog = AboutDialog(None, Path("."))
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert f"Version {BUILD}" in texts
    assert "Gabriel Tobias Mariense (GMErebos)" in texts
    assert any("GNU General Public License, version 3" in t for t in texts)
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))


def test_the_app_icon_and_mascot_load(qapp: QApplication) -> None:
    icon = branding.app_icon()
    assert {s.width() for s in icon.availableSizes()} == set(branding.ICON_SIZES)
    picture = branding.mascot(120, 2.0)
    assert picture.height() == 240 and picture.devicePixelRatio() == 2.0
