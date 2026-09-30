"""The main window. For now: menus, an empty centre and the status bar."""

from typing import Any

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import QLabel, QMainWindow

from capypanel import __version__
from capypanel.core import settings
from capypanel.core.i18n import _


class MainWindow(QMainWindow):
    def __init__(self, paths: settings.Paths, prefs: dict[str, Any]) -> None:
        super().__init__()
        self._paths = paths
        self._prefs = prefs
        self.setWindowTitle(f"CapyPanel {__version__}")

        self._build_menus()
        placeholder = QLabel(_("No host list is open yet."))
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(placeholder)
        if paths.portable:
            self.statusBar().showMessage(_("Portable mode: settings are kept next to the app."))
        else:
            self.statusBar().showMessage(_("Ready"))
        self._restore_geometry()

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(_("&File"))
        exit_action = QAction(_("E&xit"), self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    def _restore_geometry(self) -> None:
        saved = self._prefs.get("window_geometry")
        if not (
            isinstance(saved, str) and self.restoreGeometry(QByteArray.fromBase64(saved.encode()))
        ):
            self.resize(1100, 700)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._prefs["window_geometry"] = self.saveGeometry().toBase64().toStdString()
        settings.save_settings(self._paths.settings_file, self._prefs)
        super().closeEvent(event)
