"""The Hosts tool's part of Settings: General (its lists, startup, Refresh) and Connecting."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from capypanel.core.hosts import locations
from capypanel.core.i18n import N_
from capypanel.ui.saved_credentials import kept_text
from capypanel.ui.settings.connections import ConnectionsPage
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import HostsPage, Page

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.tool import HostsTool


@dataclass(frozen=True)
class SettingsPrefs:
    """The Hosts choices Settings hands over on every change."""

    start_list: str  # see locations.START_KEY
    added_lists: list[Path]  # the lists in the lists table, besides the default and personal
    hidden_lists: list[Path]  # lists in a lists folder removed from the lists table
    auto_status: tuple[bool, int] = (False, 5)  # check Status by itself, every N minutes
    start_view: tuple[str, str] | None = None  # the open list's (show, group) first
    save_passwords: bool = False  # typed passwords also go to Windows Credential Manager


class HostsSettings(SettingsGroup):
    LABEL = N_("Hosts")
    TITLES = (N_("General"), N_("Connecting"))

    general: HostsPage
    connections: ConnectionsPage

    def __init__(self, tool: "HostsTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in the lists table, across a rebuild

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
            document=doc,
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
            auto_status=tool.auto_status(),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.connections = ConnectionsPage(
            tool.connector.catalogs, doc, save_passwords=tool.saves_passwords()
        )
        self.general.changed.connect(self._changed)
        profiles = self.connections.profiles
        profiles.passwords_changed.connect(self._changed)
        profiles.manage_button.clicked.connect(
            lambda: tool.open_saved_credentials(profiles.window())
        )
        self.credentials_changed()
        self.general.view.open_requested.connect(self._open)
        self.connections.changed.connect(tool.profiles_changed)  # Connect's menu follows
        self._building = False
        return [("hosts", self.general), ("connections", self.connections)]

    def before_rebuild(self) -> None:
        self._chosen = self.general.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.general.view.select(self._chosen)

    def choices(self) -> SettingsPrefs:
        return SettingsPrefs(
            start_list=self.general.start_choice(),
            added_lists=self.general.added(),
            hidden_lists=self.general.hidden(),
            auto_status=self.general.auto_status_choice(),
            start_view=self.general.show_first_choice(),
            save_passwords=self.connections.profiles.save_passwords_choice(),
        )

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_prefs(self.choices())
            self.credentials_changed()  # Temporary credentials deletes the saved ones

    def credentials_changed(self) -> None:
        row = self.connections.profiles.saved_row
        row.description.setText(kept_text(self._tool.every_kept_login()))

    def _open(self, path: Path) -> None:
        """A list opened from the lists table: Settings then shows it as the open one."""
        self._tool.open_list(path)
        self.list_opened()

    def list_opened(self) -> None:
        """The lists table marks the open list; Show first is now about it."""
        doc = self._tool.document
        self.general.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)
        self.connections.profiles.document = doc
