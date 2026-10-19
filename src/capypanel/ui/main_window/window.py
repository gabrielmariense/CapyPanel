"""The main window: the shell that shows the tools. It owns the menu bar, the rail, the toolbar
area, the status bar, Settings, the theme and the language; each tool owns its toolbar, panels
and commands."""

import logging
from typing import Any

from PySide6.QtCore import QByteArray, QEvent
from PySide6.QtGui import QAction, QCloseEvent, QResizeEvent, QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from capypanel import BUILD
from capypanel.core import settings
from capypanel.core.i18n import _
from capypanel.ui import about, language
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.main_window.actions import create_actions, retranslate_actions
from capypanel.ui.main_window.rail import ToolRail
from capypanel.ui.menus import StayOpenMenu
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.themes import engine as themes

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: settings.Paths,
        prefs: dict[str, Any],
        *,
        registry: themes.Registry | None = None,
    ):
        super().__init__()
        self.paths = paths
        self.prefs = prefs
        self.registry = registry if registry is not None else themes.Registry()
        self.commands = create_actions(self)
        self.rail = ToolRail()
        self.rail.settings_requested.connect(lambda: self.open_settings())
        self.hosts = HostsTool(self)

        # The rail runs down the left edge; the tool, its toolbar on top, fills the rest.
        tool = QWidget()
        column = QVBoxLayout(tool)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.hosts.toolbar)
        column.addWidget(self.hosts, 1)
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.rail)
        row.addWidget(tool, 1)
        self.setCentralWidget(central)
        self.statusBar().addWidget(self.hosts.status_label, 1)
        for widget in self.hosts.status_widgets():
            self.statusBar().addPermanentWidget(widget)

        self._build_menus()
        self._connect()
        self._restore_layout()
        self.hosts.title_changed.connect(self._show_title)
        self._show_title(self.hosts.title())

    # ---- what tools ask of the shell ----

    def save_prefs(self) -> None:
        try:
            settings.save_settings(self.paths.settings_file, self.prefs)
        except OSError:
            log.exception("Couldn't save settings")

    def show_message(self, text: str, timeout: int = 5000) -> None:
        self.statusBar().showMessage(text, timeout)

    def open_settings(self, page: str | None = None) -> None:
        dialog = self.settings_dialog()
        geometry = self.prefs.get("settings_geometry")
        if isinstance(geometry, str):
            dialog.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        if page:
            dialog.show_page(page)
        run_modal(dialog)
        self.prefs["settings_geometry"] = dialog.saveGeometry().toBase64().toStdString()
        self.save_prefs()

    # ---- building ----

    def _build_menus(self) -> None:
        """Menus are built without text; retranslate() fills it in, now and on every switch."""
        a = self.commands
        bar = self.menuBar()
        self._file_menu = bar.addMenu("")
        # Lists are the tools': they're in each tool's list dropdown, not here.
        self._file_menu.addAction(a.settings)
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.exit)

        # It stays open while parts are ticked, so several can be shown or hidden in one go.
        # The tools first, then the shown tool's panels; theme and language are in Settings.
        # A tool's own commands live in its toolbar: the menu bar is the same for every tool.
        self._view_menu = StayOpenMenu(self)
        bar.addMenu(self._view_menu)
        a.show_hosts.setChecked(True)  # the only tool for now
        self._view_menu.addAction(a.show_hosts)
        for group in self.hosts.view_actions():
            self._view_menu.addSeparator()
            self._view_menu.addActions(group)
        self._view_menu.addSeparator()
        self._view_menu.addActions([a.show_toolbar, a.show_status_bar])

        self._help_menu = bar.addMenu("")
        self._help_menu.addActions([a.documentation, a.report_problem])
        self._help_menu.addSeparator()
        self._help_menu.addAction(a.about)
        self._retranslate_menus()

    def _retranslate_menus(self) -> None:
        retranslate_actions(self.commands)
        self.rail.retranslate()
        self._file_menu.setTitle(_("&File"))
        self._view_menu.setTitle(_("&View"))
        self._help_menu.setTitle(_("&Help"))

    def _connect(self) -> None:
        a = self.commands
        a.settings.triggered.connect(lambda: self.open_settings())
        a.exit.triggered.connect(self.close)
        a.show_hosts.triggered.connect(lambda: self._show_tool("hosts"))
        self.rail.hosts_button.clicked.connect(lambda: self._show_tool("hosts"))
        a.documentation.triggered.connect(lambda: about.open_url(about.docs_url()))
        a.report_problem.triggered.connect(
            lambda: about.open_url(about.report_url(self.paths.portable))
        )
        a.about.triggered.connect(lambda: self.open_settings("about"))  # About is a page there
        a.show_toolbar.toggled.connect(self.hosts.toolbar.setVisible)
        a.show_toolbar.toggled.connect(self.hosts.align_toolbar_later)
        a.show_status_bar.toggled.connect(self.statusBar().setVisible)

    def _restore_layout(self) -> None:
        geometry = self.prefs.get("window_geometry")
        if not (
            isinstance(geometry, str)
            and self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        ):
            self.resize(1100, 700)
        view = self.prefs.get("view")
        view = view if isinstance(view, dict) else {}
        for key, action in self._view_choices().items():
            action.setChecked(bool(view.get(key, True)))
        self.hosts.toolbar.setVisible(self.commands.show_toolbar.isChecked())
        self.statusBar().setVisible(self.commands.show_status_bar.isChecked())

    def _view_choices(self) -> dict[str, QAction]:
        """The shell's View menu ticks, by the key they're saved under."""
        a = self.commands
        return {"toolbar": a.show_toolbar, "status_bar": a.show_status_bar}

    def reset_layout(self) -> None:
        """Settings > Window layout: default panel sizes, columns and hidden parts shown again.
        The window's size, the theme and every other setting stay."""
        for action in (self.commands.show_toolbar, self.commands.show_status_bar):
            action.setChecked(True)
        self.hosts.reset_layout()

    def _show_tool(self, tool: str) -> None:
        """The rail and View > tools agree on the tool shown (Hosts is the only one for now)."""
        self.commands.show_hosts.setChecked(tool == "hosts")
        self.rail.hosts_button.setChecked(tool == "hosts")

    def _show_title(self, name: str) -> None:
        self.setWindowTitle(f"{name} — CapyPanel {BUILD}" if name else f"CapyPanel {BUILD}")

    # ---- settings ----

    def settings_dialog(self) -> SettingsDialog:
        """Settings, wired up: every choice applies as it's made, with no Save."""
        dialog = SettingsDialog(
            self, paths=self.paths, registry=self.registry, **self.hosts.settings_values()
        )
        dialog.language_picked.connect(self.set_language)
        dialog.theme_picked.connect(self.set_theme)
        dialog.layout_reset_requested.connect(self.reset_layout)
        self.hosts.wire_settings(dialog)
        return dialog

    # ---- look ----

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)
        self.hosts.restyle()  # icon colours, the font's size, the toolbar's padding
        self.prefs["theme"] = theme.id
        self.save_prefs()
        log.info("Theme: %s", theme.id)

    def set_language(self, code: str) -> None:
        """Switches live: Qt then sends every window a LanguageChange event (see changeEvent)."""
        code = language.apply(code)
        self.prefs["language"] = code
        self.save_prefs()
        log.info("Language: %s", code)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        """Every text this window shows, in the current language."""
        self._retranslate_menus()
        self.hosts.retranslate()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)  # the window handle only exists once it's shown
        self.hosts.align_toolbar_later()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.hosts.align_toolbar_later()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.prefs["window_geometry"] = self.saveGeometry().toBase64().toStdString()
        self.hosts.save_state()
        choices = {**self._view_choices(), **self.hosts.view_choices()}
        self.prefs["view"] = {k: a.isChecked() for k, a in choices.items()}
        self.save_prefs()
        super().closeEvent(event)
