"""The Hosts tool's part of Settings: General (its lists, startup, Refresh) and Connecting."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import shiboken6
from PySide6.QtWidgets import QLabel

from capypanel.core.hosts import locations
from capypanel.core.i18n import N_, _
from capypanel.ui.hosts_tool.accounts import AccountsSection
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


class HostsSettings(SettingsGroup):
    LABEL = N_("Hosts")
    TITLES = (N_("General"), N_("Connecting"), N_("Credentials"))

    general: HostsPage
    connections: ConnectionsPage
    accounts_page: Page  # only this person's: which account signs in where, and passwords
    accounts: AccountsSection

    def __init__(self, tool: "HostsTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in the lists table, across a rebuild
        self._kept: QLabel | None = None  # the open Settings' line saying which logins are kept
        # Once, for as long as the tool lives. Hooked up in build(), each opening of Settings
        # added one more listener, all still called after its pages were deleted.
        tool.accounts.changed.connect(self.credentials_changed)

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
        self.general.customize_requested.connect(
            lambda: tool.customize_details(0, parent=self.general.window())
        )
        self.connections = ConnectionsPage(tool.connector.catalogs, doc)
        self.accounts = AccountsSection(tool.accounts)  # which account signs in to which PCs
        self.accounts_page = Page(_("Credentials"))
        for section in (self.accounts, self.connections.profiles.passwords_section):
            self.accounts_page.body.addWidget(section)
        self.accounts_page.body.addStretch(1)
        self._kept = self.connections.profiles.saved_row.description
        self.general.changed.connect(self._changed)
        profiles = self.connections.profiles
        profiles.manage_button.clicked.connect(
            lambda: tool.open_saved_credentials(profiles.window())
        )
        self.credentials_changed()
        self.general.view.open_requested.connect(self._open)
        self.connections.changed.connect(tool.profiles_changed)  # Connect's menu follows
        self._building = False
        return [
            ("hosts", self.general),
            ("connections", self.connections),
            ("accounts", self.accounts_page),
        ]

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
        )

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_prefs(self.choices())

    def credentials_changed(self) -> None:
        """An account or a saved login changed: an open Settings says what's kept now. Called
        with Settings closed too (Details changes accounts), when there's no page to update."""
        if self._kept is not None and shiboken6.isValid(self._kept):
            self._kept.setText(kept_text(self._tool.every_kept_login()))

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
