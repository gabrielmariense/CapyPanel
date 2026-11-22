import logging
from collections.abc import Callable, Sequence
from dataclasses import fields, replace
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
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from capypanel import __version__
from capypanel.core import settings
from capypanel.core.i18n import _, pgettext
from capypanel.ui import help_links, language, spacing
from capypanel.ui.dialogs import run_modal
from capypanel.ui.guides import Guide, GuideRunner, Step, on_screen, seen_from
from capypanel.ui.icons import tabler_icon
from capypanel.ui.main_window.actions import FIXED, create_actions, retranslate_actions
from capypanel.ui.main_window.home import HomePage
from capypanel.ui.main_window.rail import ToolRail
from capypanel.ui.main_window.tool import Tool, ToolKind
from capypanel.ui.main_window.tray import Tray, ask_closing
from capypanel.ui.menus import StayOpenMenu, label, plain
from capypanel.ui.saved_credentials import KeptLogin, SavedCredentialsDialog
from capypanel.ui.settings.pages import open_folder
from capypanel.ui.settings.window import HEIGHT as SETTINGS_HEIGHT
from capypanel.ui.settings.window import WIDTH as SETTINGS_WIDTH
from capypanel.ui.settings.window import SettingsDialog
from capypanel.ui.shortcuts import EVERYWHERE, KeyCommand, Keys, key_tip, portable
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import CATALOG, ToolInfo
from capypanel.ui.updater import Updater

log = logging.getLogger(__name__)
OFFER_RETRY_MS = 2000


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
        self._pages = QStackedWidget()
        self._tool_actions = QActionGroup(self)
        self._tool_actions.setExclusive(True)
        self._home_action = QAction(self)
        self._home_action.setCheckable(True)
        self._home_action.setShortcut(QKeySequence("Ctrl+0"))
        self._home_action.triggered.connect(lambda _c=False: self.show_home())
        self._tool_actions.addAction(self._home_action)
        self.addAction(self._home_action)
        self._status: dict[str, _StatusGroup] = {}
        self._badges: dict[str, int] = {}
        self.tray = Tray(self)
        self._in_tray = False
        self._quitting = False
        self._notified_by: str | None = None
        self._page_of: dict[str, QWidget] = {}

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self.rail)
        row.addWidget(self._pages, 1)
        self.setCentralWidget(central)

        self._building = True
        for make in tools:
            self._add_tool(make(self))
        self._shown: str | None = None
        self.home = HomePage(self._infos())
        self.home.tool_picked.connect(self.show_tool)
        self._pages.insertWidget(0, self.home)

        self.updater = Updater(self.prefs, self.save_prefs, self.paths.company_tools_dir, self)
        self._update_shown = ""
        self.guides = GuideRunner(self, seen_from(self.prefs), self.save_prefs, _docs_page)
        self._tools_agreed = False
        self._build_menus()
        for action in (self._home_action, self.commands.settings):
            action.changed.connect(self._rail_tips)
        self.keys = Keys(self.prefs, self.save_prefs)
        self.keys.load(self._key_commands())
        self._connect()
        self._connect_tray()
        themes.switches().switched.connect(self._restyle)
        self._restore_layout()
        start = self.prefs.get(settings.START_KEY, settings.START_HOME)
        if start == settings.START_LAST:
            start = self.prefs.get(settings.TOOL_KEY)
        start = start if isinstance(start, str) and start in self.tools else None
        if start is not None and self.tools[start].first_use_pending():
            start = None
        self._building = False
        self._show(start)

    def _add_tool(self, tool: Tool) -> None:
        tool_id = tool.TOOL_ID
        self.tools[tool_id] = tool
        page = QWidget()
        self._pages.addWidget(page)
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(tool.toolbar)
        column.addWidget(tool, 1)
        self._page_of[tool_id] = page
        self.rail.add_tool(tool_id, tool.ICON)
        action = QAction(self)
        action.setCheckable(True)
        action.setData(tool_id)
        if len(self.tools) <= 9:
            action.setShortcut(QKeySequence(f"Ctrl+{len(self.tools)}"))
        action.triggered.connect(lambda _c=False: self.show_tool(tool_id))
        action.changed.connect(lambda t=tool_id: self._rail_tip(t))
        self._tool_actions.addAction(action)
        self.addAction(action)
        self.statusBar().addWidget(tool.status_label, 1)
        right = _StatusGroup(tool.status_widgets())
        self.statusBar().addPermanentWidget(right)
        self._status[tool_id] = right
        tool.title_changed.connect(lambda _name, t=tool_id: self._title_changed(t))
        tool.badge_changed.connect(lambda count, t=tool_id: self._badge_changed(t, count))
        tool.notify_requested.connect(lambda title, text, t=tool_id: self._notify(t, title, text))

    def shown_tool(self) -> Tool | None:
        return None if self._shown is None else self.tools[self._shown]

    def help_place(self) -> str:
        tool = self.shown_tool()
        return (tool.help_place() if tool is not None else "") or "start-run-capypanel"

    def show_tool(self, tool_id: str) -> bool:
        self._show(tool_id)
        return self._shown == tool_id

    def show_home(self) -> None:
        self._show(None)

    def _show(self, tool_id: str | None) -> None:
        if tool_id is not None and on_screen(self):
            tool = self.tools[tool_id]
            if tool.first_use_pending() and not tool.first_use_warning(self):
                self.rail.show_tool(self._shown)
                return
        if self.guides.running and self.guides.running != (tool_id or "home"):
            self.guides.stop()
        self._shown = tool_id
        tool = self.shown_tool()
        self._pages.setCurrentWidget(self.home if tool_id is None else self._page_of[tool_id])
        if tool is not None:
            tool.came_to_front()
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
        return [info for info in self._catalog if info.tool_id in self.tools]

    def _tool_list_actions(self) -> list[QAction]:
        return [a for a in self._tool_actions.actions() if a is not self._home_action]

    def _tool_action(self, tool_id: str) -> QAction:
        return next(a for a in self._tool_list_actions() if a.data() == tool_id)

    def fills_now(self, tool_id: str) -> bool:
        return not self._building and self._shown == tool_id

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
        if isinstance(geometry, str) and self.prefs.get("settings_opens_at") == opens_at:
            dialog.own_size = dialog.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        if page:
            dialog.show_page(page)
        run_modal(dialog)
        self.prefs["settings_geometry"] = dialog.saveGeometry().toBase64().toStdString()
        self.prefs["settings_opens_at"] = opens_at
        self.save_prefs()
        self._update_tray()

    def kept_logins(self) -> list[KeptLogin]:
        return [login for tool in self.tools.values() for login in tool.kept_logins()]

    def tool(self, tool_id: str) -> Tool | None:
        return self.tools.get(tool_id)

    def open_saved_credentials(self, parent: QWidget | None = None) -> None:
        run_modal(SavedCredentialsDialog(parent or self, self.kept_logins))
        if isinstance(parent, SettingsDialog):
            parent.credentials_changed()

    def _build_menus(self) -> None:
        a = self.commands
        bar = self.menuBar()
        self._file_menu = bar.addMenu("")
        self._file_menu.addAction(a.settings)
        self._file_menu.addSeparator()
        self._file_menu.addAction(a.exit)
        self._view_menu = StayOpenMenu(self)
        bar.addMenu(self._view_menu)
        self._help_menu = bar.addMenu("")
        self._help_menu.addActions(
            [a.show_guide, a.show_all_guides, a.help_screen, a.documentation, a.report_problem]
        )
        self._help_menu.addSeparator()
        self._help_menu.addActions([a.check_updates, a.about])
        self.update_button = QToolButton()
        self.update_button.setObjectName("updateButton")
        self.update_button.setAutoRaise(True)
        self.update_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.update_button.clicked.connect(lambda: self.open_updates())
        self.update_button.hide()
        bar.setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)
        self._retranslate_menus()

    def _fill_view_menu(self) -> None:
        menu = self._view_menu
        for action in menu.actions():  # not clear(): it deletes the tools' own actions
            menu.removeAction(action)
            if action.isSeparator():
                action.deleteLater()
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
        self._home_action.setText(_("Hom&e"))
        for action in self._tool_list_actions():
            action.setText(self.tools[str(action.data())].menu_name())
        self._rail_tips()
        self._file_menu.setTitle(_("&File"))
        self._view_menu.setTitle(_("&View"))
        self._help_menu.setTitle(_("&Help"))

    def _connect(self) -> None:
        a = self.commands
        a.settings.triggered.connect(lambda: self.open_settings())
        a.exit.triggered.connect(self.close)
        a.documentation.triggered.connect(self._open_docs)
        a.help_screen.triggered.connect(lambda: help_links.open_place(self.help_place()))
        self.rail.help_button.clicked.connect(a.help_screen.trigger)
        a.report_problem.triggered.connect(self._report_problem)
        a.about.triggered.connect(lambda: self.open_settings("about"))
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

    def _rail_tips(self) -> None:
        home, help_words = self._home_action, _("Help for this screen")
        self.rail.home_button.setToolTip(key_tip(plain(label(home)), home))
        self.rail.help_button.setToolTip(key_tip(help_words, self.commands.help_screen))
        self.rail.help_button.setAccessibleName(help_words)  # no &, so it isn't read aloud
        self.rail.settings_button.setToolTip(key_tip(_("Settings"), self.commands.settings))
        for tool_id in self.tools:
            self._rail_tip(tool_id)

    def _rail_tip(self, tool_id: str) -> None:
        tool = self.tools[tool_id]
        tip = key_tip(tool.tool_name(), self._tool_action(tool_id))
        count = self._badges.get(tool_id, 0)
        if count and (meaning := tool.attention_text(count)):
            tip = "\n".join((tip, meaning))
        self.rail.buttons[tool_id].setToolTip(tip)

    def _title_changed(self, tool_id: str) -> None:
        if tool_id == self._shown:
            self._show_title(self.tools[tool_id].title())

    def _show_title(self, name: str) -> None:
        app = f"CapyPanel {__version__}"
        self.setWindowTitle(f"{name} — {app}" if name else app)

    def settings_dialog(self) -> SettingsDialog:
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
            closing=closing if isinstance(closing, str) else settings.CLOSE_ASK,
            keys=self.keys,
            place_names={tool_id: tool.tool_name() for tool_id, tool in self.tools.items()},
        )
        dialog.language_picked.connect(self.set_language)
        dialog.theme_picked.connect(self.set_theme)
        dialog.start_picked.connect(self._set_start)
        dialog.closing_picked.connect(self._set_closing)
        dialog.updates_picked.connect(lambda how: self._set_update_checks(how, dialog))
        dialog.about.updates_button.clicked.connect(lambda: self.open_updates(dialog))
        return dialog

    def _key_commands(self) -> list[KeyCommand]:
        a = self.commands
        own = [getattr(a, f.name) for f in fields(a)]
        made = [KeyCommand(f"app.{f.name}", action, EVERYWHERE, portable(action.shortcut()),
                           fixed=f.name in FIXED)
                for f, action in zip(fields(a), own, strict=True)]  # fmt: skip
        for action in [self._home_action, *self._tool_list_actions()]:
            place = "home" if action is self._home_action else str(action.data())
            made.append(KeyCommand(f"go.{place}", action, EVERYWHERE, portable(action.shortcut())))
        for tool in self.tools.values():
            made.extend(tool.key_commands())
        return made

    def _set_update_checks(self, how: str, dialog: SettingsDialog) -> None:
        try:
            self.updater.set_how_often(how)
        except OSError as e:
            dialog.show_updates(self.updater.how_often())
            text = _("Couldn't save how often to check: {error}").format(error=e)
            help_links.warning(dialog, _("Settings"), text, place="settings-updates-not-saved")

    def _set_start(self, start: str) -> None:
        self.prefs[settings.START_KEY] = start
        self.save_prefs()

    def _set_closing(self, closing: str) -> None:
        self.prefs[settings.CLOSE_KEY] = closing
        self.save_prefs()

    def _connect_tray(self) -> None:
        self.tray.open_requested.connect(self.open_from_tray)
        self.tray.quit_requested.connect(self.quit_app)
        self.tray.attention_requested.connect(self._show_attention)
        self.tray.message_clicked.connect(self._notification_clicked)
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            # When Windows ends the session, Qt says aboutToQuit, then closes the windows, all in
            # WM_ENDSESSION. commitDataRequest also comes when the end is then cancelled: no sign.
            app.aboutToQuit.connect(self._session_ending)
        self._update_tray()

    def _session_ending(self) -> None:
        """Windows is logging off or shutting down: quit without asking, never holding it up."""
        self._quitting = True
        self._tools_agreed = True

    def _update_tray(self) -> None:
        working = any(t.works_in_background() for t in self.tools.values())
        self.tray.set_shown(self._in_tray or working)

    def _tray_counts(self) -> None:
        self.tray.set_counts(
            {t: (n, self.tools[t].attention_text(n)) for t, n in self._badges.items()}
        )

    def _notify(self, tool_id: str, title: str, text: str) -> None:
        self._notified_by = tool_id
        self.tray.set_shown(True)
        self.tray.notify(title, text)

    def _notification_clicked(self) -> None:
        if self._notified_by is not None:
            self._show_attention(self._notified_by)
        else:
            self.open_from_tray()

    def _show_attention(self, tool_id: str) -> None:
        self.open_from_tray()
        self.show_tool(tool_id)
        self.tools[tool_id].show_attention()

    def to_tray(self) -> None:
        self._save_state()
        self._in_tray = True
        QApplication.setQuitOnLastWindowClosed(False)
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
        self._quitting = True
        hidden = self._in_tray
        if self.close() and hidden:
            QApplication.quit()  # a hidden window closing doesn't end the app by itself

    def _close_choice(self) -> str | None:
        if self._quitting or not self.tray.available():
            return settings.CLOSE_QUIT
        choice = self.prefs.get(settings.CLOSE_KEY, settings.CLOSE_ASK)
        if choice in (settings.CLOSE_TRAY, settings.CLOSE_QUIT):
            return str(choice)
        answer, remember = ask_closing(self)
        if answer is not None and remember:
            self._set_closing(answer)
        return answer

    def set_theme(self, theme_id: str) -> None:
        theme = self.registry.find(theme_id)
        themes.apply(theme)
        self.prefs["theme"] = theme.id
        self.save_prefs()
        log.info("Theme: %s", theme.id)

    def _restyle(self) -> None:
        for tool in self.tools.values():
            tool.restyle()
        self._tray_counts()
        self._paint_update_button()

    def open_updates(self, parent: QWidget | None = None) -> None:
        from capypanel.ui.updater import UpdateWindow

        if self.updater.offer is not None:
            self._update_shown = self.updater.offer.version
        window = UpdateWindow(
            parent or self, self.updater, app_dir=settings.app_dir(),
            working=self.tools_working, quit_for_update=self.quit_for_update,
        )  # fmt: skip
        run_modal(window)
        if window._release is not None:
            self._update_shown = window._release.version

    def _offer_update(self) -> None:
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
            self.menuBar().setCornerWidget(self.update_button, Qt.Corner.TopRightCorner)

    def _paint_update_button(self) -> None:
        color = self.update_button.palette().color(QPalette.ColorRole.Link)
        self.update_button.setIcon(tabler_icon("download", color, 16))

    def _guide_for(self, tool_id: str | None) -> Guide | None:
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

        def view_title() -> QRect:
            spot = bar.actionGeometry(self._view_menu.menuAction())
            return QRect(bar.mapTo(self, spot.topLeft()), spot.size())

        return Step(pgettext("guide", "View"),
                    _("The View menu, on the menu bar, shows and hides this screen's panels, "
                      "like Tags and Details."), lambda: None, lambda: tool,
                    area=view_title)  # fmt: skip

    def _guide_now(self, *, force: bool = False) -> None:
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
        home, rail, bar = self.home, self.rail, self.menuBar()

        def help_title() -> QRect:
            spot = bar.actionGeometry(self._help_menu.menuAction())
            return QRect(bar.mapTo(self, spot.topLeft()), spot.size())

        def steps() -> list[Step]:
            return [
                Step(_("Welcome to CapyPanel"),
                     _("CapyPanel keeps the computers and printers you look after in one window. "
                       "You can see which are on and who's signed in, connect to them, run "
                       "commands and check the toner. These cards show you around."),
                     lambda: None),
                Step(_("Four tools"),
                     _("Hosts is for computers, Printers for printers, Profile cleanup clears "
                       "old Windows profiles off a PC, and SSH opens a terminal on your servers "
                       "and switches. Each tile opens its tool."),
                     lambda: home.tiles, lambda: home),
                Step(_("The sidebar"),
                     _("This bar stays here on every screen. Home is at the top, the ? for help "
                       "and Settings at the bottom, and the tools in between."), lambda: rail),
                Step(_("Help"),
                     _("F1, or the ? in the sidebar, opens help for the screen you're on. To see "
                       "this guide again, use Help › Guide to this screen. Show all the guides "
                       "again brings every guide back, and Documentation opens the step-by-step "
                       "pages."),
                     lambda: None, lambda: home, area=help_title),
                *([self._portable_step()] if self.paths.portable else []),
            ]  # fmt: skip

        docs = "getting-started/"
        if self.paths.portable:
            docs = "settings-and-files/#settings-portable-mode"
        return Guide("home", steps, docs=docs, mascot=True)

    def _portable_step(self) -> Step:
        folder = self.paths.root
        text = _("This copy keeps everything it saves (settings, lists, connection profiles and "
                 "logs) in the userdata folder beside CapyPanel.exe. Passwords you save stay in "
                 "Windows on this PC, so they don't travel with the folder. Lists and settings "
                 "from another copy of CapyPanel aren't brought in: click the list's name on top "
                 "of the Groups panel and use Open list…, or copy their files into the userdata "
                 "folder.")  # fmt: skip
        opens = (_("Open the userdata folder"), lambda: open_folder(folder))
        return Step(_("A portable copy"), text, lambda: None, action=opens)

    def tools_working(self) -> bool:
        return any(tool.working() for tool in self.tools.values())

    def quit_for_update(self, start_helper: Callable[[], None]) -> bool:
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
        from capypanel.ui.updater import RestartWindow, restart_text

        log.info("%s", restart_text(kind, version, why))
        run_modal(RestartWindow(self, kind, version, why, self.updater.take_installed()))

    def set_language(self, code: str) -> None:
        code = language.apply(code)
        self.prefs["language"] = code
        self.save_prefs()
        log.info("Language: %s", code)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        self._retranslate_menus()
        self.home.retranslate()
        for tool in self.tools.values():
            tool.retranslate()
        self._tray_counts()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._guide_now()
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
        if not self._in_tray:
            self._save_state()
        self.tray.set_shown(False)
        QApplication.setQuitOnLastWindowClosed(True)
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
    """Shown only with a visible widget: an empty group still draws a separator in some themes."""

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
