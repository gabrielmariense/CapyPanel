"""The main window: the shell that shows the tools. It owns the menu bar, the rail, the toolbar
area, the status bar, Settings, the theme and the language; each tool owns its toolbar, panels
and commands. The rail, View's tools, the toolbar, the tool and the status bar's text all follow
the tool shown. With none shown, the Home page fills the window."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QObject, QRect, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QGuiApplication,
    QKeySequence,
    QPalette,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel import __version__
from capypanel.core import settings
from capypanel.core.i18n import _, pgettext
from capypanel.ui import language, spacing
from capypanel.ui.dialogs import run_modal
from capypanel.ui.guides import Guide, GuideRunner, Step, on_screen, seen_from
from capypanel.ui.icons import tabler_icon
from capypanel.ui.main_window.actions import create_actions, retranslate_actions
from capypanel.ui.main_window.home import HomePage
from capypanel.ui.main_window.rail import ToolRail
from capypanel.ui.main_window.tool import Tool, ToolKind
from capypanel.ui.main_window.tray import Tray, ask_closing
from capypanel.ui.menus import StayOpenMenu
from capypanel.ui.saved_credentials import KeptLogin, SavedCredentialsDialog
from capypanel.ui.settings.window import HEIGHT as SETTINGS_HEIGHT
from capypanel.ui.settings.window import WIDTH as SETTINGS_WIDTH
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import CATALOG, ToolInfo
from capypanel.ui.updater import Updater

log = logging.getLogger(__name__)
OFFER_RETRY_MS = 2000  # a found update waits this long between tries while something is in the way


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: settings.Paths,
        prefs: dict[str, Any],
        *,
        tools: Sequence[ToolKind],
        registry: themes.Registry | None = None,
        catalog: Sequence[ToolInfo] = CATALOG,
    ):
        """tools: in the rail's order. catalog: what Home and Settings show of each tool."""
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
        self._badges: dict[str, int] = {}  # each tool's count of items needing attention
        self.tray = Tray(self)
        self._in_tray = False  # the window's X sent it to the tray
        self._quitting = False  # Quit CapyPanel: the X's choice isn't asked
        self._notified_by: str | None = None  # the tool behind the last notification
        self._page_of: dict[str, QWidget] = {}  # each tool's page: its toolbar and the tool
        for make in tools:
            self._add_tool(make(self))
        self._shown: str | None = None  # the tool shown; None: Home
        self.home = HomePage(self._infos())
        self.home.tool_picked.connect(self.show_tool)
        self._pages.insertWidget(0, self.home)

        # The rail runs down the left edge; the tool shown, its toolbar on top, fills the rest.
        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.rail)
        row.addWidget(self._pages, 1)
        self.setCentralWidget(central)

        self.updater = Updater(self.prefs, self.save_prefs, self.paths.company_tools_dir, self)
        self._update_shown = ""  # the version whose window opened in this run: once is enough
        self.guides = GuideRunner(self, seen_from(self.prefs), self.save_prefs, _docs_page)
        self._tools_agreed = False  # an update asked the tools already: closing asks no more
        self._build_menus()
        self._connect()
        self._connect_tray()
        themes.switches().switched.connect(self._restyle)
        self._restore_layout()
        # Home, unless the user picked a tool, or the tool shown last, in Settings.
        start = self.prefs.get(settings.START_KEY, settings.START_HOME)
        if start == settings.START_LAST:
            start = self.prefs.get(settings.TOOL_KEY)
        start = start if isinstance(start, str) and start in self.tools else None
        if start is not None and self.tools[start].first_use_pending():
            start = None  # its warning comes first, from Home, once the window shows
        self._show(start)

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
        tool.badge_changed.connect(lambda count, t=tool_id: self._badge_changed(t, count))
        tool.notify_requested.connect(lambda title, text, t=tool_id: self._notify(t, title, text))

    def shown_tool(self) -> Tool | None:
        """None while Home is shown."""
        return None if self._shown is None else self.tools[self._shown]

    def show_tool(self, tool_id: str) -> None:
        self._show(tool_id)

    def show_home(self) -> None:
        self._show(None)

    def _show(self, tool_id: str | None) -> None:
        """The rail, View's tools, the toolbar, the tool and the status bar follow. Home has
        no toolbar and nothing on the status bar. A tool's first-use warning comes before its
        first showing; its guide after, the first time."""
        if tool_id is not None and on_screen(self):
            tool = self.tools[tool_id]
            if tool.first_use_pending() and not tool.first_use_warning(self):
                self.rail.show_tool(self._shown)  # Cancel: where it was
                return
        if self.guides.running and self.guides.running != (tool_id or "home"):
            self.guides.stop()  # left its screen: it shows again the next time
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
        self._guide_now()
        if tool is not None:
            tool.align_toolbar_later()
            self.prefs[settings.TOOL_KEY] = tool_id

    def _infos(self) -> list[ToolInfo]:
        """The catalog's entries for the window's tools, in the rail's order."""
        return [info for info in self._catalog if info.tool_id in self.tools]

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
        opens_at = [SETTINGS_WIDTH, SETTINGS_HEIGHT]
        # A size kept while Settings opened at another one was never a choice against this
        # one: the new opening size shows once, and what the person makes of it is kept.
        if isinstance(geometry, str) and self.prefs.get("settings_opens_at") == opens_at:
            dialog.own_size = dialog.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        if page:
            dialog.show_page(page)
        run_modal(dialog)
        self.prefs["settings_geometry"] = dialog.saveGeometry().toBase64().toStdString()
        self.prefs["settings_opens_at"] = opens_at
        self.save_prefs()
        self._update_tray()  # Refresh on its own may have been switched on or off

    def kept_logins(self) -> list[KeptLogin]:
        return [login for tool in self.tools.values() for login in tool.kept_logins()]

    def tool(self, tool_id: str) -> Tool | None:
        return self.tools.get(tool_id)

    def open_saved_credentials(self, parent: QWidget | None = None) -> None:
        run_modal(SavedCredentialsDialog(parent or self, self.kept_logins))
        if isinstance(parent, SettingsDialog):  # its pages show what's kept
            parent.credentials_changed()

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
        self._help_menu.addActions(
            [a.show_guide, a.show_all_guides, a.documentation, a.report_problem]
        )
        self._help_menu.addSeparator()
        self._help_menu.addActions([a.check_updates, a.about])
        # A newer release: a button at the menu bar's right end, the same in every tool.
        self.update_button = QToolButton()
        self.update_button.setObjectName("updateButton")
        self.update_button.setAutoRaise(True)
        self.update_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.update_button.clicked.connect(lambda: self.open_updates())
        self.update_button.hide()
        bar.setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)
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
        for tool_id in self.tools:
            self._rail_tip(tool_id)
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
        a.documentation.triggered.connect(self._open_docs)
        a.report_problem.triggered.connect(self._report_problem)
        a.about.triggered.connect(lambda: self.open_settings("about"))  # About is a page there
        a.check_updates.triggered.connect(lambda: self.open_updates())
        a.show_guide.triggered.connect(lambda: self._guide_now(force=True))
        a.show_all_guides.triggered.connect(self.show_all_guides_again)
        self.updater.changed.connect(self._show_update_button)
        self.updater.found.connect(self._offer_update)
        a.show_toolbar.toggled.connect(self._show_toolbars)
        a.show_status_bar.toggled.connect(self.statusBar().setVisible)

    # About's code is loaded when first needed, not at every start: it looks up each library.
    def _open_docs(self) -> None:
        from capypanel.ui import about

        about.open_url(about.docs_url())

    def _report_problem(self) -> None:
        from capypanel.ui import about

        about.open_url(about.report_url(self.paths.portable))

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

    def _badge_changed(self, tool_id: str, count: int) -> None:
        self._badges[tool_id] = count
        self.rail.set_badge(tool_id, count)
        self._rail_tip(tool_id)
        self._tray_counts()

    def _rail_tip(self, tool_id: str) -> None:
        """The rail icon's tip, "Printers (Ctrl+2)", and under it what the red count means,
        while there's one."""
        tool, index = self.tools[tool_id], list(self.tools).index(tool_id) + 1
        tip = f"{tool.tool_name()} (Ctrl+{index})"
        count = self._badges.get(tool_id, 0)
        if count and (meaning := tool.attention_text(count)):
            tip = "\n".join((tip, meaning))
        self.rail.buttons[tool_id].setToolTip(tip)

    def _title_changed(self, tool_id: str) -> None:
        if tool_id == self._shown:
            self._show_title(self.tools[tool_id].title())

    def _show_title(self, name: str) -> None:
        """The title, e.g. "Clinic — CapyPanel 0.26.1": the version only; About has the build."""
        app = f"CapyPanel {__version__}"
        self.setWindowTitle(f"{name} — {app}" if name else app)

    # ---- settings ----

    def settings_dialog(self) -> SettingsDialog:
        """Settings, wired up: every choice applies as it's made, with no Save."""
        groups = [g for t in self.tools.values() if (g := t.settings_group()) is not None]
        start = self.prefs.get(settings.START_KEY)
        closing = self.prefs.get(settings.CLOSE_KEY)
        dialog = SettingsDialog(
            self,
            paths=self.paths,
            registry=self.registry,
            groups=groups,
            tools=self._infos(),
            start=start if isinstance(start, str) else settings.START_HOME,
            updates=self.updater.how_often(),
            updates_editable=self.updater.can_set(),
            # What's saved, so the page shows it, and picking "Ask" again is a change it saves.
            closing=closing if isinstance(closing, str) else settings.CLOSE_ASK,
        )
        dialog.language_picked.connect(self.set_language)
        dialog.theme_picked.connect(self.set_theme)
        dialog.start_picked.connect(self._set_start)
        dialog.closing_picked.connect(self._set_closing)
        dialog.updates_picked.connect(lambda how: self._set_update_checks(how, dialog))
        dialog.about.updates_button.clicked.connect(lambda: self.open_updates(dialog))
        return dialog

    def _set_update_checks(self, how: str, dialog: SettingsDialog) -> None:
        try:
            self.updater.set_how_often(how)
        except OSError as e:
            dialog.general.show_updates(self.updater.how_often())
            text = _("Couldn't save how often to check: {error}").format(error=e)
            QMessageBox.warning(dialog, _("Settings"), text)

    def _set_start(self, start: str) -> None:
        self.prefs[settings.START_KEY] = start
        self.save_prefs()

    def _set_closing(self, closing: str) -> None:
        self.prefs[settings.CLOSE_KEY] = closing
        self.save_prefs()

    # ---- the tray ----

    def _connect_tray(self) -> None:
        self.tray.open_requested.connect(self.open_from_tray)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.attention_requested.connect(self._show_attention)
        self.tray.message_clicked.connect(self._notification_clicked)
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.commitDataRequest.connect(self._session_ending)
        self._update_tray()

    def _session_ending(self, _manager: object) -> None:
        """Windows is logging off or shutting down: the X then quits, with no question and no
        tray, so CapyPanel never holds the shutdown up."""
        self._quitting = True

    def _update_tray(self) -> None:
        """The tray icon shows while the window is in the tray, or while a tool works on its
        own: its notifications need it."""
        working = any(t.works_in_background() for t in self.tools.values())
        self.tray.set_shown(self._in_tray or working)

    def _tray_counts(self) -> None:
        self.tray.set_counts(
            {t: (n, self.tools[t].attention_text(n)) for t, n in self._badges.items()}
        )

    def _notify(self, tool_id: str, title: str, text: str) -> None:
        self._notified_by = tool_id
        self.tray.set_shown(True)  # already shown while a tool works on its own
        self.tray.notify(title, text)

    def _notification_clicked(self) -> None:
        if self._notified_by is not None:
            self._show_attention(self._notified_by)
        else:
            self.open_from_tray()

    def _show_attention(self, tool_id: str) -> None:
        """The tool, listing just its items needing attention."""
        self.open_from_tray()
        self.show_tool(tool_id)
        self.tools[tool_id].show_attention()

    def to_tray(self) -> None:
        """Hidden, still running: the tools' Refresh on its own and warnings go on."""
        self._save_state()
        self._in_tray = True
        QApplication.setQuitOnLastWindowClosed(False)  # a box closing now mustn't quit
        self.hide()
        self._update_tray()
        log.info("Window sent to the tray")

    def open_from_tray(self) -> None:
        if self._in_tray:
            self._in_tray = False
            QApplication.setQuitOnLastWindowClosed(True)
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self._update_tray()

    def quit_app(self) -> None:
        """Quit CapyPanel, from the tray's menu: no question asked."""
        self._quitting = True
        hidden = self._in_tray
        if self.close() and hidden:
            QApplication.quit()  # a hidden window closing doesn't end the app by itself

    def _close_choice(self) -> str | None:
        """What the X does now: settings.CLOSE_TRAY, CLOSE_QUIT, or None to stay open. "Ask
        each time" asks every time, even with nothing running on its own: from the tray the
        window comes back at once, where a new start takes seconds."""
        if self._quitting or not self.tray.available():
            return settings.CLOSE_QUIT
        choice = self.prefs.get(settings.CLOSE_KEY, settings.CLOSE_ASK)
        if choice in (settings.CLOSE_TRAY, settings.CLOSE_QUIT):
            return str(choice)
        answer, remember = ask_closing(self)
        if answer is not None and remember:
            self._set_closing(answer)
        return answer

    # ---- look ----

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)  # _restyle follows it
        self.prefs["theme"] = theme.id
        self.save_prefs()
        log.info("Theme: %s", theme.id)

    def _restyle(self) -> None:
        """After every theme switch, the one Windows starts under "follow system" too."""
        for tool in self.tools.values():
            tool.restyle()  # icon colours, the font's size, the toolbar's padding
        self._tray_counts()  # the count on the tray's icon is in the theme's red
        self._paint_update_button()

    # ---- updates ----

    def open_updates(self, parent: QWidget | None = None) -> None:
        """The update window: the release on offer, or a look at GitHub first."""
        from capypanel.ui.updater import UpdateWindow

        if self.updater.offer is not None:
            self._update_shown = self.updater.offer.version
        window = UpdateWindow(
            parent or self, self.updater, app_dir=settings.app_dir(),
            working=self.tools_working, quit_for_update=self.quit_for_update,
        )  # fmt: skip
        run_modal(window)
        if window._release is not None:  # found while it was open
            self._update_shown = window._release.version

    def _offer_update(self) -> None:
        """A newer release, found on its own: its window opens, once per run, when nothing
        else is in the way (a guide, another window, CapyPanel in the tray)."""
        offer = self.updater.offer
        if offer is None or offer.version == self._update_shown or self._quitting:
            return
        busy = bool(self.guides.running) or QApplication.activeModalWidget() is not None
        if busy or not on_screen(self):
            QTimer.singleShot(OFFER_RETRY_MS, self, self._offer_update)
            return
        self.open_updates()

    def _show_update_button(self) -> None:
        from capypanel.ui.updater import button_text

        offer = self.updater.offer
        self.update_button.setVisible(offer is not None)
        if offer is not None:
            self.update_button.setText(button_text(offer))
            self.update_button.setToolTip(_("A newer CapyPanel is out: see what's new"))
            self._paint_update_button()
            self.update_button.adjustSize()
            # The menu bar sizes its corner when it's given one: given again, it fits the words.
            self.menuBar().setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)

    def _paint_update_button(self) -> None:
        color = self.update_button.palette().color(QPalette.ColorRole.Link)
        self.update_button.setIcon(tabler_icon("download", color, 16))

    # ---- first-run guides ----

    def _guide_for(self, tool_id: str | None) -> Guide | None:
        """The screen's guide; a tool's own ends on the View menu, the same for every tool."""
        if tool_id is None:
            return self._home_guide()
        tool = self.tools[tool_id]
        guide = tool.guide()
        if guide is None or guide.guide_id != tool_id or not tool.view_actions():
            return guide
        steps = guide.steps
        return replace(guide, steps=lambda: [*steps(), self._view_step(tool)])

    def _view_step(self, tool: Tool) -> Step:
        bar = self.menuBar()

        def view_title() -> QRect:  # "View" on the menu bar
            spot = bar.actionGeometry(self._view_menu.menuAction())
            return QRect(bar.mapTo(self, spot.topLeft()), spot.size())

        return Step(pgettext("guide", "View"),  # the card's title, without the menu's &
                    _("The View menu, on the menu bar, shows and hides this screen's panels, "
                      "like Tags and Details."), lambda: None, lambda: tool,
                    area=view_title)  # fmt: skip

    def _guide_now(self, *, force: bool = False) -> None:
        """The shown screen's guide: the first time it's shown (once its page is laid out), or
        now from Help."""
        guide = self._guide_for(self._shown)
        if guide is None:
            if force:
                self.statusBar().showMessage(_("This screen has no guide."), 5000)
            return
        if force:
            self.guides.show(guide)
        elif on_screen(self) and not self.guides.seen(guide.guide_id):
            QTimer.singleShot(400, self, lambda: self.guides.offer(self._guide_for(self._shown)))

    def show_all_guides_again(self) -> None:
        self.guides.forget_all()
        self.statusBar().showMessage(
            _("Each guide shows again the next time its screen is opened."), 8000
        )

    def _home_guide(self) -> Guide:
        """What every tool shares, said once, on the very first start."""
        home, rail, bar = self.home, self.rail, self.menuBar()

        def help_title() -> QRect:  # "Help" on the menu bar, which has no widget of its own
            spot = bar.actionGeometry(self._help_menu.menuAction())
            return QRect(bar.mapTo(self, spot.topLeft()), spot.size())

        def steps() -> list[Step]:
            return [
                Step(_("Welcome to CapyPanel"),
                     _("CapyPanel keeps the computers and printers you look after in one window. "
                       "You can see which are on and who's signed in, connect to them, run "
                       "commands and check the toner. These cards show you around."),
                     lambda: None),
                Step(_("Three tools"),
                     _("Hosts is for computers, Printers for printers, and User profiles clears "
                       "old Windows profiles off a PC. Each tile opens its tool."),
                     lambda: home.tiles, lambda: home),
                Step(_("The sidebar"),
                     _("This bar stays here on every screen. Home is at the top, Settings at the "
                       "bottom, and the tools in between."), lambda: rail),
                Step(_("Help"),
                     _("To see this guide again, use Help › Guide to this screen. Show all the "
                       "guides again brings every guide back, and Documentation opens the "
                       "step-by-step pages."),
                     lambda: None, lambda: home, area=help_title),
            ]  # fmt: skip

        return Guide("home", steps, docs="getting-started/", mascot=True)

    def tools_working(self) -> bool:
        return any(tool.working() for tool in self.tools.values())

    def quit_for_update(self, start_helper: Callable[[], None]) -> bool:
        """Closes CapyPanel for an update, once every tool agrees (a profile being deleted asks
        first); `start_helper` runs just before, so the new version takes over. False: a tool
        kept it open and nothing was started."""
        if not all(tool.quit_question(self) for tool in self.tools.values()):
            return False
        start_helper()
        self._tools_agreed = True
        self._quitting = True
        hidden = self._in_tray
        if self.close() and hidden:
            QApplication.quit()
        return True

    def show_restart_note(self, kind: str, version: str, why: str) -> None:
        """After the update's helper started CapyPanel again: what happened. What the update
        left is cleared at every start (ui/app.py)."""
        from capypanel.ui.updater import RestartWindow, restart_text

        log.info("%s", restart_text(kind, version, why))
        run_modal(RestartWindow(self, kind, version, why, self.updater.take_installed()))

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
        self._tray_counts()  # the tray's menu, in the new language

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._guide_now()  # Home's on the very first start
        themes.paint_title_bar(self)  # the window handle only exists once it's shown
        self._align_toolbar()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._align_toolbar()

    def closeEvent(self, event: QCloseEvent) -> None:
        choice = self._close_choice()
        if choice != settings.CLOSE_QUIT:
            event.ignore()
            if choice == settings.CLOSE_TRAY:
                self.to_tray()
            return
        if not self._tools_agreed and not all(
            tool.quit_question(self) for tool in self.tools.values()
        ):
            event.ignore()
            self._quitting = False
            return
        if not self._in_tray:  # saved when it went there, as it was shown
            self._save_state()
        self.tray.set_shown(False)
        QApplication.setQuitOnLastWindowClosed(True)
        # Windows of CapyPanel's own that no window owns, such as Commands: they go too.
        for other in QApplication.topLevelWidgets():
            if other is not self and other.isWindow() and other.isVisible():
                other.close()
        super().closeEvent(event)

    def _save_state(self) -> None:
        self.prefs["window_geometry"] = self.saveGeometry().toBase64().toStdString()
        for tool in self.tools.values():
            tool.save_state()
        self.prefs["view"] = {k: a.isChecked() for k, a in self._view_choices().items()}
        self.save_prefs()


def _docs_page(page: str) -> str:
    from capypanel.ui import about

    return about.docs_url() + page


class _StatusGroup(QWidget):
    """A tool's widgets on the status bar's right. Shown only while its tool is and one of them
    is: an empty group would still draw a separator line in some themes."""

    def __init__(self, widgets: list[QWidget]) -> None:
        super().__init__()
        self._widgets = widgets
        self._shown = True
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing.CONTROLS)
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
