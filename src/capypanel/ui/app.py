"""Starts Qt, wires up the core services and shows the main window."""

import logging
import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel import BUILD, __version__
from capypanel.core import applog, i18n, migration, settings
from capypanel.core.i18n import _
from capypanel.ui import language
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("CapyPanel")
    app.setApplicationVersion(__version__)
    sys.excepthook = _report_unexpected_error

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
    language.apply(prefs.get("language", i18n.DEFAULT_LANGUAGE))  # before any window exists

    registry = themes.Registry()
    themes.apply(registry.find(prefs.get("theme")))
    window = MainWindow(paths, prefs, registry=registry)
    window.show()
    code = app.exec()
    log.info("CapyPanel exiting (code %s)", code)
    return code


def _report_unexpected_error(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    # Log first: the dialog is for the user, the log is what a bug report needs.
    log.critical("Unexpected error", exc_info=(exc_type, exc, tb))
    box = QMessageBox(
        QMessageBox.Icon.Critical,
        _("Unexpected error"),
        _("Something went wrong. The details were saved to the app log."),
    )
    box.setDetailedText("".join(traceback.format_exception(exc_type, exc, tb)))
    box.exec()
