"""The SSH tool's part of Settings: General, with Refresh status by itself (off until it's picked:
a strict fail2ban can take the checks for failed logins). Its lists are Hosts', managed on Hosts'
General page."""

from typing import TYPE_CHECKING

from capypanel.core.i18n import N_, _
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import AutoStatusOnlyPage, Page

if TYPE_CHECKING:
    from capypanel.ui.ssh_tool.tool import SshTool


def auto_line() -> str:
    """Under Refresh status by itself: what it checks, and the one way it can hurt."""
    return _("Only the SSH port, so nothing logs in. A server running fail2ban in a strict mode "
             "may count each check as a failed login and block this PC.")  # fmt: skip


class SshSettings(SettingsGroup):
    LABEL = N_("SSH")
    TITLES = (N_("General"),)

    general: AutoStatusOnlyPage

    def __init__(self, tool: "SshTool") -> None:
        self._tool = tool

    def build(self) -> list[tuple[str, Page]]:
        self.general = AutoStatusOnlyPage(
            auto_line=auto_line(), auto_status=self._tool.auto_status()
        )
        self.general.changed.connect(self._changed)
        return [("ssh", self.general)]

    def _changed(self) -> None:
        self._tool.set_auto_status(self.general.auto_status_choice())
        self._tool.prefs_applied()
