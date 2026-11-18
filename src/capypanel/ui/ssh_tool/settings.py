"""The SSH tool's part of Settings: General, with its lists, what opens first and Refresh status
by itself (off until it's picked: a strict fail2ban can take the checks for failed logins)."""

from pathlib import Path
from typing import TYPE_CHECKING

from capypanel.core.hosts import locations
from capypanel.core.i18n import N_, _
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import AutoStatusPage, Page

if TYPE_CHECKING:
    from capypanel.ui.ssh_tool.tool import SshTool


def auto_line() -> str:
    """Under Refresh status by itself: what it checks, and the one way it can hurt."""
    return _("Only the SSH port, so nothing logs in. A server running fail2ban in a strict mode "
             "may count each check as a failed login and block this PC.")  # fmt: skip


class SshSettings(SettingsGroup):
    LABEL = N_("SSH")
    TITLES = (N_("General"),)

    general: AutoStatusPage

    def __init__(self, tool: "SshTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in the lists table, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        self.general = AutoStatusPage(
            texts=tool.list_texts(),
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            auto_line=auto_line(),
            document=doc,
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
            auto_status=tool.auto_status(),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.general.changed.connect(self._changed)
        self.general.view.open_requested.connect(self._open)
        self._building = False
        return [("ssh", self.general)]

    def before_rebuild(self) -> None:
        self._chosen = self.general.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.general.view.select(self._chosen)

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_list_prefs(
                self.general.start_choice(),
                self.general.show_first_choice(),
                self.general.added(),
                self.general.hidden(),
            )
            self._tool.set_auto_status(self.general.auto_status_choice())
            self._tool.prefs_applied()

    def _open(self, path: Path) -> None:
        """A list opened from the lists table: Settings then shows it as the open one."""
        self._tool.open_list(path)
        doc = self._tool.document
        self.general.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)
