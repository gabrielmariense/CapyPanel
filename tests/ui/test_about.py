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
from capypanel.ui.about import COMPONENTS, LICENSES_DIR, AboutDialog
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
    tabs = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    assert tabs == ["About", "Credits", "Licenses"]
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog.version.text() == __version__ and dialog.version.copy_text() == BUILD
    assert '© 2026 Gabriel "GMErebos" Mariense' in texts
    notice = next(t for t in texts if "with no warranty" in t)  # the GPL's notices
    assert "GPL-3.0" in notice and 'href="#licenses"' in notice
    assert any(t.endswith("portable mode") for t in texts)  # only what applies
    assert not any(b.isDefault() or b.autoDefault() for b in dialog.findChildren(QPushButton))
    dialog._open_link("#licenses")  # "see Licenses" opens the tab
    assert dialog.tabs.currentIndex() == 2


def test_licenses_list_each_part_with_a_link_to_its_shipped_text(qapp: QApplication) -> None:
    dialog = AboutDialog(None, Path("."), portable=False)
    texts = [label.text() for label in dialog.licenses.findChildren(QLabel)]
    assert [c.name for c in COMPONENTS][:1] == ["CapyPanel"]  # its own license first
    for part in COMPONENTS:
        assert (LICENSES_DIR / part.file).is_file(), part.file  # shipped, readable offline
        assert any(part.file in t and part.license in t for t in texts)  # linked by name
    assert any("The Qt Company" in t for t in texts)  # the library's copyright, as LGPL asks
    dialog._open_link("license:lgpl-3.0.txt")  # read in the app, not in Notepad
    assert dialog.reader.isVisible() and dialog.reader.windowTitle() == "Qt · LGPL-3.0"
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in dialog.reader.text.toPlainText()
    dialog.reader.close()


def test_a_problem_report_carries_no_user_or_computer_name(qapp: QApplication) -> None:
    body = unquote(about.report_url(portable=False).split("?body=", 1)[1])  # not the URL
    assert "Theme: " in body and "Language: en" in body and "· source" in body
    assert getpass.getuser() not in body and platform.node() not in body


def test_the_app_icon_and_mascot_load(qapp: QApplication) -> None:
    icon = branding.app_icon()
    assert {s.width() for s in icon.availableSizes()} == set(branding.ICON_SIZES)
    picture = branding.mascot(120, 2.0)
    assert picture.height() == 240 and picture.devicePixelRatio() == 2.0
