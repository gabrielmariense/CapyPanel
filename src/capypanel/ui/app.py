"""Starts Qt, wires up the core services and shows the main window with every tool. It imports
no tool itself: the tool catalog loads them."""

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel import BUILD, __version__
from capypanel.core import applog, i18n, migration, settings
from capypanel.ui import branding, error_window, language
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import CATALOG

log = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    branding.use_own_taskbar_icon()  # before any window exists
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("CapyPanel")
    app.setWindowIcon(branding.app_icon())
    app.setApplicationVersion(__version__)
    sys.excepthook = error_window.report

    # Logging first, so a problem with the user's folder is logged and shown, not lost.
    paths = settings.resolve_paths()
    applog.setup_logging(paths.log_file)
    log.info("CapyPanel %s starting for %s (portable=%s)", BUILD, paths.account, paths.portable)
    try:
        settings.ensure_dirs(paths)
    except settings.UserFolderError as e:
        log.error("%s", e)
        QMessageBox.critical(None, "CapyPanel", str(e))
        return 1
    try:
        for copied in migration.migrate(paths):
            log.info("Copied from an older version: %s", copied)
    except OSError:
        log.exception("Couldn't copy files from an older version")
    prefs = settings.load_settings(paths.settings_file)
    tools = [info.load() for info in CATALOG]
    for tool in tools:
        tool.prepare(paths)  # e.g. the files it starts with
    language.apply(prefs.get("language", i18n.DEFAULT_LANGUAGE))  # before any window exists

    registry = themes.Registry()
    themes.apply(registry.find(prefs.get("theme")))
    window = MainWindow(paths, prefs, registry=registry, tools=tools)
    window.show()
    code = app.exec()
    log.info("CapyPanel exiting (code %s)", code)
    return code
