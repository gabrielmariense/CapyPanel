"""The Hosts tool's part of Settings: General (startup, Refresh), Host lists and Connections."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from capypanel.core.hosts import locations
from capypanel.core.i18n import N_
from capypanel.ui.settings.connections import ConnectionsPage
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import HostsPage, ListsPage, Page

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.tool import HostsTool


@dataclass(frozen=True)
class SettingsPrefs:
    """The Hosts choices Settings hands over on every change."""

    start_list: str  # see locations.START_KEY
    added_lists: list[Path]  # the lists in Host lists, besides the default and personal
    hidden_lists: list[Path]  # lists in a lists folder removed from Host lists
    auto_status: tuple[bool, int] = (False, 5)  # check Status by itself, every N minutes
    start_view: tuple[str, str] | None = None  # the open list's (show, group) first
    save_passwords: bool = False  # typed passwords also go to Windows Credential Manager


class HostsSettings(SettingsGroup):
    LABEL = N_("Hosts")
    TITLES = (N_("General"), N_("Host lists"), N_("Connections"))

    general: HostsPage
    lists: ListsPage
    connections: ConnectionsPage

    def __init__(self, tool: "HostsTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in Host lists, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        texts = tool.list_texts()
        self.general = HostsPage(
            texts=texts,
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            auto_status=tool.auto_status(),
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
        self.connections = ConnectionsPage(
            tool.connector.catalogs, doc, save_passwords=tool.saves_passwords()
        )
        for page in (self.general, self.lists):
            page.changed.connect(self._changed)
        self.connections.profiles.passwords_changed.connect(self._changed)
        self.lists.view.open_requested.connect(self._open)
        self.connections.changed.connect(tool.profiles_changed)  # Connect's menu follows
        self._building = False
        return [
            ("hosts", self.general),
            ("host_lists", self.lists),
            ("connections", self.connections),
        ]

    def before_rebuild(self) -> None:
        self._chosen = self.lists.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.lists.view.select(self._chosen)

    def choices(self) -> SettingsPrefs:
        return SettingsPrefs(
            start_list=self.general.start_choice(),
            added_lists=self.lists.added(),
            hidden_lists=self.lists.hidden(),
            auto_status=self.general.auto_status_choice(),
            start_view=self.general.show_first_choice(),
            save_passwords=self.connections.profiles.save_passwords_choice(),
        )

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_prefs(self.choices())

    def _open(self, path: Path) -> None:
        """A list opened from Host lists: Settings then shows it as the open one."""
        self._tool.open_list(path)
        self.list_opened()

    def list_opened(self) -> None:
        """Host lists marks the open list; Show first is now about it."""
        doc = self._tool.document
        self.lists.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)
        self.connections.profiles.document = doc
