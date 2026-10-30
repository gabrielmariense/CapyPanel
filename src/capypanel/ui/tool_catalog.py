"""Every tool CapyPanel has, in the rail's order, with what Home and Settings show of it. The
window and the start-up import no tool themselves: load() does."""

import importlib
from dataclasses import dataclass

from capypanel.core.i18n import N_
from capypanel.ui.main_window.tool import ToolKind


@dataclass(frozen=True)
class ToolInfo:
    tool_id: str
    icon: str  # a Tabler icon's name
    name: str  # N_() texts: shown through _()
    blurb: str  # what the tool is for, in one line
    module: str  # where its class lives
    class_name: str

    def load(self) -> ToolKind:
        return getattr(importlib.import_module(self.module), self.class_name)


CATALOG = (
    ToolInfo(
        "hosts",
        "device-desktop",
        N_("Hosts"),
        N_("Your computers: connect, see who's logged on, check them."),
        "capypanel.ui.hosts_tool.tool",
        "HostsTool",
    ),
    ToolInfo(
        "printers",
        "printer",
        N_("Printers"),
        N_("Your printers: status and toner, web pages, reports."),
        "capypanel.ui.printers_tool.tool",
        "PrintersTool",
    ),
)
