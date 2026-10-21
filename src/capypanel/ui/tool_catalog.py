"""Every tool CapyPanel has, in the rail's order. A tool's code is imported only when the tool is
on, so tools turned off cost nothing; what the Tools window shows of them is kept here."""

import importlib
from dataclasses import dataclass
from typing import Any

from capypanel.core import settings
from capypanel.core.i18n import N_
from capypanel.ui.main_window.tool import ToolKind


@dataclass(frozen=True)
class ToolInfo:
    tool_id: str
    icon: str  # a Tabler icon's name
    name: str  # N_() texts: shown through _()
    blurb: str  # what the tool is for, in one line
    module: str  # where its class lives, imported only when the tool is on
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
        N_("Your printers: web pages, details, reports."),
        "capypanel.ui.printers_tool.tool",
        "PrintersTool",
    ),
)


def tools_on(prefs: dict[str, Any], catalog: tuple[ToolInfo, ...] = CATALOG) -> list[ToolInfo]:
    """The tools that are on, in the rail's order. Never none: with every one off, the first."""
    off = prefs.get(settings.TOOLS_OFF_KEY)
    off = {i for i in off if isinstance(i, str)} if isinstance(off, list) else set()
    return [t for t in catalog if t.tool_id not in off] or list(catalog[:1])
