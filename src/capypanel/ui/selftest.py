"""`CapyPanel.exe --self-test <report file>`: does this copy of CapyPanel work at all?

A packaged build brings its own Python, Qt and libraries, and a file left out of it only shows
when the part that needs it runs. This loads every bundled folder, the libraries that come as
compiled code, Qt's own parts, and the whole window with every tool, theme and language. Its
windows are made for real but never put on the screen, and it works in a folder of its own that
it removes: nothing of the person's is read or written, and nothing reaches the network. It
writes what it found to the report file and ends with 0 when all of it worked. The build runs
it on the build server before a zip is made."""

import shutil
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path


def _bundled_files() -> list[str]:
    from capypanel.core import i18n
    from capypanel.core.tools import catalog, profile_store
    from capypanel.ui import about, branding, icons
    from capypanel.ui.themes import engine as themes

    found = []
    for what, folder, pattern, least in (
        ("translations", i18n.LOCALE_DIR, "*/LC_MESSAGES/*.mo", 1),
        ("themes", themes.THEMES_DIR, "*.json", 2),
        ("theme images", themes.THEMES_DIR, "*.svg", 5),
        ("icons", icons.TABLER_DIR, "*.svg", 50),
        ("app icons", branding.BRANDING_DIR, "*.png", 5),
        ("licenses", about.LICENSES_DIR, "*.txt", 5),
        ("tools", catalog.SHIPPED_DIR / "tools", "*.json", 1),
        ("profiles", profile_store.STARTERS_DIR, "*", 1),
    ):
        count = len(list(folder.glob(pattern)))
        if count < least:
            raise RuntimeError(f"{what}: {count} of at least {least} files in {folder}")
        found.append(f"{what} {count}")
    return found


def _compiled_libraries() -> list[str]:
    """What comes as compiled code: imported and used once."""
    import pythoncom  # noqa: F401
    import pywintypes  # noqa: F401
    import win32com.client  # noqa: F401
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from PySide6.QtCore import QByteArray
    from PySide6.QtNetwork import QLocalServer  # noqa: F401
    from PySide6.QtSvg import QSvgRenderer

    encryptor = Cipher(algorithms.AES(bytes(16)), CFB(bytes(16))).encryptor()
    if len(encryptor.update(b"capypanel") + encryptor.finalize()) != 9:
        raise RuntimeError("cryptography: AES gave another length")
    svg = QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    if not QSvgRenderer(svg).isValid():
        raise RuntimeError("QtSvg can't read an SVG")
    return ["pywin32", "cryptography", "QtSvg", "QtNetwork"]


def _qt_parts() -> list[str]:
    """Qt's plugins and translations, which a build can leave out without any error: the
    Windows look, the image formats the icons come in, and Qt's own words (OK, Cancel) in each
    language CapyPanel has."""
    from PySide6.QtCore import QLibraryInfo, QTranslator
    from PySide6.QtGui import QGuiApplication, QImageReader
    from PySide6.QtWidgets import QApplication, QStyleFactory

    from capypanel.core import i18n

    app = QApplication.instance() or QApplication([])
    platform = QGuiApplication.platformName()
    styles = {name.casefold() for name in QStyleFactory.keys()}  # noqa: SIM118 -- a list
    formats = {bytes(f.data()).decode() for f in QImageReader.supportedImageFormats()}
    for what, have, needs in (
        ("styles", styles, {"windows11", "fusion"}),
        ("image formats", formats, {"svg", "png", "ico"}),
    ):
        if not needs <= have:
            raise RuntimeError(f"{what}: {sorted(needs - have)} missing of {sorted(have)}")
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for code in i18n.LANGUAGES:
        if code != i18n.DEFAULT_LANGUAGE and not QTranslator(app).load(f"qtbase_{code}", folder):
            raise RuntimeError(f"Qt's own words in {code} are missing from {folder}")
    return [f"platform {platform}", "styles", "image formats", "Qt's translations"]


def _whole_window(root: Path) -> list[str]:
    """The window with every tool, in every theme and language, and every page of Settings
    (About is one: it names the version of each library that came along)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from capypanel.core import i18n, settings
    from capypanel.ui.main_window.window import MainWindow
    from capypanel.ui.themes import engine as themes
    from capypanel.ui.tool_catalog import CATALOG

    app = QApplication.instance() or QApplication([])
    (root / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(root, account="self-test")
    settings.ensure_dirs(paths)
    tools = [info.load() for info in CATALOG]
    for tool in tools:
        tool.prepare(paths)
    registry = themes.Registry()
    prefs = {"schema": settings.SETTINGS_SCHEMA, settings.CLOSE_KEY: settings.CLOSE_QUIT}
    window = MainWindow(paths, prefs, registry=registry, tools=tools)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    for theme in registry.all():
        window.set_theme(theme.id)
        app.processEvents()
    for code in i18n.LANGUAGES:
        window.set_language(code)
        app.processEvents()
    for tool_id in window.tools:
        window.show_tool(tool_id)
        app.processEvents()
    window.show_home()
    dialog = window.settings_dialog()
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.show()
    for page in dialog.pages:
        dialog.show_page(page)
        app.processEvents()
    shown = (len(window.tools), len(registry.all()), len(i18n.LANGUAGES), len(dialog.pages))
    dialog.close()
    window.close()
    app.processEvents()
    return [
        f"tools {shown[0]}",
        f"themes {shown[1]}",
        f"languages {shown[2]}",
        f"settings pages {shown[3]}",
    ]


def run(report: Path) -> int:
    """Every check, each one's outcome a line of `report`. 0: all of them worked."""
    from capypanel import BUILD

    root = Path(tempfile.mkdtemp(prefix="capypanel-self-test-"))
    lines = [f"CapyPanel {BUILD}", f"packaged: {bool(getattr(sys, 'frozen', False))}"]
    failed = False
    checks: tuple[tuple[str, Callable[[], list[str]]], ...] = (
        ("bundled files", _bundled_files),
        ("compiled libraries", _compiled_libraries),
        ("Qt's parts", _qt_parts),
        ("the window", lambda: _whole_window(root)),
    )
    for name, check in checks:
        try:
            lines.append(f"ok    {name}: {', '.join(check())}")
        except Exception:  # noqa: BLE001 -- whatever broke is what the report is for
            failed = True
            lines.append(f"FAILED {name}:\n{traceback.format_exc()}")
    shutil.rmtree(root, ignore_errors=True)
    lines.append("SELF-TEST FAILED" if failed else "SELF-TEST PASSED")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
