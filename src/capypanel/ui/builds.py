"""CapyPanel's build: the app with every tool. A build with one tool has a module of its own, so
it imports no other tool's code."""

from capypanel.core import identity
from capypanel.ui.app import Build
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.printers_tool.tool import PrintersTool

CAPYPANEL = Build(identity.CAPYPANEL, (HostsTool, PrintersTool), carry_over=True)
