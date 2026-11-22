import shutil
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path

PYTE_NOTICES = ("LICENSE", "AUTHORS", "CHANGES-CAPYPANEL.txt")
CONPTY_FILES = ("conpty.dll", "OpenConsole.exe", "LICENSE", "NOTICE.md", "CHANGES-CAPYPANEL.txt")
TERMINAL_WORDS = "self-test ─┼█"


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
    import hashlib
    import ssl

    import pythoncom  # noqa: F401
    import pywintypes  # noqa: F401
    import win32com.client  # noqa: F401
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from PySide6.QtCore import QByteArray
    from PySide6.QtNetwork import QLocalServer  # noqa: F401
    from PySide6.QtSvg import QSvgRenderer

    from capypanel.core.printers import usm

    encryptor = Cipher(algorithms.AES(bytes(16)), CFB(bytes(16))).encryptor()
    if len(encryptor.update(b"capypanel") + encryptor.finalize()) != 9:
        raise RuntimeError("cryptography: AES gave another length")
    svg = QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    if not QSvgRenderer(svg).isValid():
        raise RuntimeError("QtSvg can't read an SVG")
    import truststore

    if not ssl.create_default_context().cert_store_stats()["x509_ca"]:
        raise RuntimeError("Python's TLS found no certificate of Windows to trust")
    if not truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT).check_hostname:
        raise RuntimeError("truststore: the update check's TLS doesn't check the host name")
    for auth in usm.Auth:  # SNMP v3 signs with these, by name: an OpenSSL can come without one
        hashlib.new(auth.hash_name, b"capypanel").digest()
    return [
        "pywin32",
        "cryptography",
        "QtSvg",
        "QtNetwork",
        "TLS",
        "truststore",
        "SNMP v3's hashes",
    ]


def _qt_parts() -> list[str]:
    """Qt's plugins and translations: a build can leave them out without any error."""
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


def _terminal(root: Path) -> list[str]:
    """Runs cmd.exe on the pseudo console, never ssh.exe, which would reach the network."""
    import os
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from capypanel.ui.ssh_tool.terminal.tab import TerminalTab
    from capypanel.vendor import pyte

    folder = Path(pyte.__file__).parent
    missing = [name for name in PYTE_NOTICES if not (folder / name).is_file()]
    if missing:
        raise RuntimeError(f"pyte's {', '.join(missing)} missing from {folder}")
    app = QApplication.instance() or QApplication([])
    tab = TerminalTab(host="self-test")
    tab.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    tab.resize(640, 320)
    tab.show()
    ended: list[object] = []
    tab.view.ended.connect(ended.append)
    try:
        cmd = os.environ.get("COMSPEC", "cmd.exe")
        tab.start([cmd, "/d", "/c", f"echo {TERMINAL_WORDS}& exit 7"], cwd=str(root))
        deadline = time.monotonic() + 30
        while not ended:
            if time.monotonic() > deadline:
                raise RuntimeError("cmd.exe on the pseudo console never ended")
            app.processEvents()
            time.sleep(0.01)
        rows = tab.view.term.screen_text()
        if ended != [7] or TERMINAL_WORDS not in rows:
            shown = [row for row in rows if row]
            raise RuntimeError(f"cmd.exe ended with {ended}; the screen shows {shown}")
        if tab.grab().isNull() or not tab.ended:
            raise RuntimeError("the tab drew nothing, or showed no strip after the end")
    finally:
        tab.close_connection()
        tab.close()
        app.processEvents()
    return ["pseudo console", "screen", "drawing", "pyte's notices"]


def _console_engine(root: Path) -> list[str]:
    import os
    import time

    from capypanel.core.ssh import conpty
    from capypanel.core.ssh.screen import TermScreen, TermStream

    folder = conpty.CARRIED_DIR
    missing = [name for name in CONPTY_FILES if not (folder / name).is_file()]
    if missing:
        raise RuntimeError(f"{', '.join(missing)} missing from {folder}")
    engine = conpty.carried_engine()
    if engine is None:
        raise RuntimeError(f"the console engine in {folder} won't load")
    screen = TermScreen(80, 25)
    stream = TermStream(screen)
    ended: list[int] = []
    cmd = os.environ.get("COMSPEC", "cmd.exe")
    console = conpty.PseudoConsole(
        [cmd, "/d", "/c", f"echo {TERMINAL_WORDS}& exit 7"],
        80,
        25,
        on_ready=lambda: None,
        on_exit=ended.append,
        cwd=str(root),
        engine=engine,
    )
    deadline = time.monotonic() + 30
    try:
        while not ended:
            if time.monotonic() > deadline:
                raise RuntimeError("cmd.exe on the console engine never ended")
            stream.feed(console.take(1 << 20))
            time.sleep(0.01)
    finally:
        console.close()
    while not console.at_eof and time.monotonic() < deadline:
        stream.feed(console.take(1 << 20))
        time.sleep(0.01)
    if console.engine is not engine:
        raise RuntimeError("the console engine didn't start: Windows' own ran instead")
    if ended != [7] or TERMINAL_WORDS not in screen.screen_text():
        shown = [row for row in screen.screen_text() if row]
        raise RuntimeError(f"cmd.exe ended with {ended}; the screen shows {shown}")
    return ["cmd.exe", "its notices"]


def run(report: Path) -> int:
    from capypanel import BUILD

    root = Path(tempfile.mkdtemp(prefix="capypanel-self-test-"))
    lines = [f"CapyPanel {BUILD}", f"packaged: {bool(getattr(sys, 'frozen', False))}"]
    failed = False
    checks: tuple[tuple[str, Callable[[], list[str]]], ...] = (
        ("bundled files", _bundled_files),
        ("compiled libraries", _compiled_libraries),
        ("Qt's parts", _qt_parts),
        ("the window", lambda: _whole_window(root)),
        ("the SSH terminal", lambda: _terminal(root)),
        ("Windows 10's console engine", lambda: _console_engine(root)),
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
