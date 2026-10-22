"""The main window: the shell that shows the tools. It owns the menu bar, the rail, the toolbar
area, the status bar, Settings, the theme and the language; each tool owns its toolbar, panels
and commands. The rail, View's tools, the toolbar, the tool and the status bar's text all follow
the tool shown. With none shown, the Home page fills the window. Only the tools that are on are
given to it; turning tools on or off restarts CapyPanel."""

import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QObject, QProcess, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel import BUILD
from capypanel.core import settings
from capypanel.core.i18n import _
from capypanel.ui import about, language
from capypanel.ui.dialogs import run_modal
from capypanel.ui.main_window.actions import create_actions, retranslate_actions
from capypanel.ui.main_window.home import HomePage
from capypanel.ui.main_window.rail import ToolRail
from capypanel.ui.main_window.tool import Tool, ToolKind
from capypanel.ui.menus import StayOpenMenu
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import CATALOG, ToolInfo
from capypanel.ui.tool_switches import ToolsDialog

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: settings.Paths,
        prefs: dict[str, Any],
        *,
        tools: Sequence[ToolKind],
        registry: themes.Registry | None = None,
        catalog: Sequence[ToolInfo] = CATALOG,
        start_again: Callable[[], None] | None = None,
    ):
        """tools: the tools that are on, in the rail's order. catalog: every tool CapyPanel
        has, for the Tools window. start_again: starts a new CapyPanel, on a restart."""
        super().__init__()
        self.paths = paths
        self.prefs = prefs
        self.registry = registry if registry is not None else themes.Registry()
        self.commands = create_actions(self)
        self.rail = ToolRail()
        self.rail.settings_requested.connect(lambda: self.open_settings())
        self.rail.home_requested.connect(self.show_home)
        self.rail.tool_picked.connect(self.show_tool)
        self._catalog = list(catalog)
        self._start_again = start_again or start_capypanel
        self.tools: dict[str, Tool] = {}
        # Each tool's toolbar on top of the tool, one page each; the page shown is the tool's.
        self._pages = QStackedWidget()
        self._tool_actions = QActionGroup(self)  # View's Home and tools: one shown at a time
        self._tool_actions.setExclusive(True)
        self._home_action = QAction(self)
        self._home_action.setCheckable(True)
        self._home_action.setShortcut(QKeySequence("Ctrl+0"))
        self._home_action.triggered.connect(lambda _c=False: self.show_home())
        self._tool_actions.addAction(self._home_action)
        self.addAction(self._home_action)
        self._status: dict[str, _StatusGroup] = {}  # each tool's, on the status bar's right
        self._page_of: dict[str, QWidget] = {}  # each tool's page: its toolbar and the tool
        for make in tools:
            self._add_tool(make(self))
        self._shown: str | None = None  # the tool shown; None: Home
        self.home = HomePage([info for info in self._catalog if info.tool_id in self.tools])
        self.home.tool_picked.connect(self.show_tool)
        self.home.choose_tools.connect(self.choose_tools)
        self._pages.insertWidget(0, self.home)
        self.home.show_mascot(self.prefs.get(settings.HOME_MASCOT_KEY) is not False)

        # The rail runs down the left edge; the tool shown, its toolbar on top, fills the rest.
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.rail)
        row.addWidget(self._pages, 1)
        self.setCentralWidget(central)

        self._build_menus()
        self._connect()
        self._restore_layout()
        # Home, unless the user picked a tool, or the tool shown last, in Settings.
        start = self.prefs.get(settings.START_KEY, settings.START_HOME)
        if start == settings.START_LAST:
            start = self.prefs.get(settings.TOOL_KEY)
        self._show(start if isinstance(start, str) and start in self.tools else None)

    def _add_tool(self, tool: Tool) -> None:
        tool_id = tool.TOOL_ID
        self.tools[tool_id] = tool
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(tool.toolbar)
        column.addWidget(tool, 1)
        self._pages.addWidget(page)
        self._page_of[tool_id] = page
        self.rail.add_tool(tool_id, tool.ICON)
        action = QAction(self)
        action.setCheckable(True)
        action.setData(tool_id)
        if len(self.tools) <= 9:
            action.setShortcut(QKeySequence(f"Ctrl+{len(self.tools)}"))
        action.triggered.connect(lambda _c=False: self.show_tool(tool_id))
        self._tool_actions.addAction(action)
        self.addAction(action)  # its shortcut works wherever the focus is
        self.statusBar().addWidget(tool.status_label, 1)
        right = _StatusGroup(tool.status_widgets())
        self.statusBar().addPermanentWidget(right)
        self._status[tool_id] = right
        tool.title_changed.connect(lambda _name, t=tool_id: self._title_changed(t))

    def shown_tool(self) -> Tool | None:
        """None while Home is shown."""
        return None if self._shown is None else self.tools[self._shown]

    def show_tool(self, tool_id: str) -> None:
        self._show(tool_id)

    def show_home(self) -> None:
        self._show(None)

    def _show(self, tool_id: str | None) -> None:
        """The rail, View's tools, the toolbar, the tool and the status bar follow. Home has
        no toolbar and nothing on the status bar."""
        self._shown = tool_id
        tool = self.shown_tool()
        self._pages.setCurrentWidget(self.home if tool_id is None else self._page_of[tool_id])
        self.rail.show_tool(tool_id)
        self._home_action.setChecked(tool_id is None)
        for action in self._tool_list_actions():
            action.setChecked(action.data() == tool_id)
        for other_id, other in self.tools.items():
            other.status_label.setVisible(other_id == tool_id)
            self._status[other_id].set_shown(other_id == tool_id)
        self._fill_view_menu()
        self._show_title(tool.title() if tool is not None else "")
        if tool is not None:
            tool.align_toolbar_later()
            self.prefs[settings.TOOL_KEY] = tool_id

    def _tool_list_actions(self) -> list[QAction]:
        """View's tools, without Home."""
        return [a for a in self._tool_actions.actions() if a is not self._home_action]

    # ---- what tools ask of the shell ----

    def tool_prefs(self, tool_id: str, *, inherit: bool = False) -> dict[str, Any]:
        return settings.tool_prefs(self.prefs, tool_id, inherit=inherit)

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

    # ---- turning tools on and off ----

    def choose_tools(self) -> None:
        dialog = ToolsDialog(self, tools=self._catalog, on=self.tools)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self.restart(dialog.off())

    def restart(self, off: list[str]) -> None:
        """Turns those tools off and the others on, closes as on exit (everything saved),
        and starts CapyPanel again: tools that are off aren't loaded at all."""
        self.prefs[settings.TOOLS_OFF_KEY] = off
        self.save_prefs()
        QTimer.singleShot(0, self, self._close_and_start_again)  # once Settings has closed

    def _close_and_start_again(self) -> None:
        if self.close():
            log.info("Restarting, tools off: %s", self.prefs[settings.TOOLS_OFF_KEY])
            self._start_again()
            QApplication.quit()

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
        # A tool's own commands live in its toolbar: the menu bar is the same for every tool.
        self._view_menu = StayOpenMenu(self)
        bar.addMenu(self._view_menu)
        self._help_menu = bar.addMenu("")
        self._help_menu.addActions([a.documentation, a.report_problem])
        self._help_menu.addSeparator()
        self._help_menu.addAction(a.about)
        self._retranslate_menus()

    def _fill_view_menu(self) -> None:
        """Home and the tools first, then the shown tool's panels, then the window's parts;
        theme and language are in Settings."""
        menu = self._view_menu
        for action in menu.actions():  # not clear(): it deletes the tools' own actions
            menu.removeAction(action)
            if action.isSeparator():
                action.deleteLater()  # the menu's own
        menu.addAction(self._home_action)
        menu.addSeparator()
        menu.addActions(self._tool_list_actions())
        tool = self.shown_tool()
        for group in tool.view_actions() if tool is not None else []:
            menu.addSeparator()
            menu.addActions(group)
        menu.addSeparator()
        menu.addActions([self.commands.show_toolbar, self.commands.show_status_bar])

    def _retranslate_menus(self) -> None:
        retranslate_actions(self.commands)
        self.rail.retranslate()
        for index, (tool_id, tool) in enumerate(self.tools.items(), start=1):
            self.rail.buttons[tool_id].setToolTip(f"{tool.tool_name()} (Ctrl+{index})")
        self._home_action.setText(_("Hom&e"))
        for action in self._tool_list_actions():
            action.setText(self.tools[str(action.data())].menu_name())
        self._file_menu.setTitle(_("&File"))
        self._view_menu.setTitle(_("&View"))
        self._help_menu.setTitle(_("&Help"))

    def _connect(self) -> None:
        a = self.commands
        a.settings.triggered.connect(lambda: self.open_settings())
        a.exit.triggered.connect(self.close)
        a.documentation.triggered.connect(lambda: about.open_url(about.docs_url()))
        a.report_problem.triggered.connect(
            lambda: about.open_url(about.report_url(self.paths.portable))
        )
        a.about.triggered.connect(lambda: self.open_settings("about"))  # About is a page there
        a.show_toolbar.toggled.connect(self._show_toolbars)
        a.show_status_bar.toggled.connect(self.statusBar().setVisible)

    def _show_toolbars(self, shown: bool) -> None:
        for tool in self.tools.values():
            tool.toolbar.setVisible(shown)
        self._align_toolbar()

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
        self._show_toolbars(self.commands.show_toolbar.isChecked())
        self.statusBar().setVisible(self.commands.show_status_bar.isChecked())

    def _view_choices(self) -> dict[str, QAction]:
        """The shell's View menu ticks, by the key they're saved under."""
        a = self.commands
        return {"toolbar": a.show_toolbar, "status_bar": a.show_status_bar}

    def _align_toolbar(self) -> None:
        if (tool := self.shown_tool()) is not None:
            tool.align_toolbar_later()

    def _title_changed(self, tool_id: str) -> None:
        if tool_id == self._shown:
            self._show_title(self.tools[tool_id].title())

    def _show_title(self, name: str) -> None:
        app = f"CapyPanel {BUILD}"
        self.setWindowTitle(f"{name} — {app}" if name else app)

    # ---- settings ----

    def settings_dialog(self) -> SettingsDialog:
        """Settings, wired up: every choice applies as it's made, with no Save."""
        groups = [g for t in self.tools.values() if (g := t.settings_group()) is not None]
        start = self.prefs.get(settings.START_KEY)
        dialog = SettingsDialog(
            self,
            paths=self.paths,
            registry=self.registry,
            groups=groups,
            tools=self._catalog,
            tools_on=self.tools,
            start=start if isinstance(start, str) else settings.START_HOME,
            mascot=self.prefs.get(settings.HOME_MASCOT_KEY) is not False,
        )
        dialog.language_picked.connect(self.set_language)
        dialog.theme_picked.connect(self.set_theme)
        dialog.start_picked.connect(self._set_start)
        dialog.mascot_picked.connect(self._set_mascot)
        dialog.restart_picked.connect(lambda off: (dialog.done(0), self.restart(off)))
        return dialog

    def _set_start(self, start: str) -> None:
        self.prefs[settings.START_KEY] = start
        self.save_prefs()

    def _set_mascot(self, shown: bool) -> None:
        self.prefs[settings.HOME_MASCOT_KEY] = shown
        self.save_prefs()
        self.home.show_mascot(shown)

    # ---- look ----

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)
        for tool in self.tools.values():
            tool.restyle()  # icon colours, the font's size, the toolbar's padding
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
        self.home.retranslate()
        for tool in self.tools.values():
            tool.retranslate()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)  # the window handle only exists once it's shown
        self._align_toolbar()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._align_toolbar()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.prefs["window_geometry"] = self.saveGeometry().toBase64().toStdString()
        for tool in self.tools.values():
            tool.save_state()
        self.prefs["view"] = {k: a.isChecked() for k, a in self._view_choices().items()}
        self.save_prefs()
        super().closeEvent(event)


def start_capypanel() -> None:
    """A new CapyPanel, started the way this one was: the packaged app, or from source (with
    pythonw, so no console window opens)."""
    if getattr(sys, "frozen", False):
        QProcess.startDetached(sys.executable, sys.argv[1:])
        return
    windowless = Path(sys.executable).with_name("pythonw.exe")
    python = windowless if windowless.exists() else Path(sys.executable)
    QProcess.startDetached(str(python), ["-m", "capypanel", *sys.argv[1:]])


class _StatusGroup(QWidget):
    """A tool's widgets on the status bar's right. Shown only while its tool is and one of them
    is: an empty group would still draw a separator line in some themes."""

    def __init__(self, widgets: list[QWidget]) -> None:
        super().__init__()
        self._widgets = widgets
        self._shown = True
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        for widget in widgets:
            row.addWidget(widget)
            widget.installEventFilter(self)
            # As tall as they are even while hidden, so the bar never changes height.
            self.setMinimumHeight(max(self.minimumHeight(), widget.sizeHint().height()))
        self._update()

    def set_shown(self, shown: bool) -> None:
        self._shown = shown
        self._update()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.ShowToParent, QEvent.Type.HideToParent):
            self._update()
        return False

    def _update(self) -> None:
        self.setVisible(self._shown and any(not w.isHidden() for w in self._widgets))
