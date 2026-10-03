"""The Settings window: a list of pages on the left, Cancel / Save at the bottom.
Nothing applies until Save; the main window then applies the returned choices."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.locations import same_path
from capypanel.core.i18n import _
from capypanel.core.tools.catalog import Catalogs
from capypanel.ui.settings.connections import ConnectionChanges, ConnectionsPage
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


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        recent: list[Path],
        registry: themes.Registry,
        catalogs: Catalogs,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Settings"))
        self.general = GeneralPage(
            paths,
            start_list=start_list,
            default_list=default_list,
            personal_list=personal_list,
            recent=recent,
            language=i18n.language(),
        )
        self.host_lists = HostListsPage(
            default_list=default_list,
            personal_list=personal_list,
            document=document,
            recent=recent,
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
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.page_list.setCurrentRow(0)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
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
            connections=self.connections.changes(),
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # The list places its rows before the theme's row padding reaches it, then never
        # moves them: rows drew on top of each other. Placing them again once shown fixes it.
        self.page_list.doItemsLayout()
        themes.paint_title_bar(self)

    def _update_save(self) -> None:
        save = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        save.setEnabled(all(page.is_valid() for page in self.pages.values()))
