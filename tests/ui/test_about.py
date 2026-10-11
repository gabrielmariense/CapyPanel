import getpass
import platform
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QPushButton

from capypanel import BUILD, __version__
from capypanel.core import i18n, settings
from capypanel.ui import about, branding, language
from capypanel.ui.about import COMPONENTS, LICENSES_DIR, AboutDialog, LicensesDialog
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
        assert about.source_url().endswith("/README.pt-BR.md")  # GitHub shows the English one
    finally:
        language.apply(i18n.DEFAULT_LANGUAGE)


def test_about_names_the_creator_the_version_and_the_license(qapp: QApplication) -> None:
    dialog = AboutDialog(None, Path("."), portable=True)
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog.version.text() == __version__ and dialog.version.copy_text() == BUILD
    assert 'Gabriel "GMErebos" Mariense · © 2026' in texts  # name and © in one place only
    assert any("GPL-3.0" in t and "free to use, change and share" in t for t in texts)
    assert any(t.endswith("portable mode") for t in texts)  # only what applies
    assert not any("Python and Qt for Python" in t for t in texts)  # in Third-party licenses
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))


def test_third_party_licenses_show_each_part_with_its_text(qapp: QApplication) -> None:
    dialog = LicensesDialog(None)
    names = [dialog.parts.item(i).text() for i in range(dialog.parts.count())]
    assert [n.split()[0] for n in names] == ["Qt", "Python", "Tabler"]
    dialog.parts.setCurrentRow(2)
    assert "Paweł Kuna" in dialog.text.toPlainText() and "MIT License" in dialog.text.toPlainText()
    for _name, _notice, files in COMPONENTS:
        for file in files:
            if file != "lgpl-3.0.txt":  # still to be added from gnu.org
                assert (LICENSES_DIR / file).is_file(), file


def test_a_problem_report_carries_no_user_or_computer_name(qapp: QApplication) -> None:
    body = unquote(about.report_url(portable=False).split("?body=", 1)[1])  # not the URL
    assert "Theme: " in body and "Language: en" in body and "· source" in body
    assert getpass.getuser() not in body and platform.node() not in body


def test_the_app_icon_and_mascot_load(qapp: QApplication) -> None:
    icon = branding.app_icon()
    assert {s.width() for s in icon.availableSizes()} == set(branding.ICON_SIZES)
    picture = branding.mascot(120, 2.0)
    assert picture.height() == 240 and picture.devicePixelRatio() == 2.0
