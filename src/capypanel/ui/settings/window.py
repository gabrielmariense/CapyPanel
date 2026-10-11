"""The Settings window: a list of pages on the left, Save and Close at the bottom.
Nothing applies until Save, except the language, which switches as soon as it's picked (the
window follows). The main window applies the choices handed over by `saved`. Close, and leaving
the Connections page, ask first when something isn't saved."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, Signal
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.locations import same_path
from capypanel.core.i18n import _
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.profiles import ProfileError
from capypanel.ui.settings.connections import ConnectionChanges, ConnectionsPage, apply
from capypanel.ui.settings.pages import (
    AppearancePage,
    GeneralPage,
    HostListsPage,
    Page,
)
from capypanel.ui.themes import engine as themes


@dataclass(frozen=True)
class SettingsChoices:
    start_list: str  # see locations.START_KEY
    host_list: Path
    rewritten: bool  # the chosen list's file was written from Settings, so reopen it
    theme_id: str
    language: str
    connections: ConnectionChanges
    added_lists: list[Path]  # the lists in Host lists, besides the default and personal
    auto_status: tuple[bool, int] = (False, 5)  # check Status by itself, every N minutes


class SettingsDialog(QDialog):
    saved = Signal(object)  # SettingsChoices, on Save
    language_picked = Signal(str)  # applied at once, not on Save

    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
        registry: themes.Registry,
        catalogs: Catalogs,
        auto_status: tuple[bool, int] = (False, 5),
    ) -> None:
        super().__init__(parent)
        self._paths = paths
        self._default_list = default_list
        self._personal_list = personal_list
        self._document = document
        self._registry = registry
        self._catalogs = catalogs
        self._saved_state: tuple[object, ...] | None = None
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch (see DECISIONS, code cleanup).
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._build(start_list, added, auto_status, themes.current().id)
        self.resize(780, 540)
        self._saved_state = self._state()
        self._update_save()

    def _build(
        self,
        start_list: object,
        added: list[Path],
        auto_status: tuple[bool, int],
        theme_id: str,
        chosen: Path | None = None,
        written: tuple[Path, ...] = (),
    ) -> None:
        """The pages and buttons, in the current language, showing the values given."""
        self._building = True  # pages report changes while they're filled
        self.setWindowTitle(_("Settings"))
        self.general = GeneralPage(
            self._paths,
            start_list=start_list,
            default_list=self._default_list,
            personal_list=self._personal_list,
            added=added,
            language=i18n.language(),
            auto_status=auto_status,
        )
        self.host_lists = HostListsPage(
            default_list=self._default_list,
            personal_list=self._personal_list,
            document=self._document,
            added=added,
        )
        if chosen is not None:
            self.host_lists.view.select(chosen)
        self.host_lists.view.written.extend(written)
        self.connections = ConnectionsPage(self._catalogs, self._document)
        self.appearance = AppearancePage(self._registry, theme_id)
        self.pages: dict[str, Page] = {
            "general": self.general,
            "host_lists": self.host_lists,
            "connections": self.connections,
            "appearance": self.appearance,
        }
        self.general.language.currentIndexChanged.connect(self._language_changed)

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        # No setUniformItemSizes: it caches a row height measured before the theme reaches the
        # list, and the rows then overlap (13 px rows for 27 px of text).
        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.page_list.addItem(page.title)
            self.stack.addWidget(page)
            page.changed.connect(self._update_save)
        # Wide enough for the longest page name, so the list never cuts or overlaps it.
        longest = max(
            self.page_list.fontMetrics().horizontalAdvance(p.title) for p in self.pages.values()
        )
        self.page_list.setFixedWidth(longest + 64)
        self.page_list.currentRowChanged.connect(self._page_picked)
        self.page_list.setCurrentRow(0)

        # Save keeps the window open; Close asks first when something isn't saved. Neither is
        # a default button: Enter never saves or closes by surprise.
        self.buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.save_button = self.buttons.addButton(_("&Save"), role.ActionRole)
        self.close_button = self.buttons.addButton(_("Close"), role.RejectRole)
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        content = QWidget()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self.page_list)
        columns.addWidget(self.stack, 1)
        inside = QVBoxLayout(content)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addLayout(columns, 1)
        inside.addWidget(self.buttons)
        self._layout.addWidget(content)
        self._content = content
        self._no_default_buttons()
        self._building = False

    def _language_changed(self) -> None:
        code = self.general.language_choice()
        if code != i18n.language():
            self.language_picked.emit(code)  # the app switches now; Settings follows
            QTimer.singleShot(0, self, self._rebuild)  # after the dropdown has closed

    def _rebuild(self) -> None:
        """The same window in the new language, keeping what was picked but not saved."""
        page = self.current_page()
        chosen = self.host_lists.chosen()
        old = self._content
        values = (
            self.general.start_choice(),
            self.host_lists.added(),
            self.general.auto_status_choice(),
            self.appearance.theme_id(),
        )
        written = tuple(self.host_lists.written)
        old.hide()
        self._layout.removeWidget(old)
        self._old.append(old)
        self._build(*values, chosen=chosen, written=written)
        self.show_page(page)
        self._update_save()
        self.general.language.setFocus()

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):  # the pages' buttons too
            button.setAutoDefault(False)
            button.setDefault(False)

    def _page_picked(self, row: int) -> None:
        """Leaving Connections with changes asks first: save them, drop them, or stay."""
        here = list(self.pages).index("connections")
        if self.stack.currentIndex() == here and row != here and self.connections.has_changes():
            answer = self._ask_unsaved(_("The changes on the Connections page aren't saved yet."))
            if answer == "save" and not self._save_connections():
                answer = "stay"
            if answer == "stay":
                self.page_list.blockSignals(True)
                self.page_list.setCurrentRow(here)
                self.page_list.blockSignals(False)
                return
            if answer == "discard":
                self.connections.reset()
        self.stack.setCurrentIndex(row)
        self._update_save()

    def _ask_unsaved(self, text: str, *, can_save: bool = True) -> str:
        box = QMessageBox(QMessageBox.Icon.Warning, _("Unsaved changes"), text, parent=self)
        save = box.addButton(_("&Save changes"), QMessageBox.ButtonRole.AcceptRole)
        save.setEnabled(can_save)
        discard = box.addButton(_("&Discard changes"), QMessageBox.ButtonRole.DestructiveRole)
        stay = box.addButton(_("&Keep editing"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(stay)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "stay"

    def _save_connections(self) -> bool:
        try:
            apply(self.connections.catalogs, self.connections.changes())
        except (ProfileError, OSError) as e:
            message = _("Couldn't save the connection profiles: {error}").format(error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return False
        self.connections.reset()
        return True

    def show_page(self, page_id: str) -> None:
        self.page_list.setCurrentRow(list(self.pages).index(page_id))

    def current_page(self) -> str:
        return list(self.pages)[self.stack.currentIndex()]

    def choices(self) -> SettingsChoices:
        host_list = self.host_lists.chosen()
        assert host_list is not None, "Save is disabled until a list is chosen"
        written = self.host_lists.written
        return SettingsChoices(
            start_list=self.general.start_choice(),
            host_list=host_list,
            rewritten=any(same_path(host_list, p) for p in written),
            theme_id=self.appearance.theme_id(),
            language=self.general.language_choice(),
            added_lists=self.host_lists.added(),
            connections=self.connections.changes(),
            auto_status=self.general.auto_status_choice(),
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)
        self._no_default_buttons()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)  # any click or key in here may change something

    def hideEvent(self, event: QHideEvent) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.KeyRelease) and (
            isinstance(watched, QWidget) and self.isAncestorOf(watched)
        ):
            QTimer.singleShot(0, self, self._update_save)  # once the widget has changed
        return False

    def _state(self) -> tuple[object, ...] | None:
        """What Save would write (the language is applied at once, so not here), to tell
        whether anything is left unsaved. None while a page can't be saved."""
        if not self.is_valid():
            return None
        c = self.choices()
        return (
            c.start_list, c.host_list, c.theme_id, tuple(c.added_lists), c.auto_status,
            self.connections.has_changes(),
        )  # fmt: skip

    def is_valid(self) -> bool:
        return all(page.is_valid() for page in self.pages.values())

    def unsaved(self) -> bool:
        return self._state() != self._saved_state

    def _update_save(self) -> None:
        """Save is on only while there's something valid to save."""
        if self._building:
            return
        self.save_button.setEnabled(self.is_valid() and self.unsaved())

    def reject(self) -> None:
        """Close, Esc or the window's X: asks first when something isn't saved."""
        if self.unsaved():
            answer = self._ask_unsaved(
                _("Some changes aren't saved yet."), can_save=self.is_valid()
            )
            if answer == "stay":
                return
            if answer == "save":
                self._save()
        super().reject()

    def _save(self) -> None:
        self.saved.emit(self.choices())

    def after_save(self, document: OpenList | None) -> None:
        """The window stays open after Save: its pages now show what's saved."""
        self._document = document
        self.connections.reset()
        self.host_lists.view.saved(document)
        self._saved_state = self._state()
        self._update_save()
