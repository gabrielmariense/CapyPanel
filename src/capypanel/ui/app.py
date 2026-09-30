"""Starts Qt, wires up the core services and shows the main window."""

import logging
import sys
import traceback
from types import TracebackType

from PySide6.QtWidgets import QApplication, QMessageBox

from capypanel import __version__
from capypanel.core import applog, i18n, settings
from capypanel.core.i18n import _
from capypanel.ui.main_window.window import MainWindow

log = logging.getLogger(__name__)


def run(argv: list[str] | None = None) -> int:
    paths = settings.resolve_paths()
    settings.ensure_dirs(paths)
    applog.setup_logging(paths.log_dir)
    log.info("CapyPanel %s starting (portable=%s)", __version__, paths.portable)

    prefs = settings.load_settings(paths.settings_file)
    i18n.set_language(prefs.get("language", i18n.DEFAULT_LANGUAGE))

    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("CapyPanel")
    app.setApplicationVersion(__version__)
    sys.excepthook = _report_unexpected_error

    window = MainWindow(paths, prefs)
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
