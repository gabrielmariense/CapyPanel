"""The window as CapyPanel makes it (every tool), for the UI tests, with typed access to its
tools."""

from typing import Any

from capypanel.core import settings
from capypanel.ui.builds import CAPYPANEL
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.main_window.window import MainWindow


class CapyWindow(MainWindow):
    def __init__(self, paths: settings.Paths, prefs: dict[str, Any], **kwargs: Any) -> None:
        kwargs.setdefault("tools", CAPYPANEL.tools)
        super().__init__(paths, prefs, **kwargs)

    @property
    def hosts(self) -> HostsTool:
        tool = self.tools["hosts"]
        assert isinstance(tool, HostsTool)
        return tool
