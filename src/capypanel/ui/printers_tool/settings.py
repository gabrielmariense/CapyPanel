"""The Printers tool's part of Settings: General (startup) and Printer lists."""

from pathlib import Path
from typing import TYPE_CHECKING

from capypanel.core.hosts import locations
from capypanel.core.i18n import N_
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import ListsGeneralPage, ListsPage, Page

if TYPE_CHECKING:
    from capypanel.ui.printers_tool.tool import PrintersTool


class PrintersSettings(SettingsGroup):
    LABEL = N_("Printers")
    TITLES = (N_("General"), N_("Printer lists"))

    general: ListsGeneralPage
    lists: ListsPage

    def __init__(self, tool: "PrintersTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in Printer lists, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        texts = tool.list_texts()
        self.general = ListsGeneralPage(
            texts=texts,
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.lists = ListsPage(
            texts=texts,
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            document=doc,
            added=locations.added_lists(prefs),
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
        )
        for page in (self.general, self.lists):
            page.changed.connect(self._changed)
        self.lists.view.open_requested.connect(self._open)
        self._building = False
        return [("printers", self.general), ("printer_lists", self.lists)]

    def before_rebuild(self) -> None:
        self._chosen = self.lists.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.lists.view.select(self._chosen)

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_list_prefs(
                self.general.start_choice(),
                self.general.show_first_choice(),
                self.lists.added(),
                self.lists.hidden(),
            )
            self._tool.prefs_applied()

    def _open(self, path: Path) -> None:
        """A list opened from Printer lists: Settings then shows it as the open one."""
        self._tool.open_list(path)
        doc = self._tool.document
        self.lists.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)
