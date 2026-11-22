"""The window as CapyPanel makes it, with typed access to its tools; it opens on Hosts."""

from typing import Any

from capypanel.core import settings
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.tool_catalog import CATALOG


class CapyWindow(MainWindow):
    def __init__(self, paths: settings.Paths, prefs: dict[str, Any], **kwargs: Any) -> None:
        kwargs.setdefault("tools", [info.load() for info in CATALOG])
        prefs.setdefault(settings.START_KEY, "hosts")
        super().__init__(paths, prefs, **kwargs)

    @property
    def hosts(self) -> HostsTool:
        tool = self.tools["hosts"]
        assert isinstance(tool, HostsTool)
        return tool
