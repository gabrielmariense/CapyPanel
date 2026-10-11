"""The Settings window: a list of pages on the left, OK / Save / Cancel at the bottom.
Nothing applies until OK or Save (which keeps the window open); the main window applies the
choices handed over by `saved`. Cancel reads "Close" while nothing is left unsaved. Leaving the
Connections page with changes asks to save or drop them first."""

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
    saved = Signal(object)  # SettingsChoices, on OK and on Save

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
        self.setWindowTitle(_("Settings"))
        self.closing = False  # OK was clicked: the window goes once its choices are applied
        self.reopen = False  # the language changed on Save: open again, in the new language
        self.cancel_button: QPushButton | None = None  # reads "Close" while nothing is unsaved
        self._saved_state: tuple[object, ...] | None = None
        self.general = GeneralPage(
            paths,
            start_list=start_list,
            default_list=default_list,
            personal_list=personal_list,
            added=added,
            language=i18n.language(),
            auto_status=auto_status,
        )
        self.host_lists = HostListsPage(
            default_list=default_list,
            personal_list=personal_list,
            document=document,
            added=added,
        )
        self.connections = ConnectionsPage(catalogs, document)
        self.appearance = AppearancePage(registry, themes.current().id)
        self.pages: dict[str, Page] = {
            "general": self.general,
            "host_lists": self.host_lists,
            "connections": self.connections,
            "appearance": self.appearance,
        }

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

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # ActionRole puts Save between OK and Cancel; Cancel stays on the far right.
        self.save_button = self.buttons.addButton(
            _("&Save"), QDialogButtonBox.ButtonRole.ActionRole
        )
        self.save_button.setToolTip(_("Save the changes and keep Settings open"))
        # Enter means OK wherever the focus is; the other buttons never take its place.
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        assert ok is not None and cancel is not None
        self.cancel_button = cancel
        ok.setDefault(True)
        for button in (self.save_button, cancel):
            button.setAutoDefault(False)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self.page_list)
        columns.addWidget(self.stack, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addLayout(columns, 1)
        layout.addWidget(self.buttons)
        self.resize(780, 540)
        self._update_save()
        self._mark_saved()

    def _page_picked(self, row: int) -> None:
        """Leaving Connections with changes asks first: save them, drop them, or stay."""
        here = list(self.pages).index("connections")
        if self.stack.currentIndex() == here and row != here and self.connections.has_changes():
            answer = self._ask_unsaved()
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
        self._update_close()

    def _ask_unsaved(self) -> str:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("Unsaved changes"),
            _("The changes on the Connections page aren't saved yet."),
            parent=self,
        )
        save = box.addButton(_("&Save changes"), QMessageBox.ButtonRole.AcceptRole)
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

    def current_page(self) -> str:
        return list(self.pages)[self.stack.currentIndex()]

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        for button in self.findChildren(QPushButton):  # pages' buttons too, e.g. Open folder
            if button is not ok:
                button.setAutoDefault(False)  # or the focused one would take Enter from OK
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
            QTimer.singleShot(0, self, self._update_close)  # once the widget has changed
        return False

    def _state(self) -> tuple[object, ...] | None:
        """What Save would write, to tell whether anything is left unsaved."""
        if not all(page.is_valid() for page in self.pages.values()):
            return None
        c = self.choices()
        return (
            c.start_list, c.host_list, c.theme_id, c.language, tuple(c.added_lists),
            c.auto_status, self.connections.has_changes(),
        )  # fmt: skip

    def _mark_saved(self) -> None:
        self._saved_state = self._state()
        self._update_close()

    def _update_close(self) -> None:
        if self.cancel_button is None:  # still being built
            return
        unsaved = self._state() != self._saved_state
        self.cancel_button.setText(_("Cancel") if unsaved else _("Close"))

    def _update_save(self) -> None:
        valid = all(page.is_valid() for page in self.pages.values())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
        self.save_button.setEnabled(valid)
        self._update_close()

    def _ok(self) -> None:
        self.closing = True
        self.saved.emit(self.choices())
        self.accept()

    def _save(self) -> None:
        self.saved.emit(self.choices())

    def after_save(self, document: OpenList | None) -> None:
        """The window stays open after Save: its pages now show what's saved."""
        self.connections.reset()
        self.host_lists.view.saved(document)
        self._update_save()
        self._mark_saved()
