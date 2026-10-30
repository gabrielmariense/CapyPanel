"""The Printers toolbar, slot for slot like Hosts': Open web page and Refresh, Inventory, Report.
Refresh is a plain button: printers have one check (one SNMP read), so there's nothing to pick."""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMenu

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon
from capypanel.ui.main_window.toolbar import ToolBar, tool_button
from capypanel.ui.printers_tool.actions import PrintersActions


class PrintersToolBar(ToolBar):
    def __init__(self, commands: PrintersActions) -> None:
        super().__init__()
        self.web_button = tool_button()
        self.web_button.clicked.connect(commands.open_web_page.trigger)
        commands.open_web_page.enabledChanged.connect(self.web_button.setEnabled)
        self.web_button.setEnabled(commands.open_web_page.isEnabled())
        self.refresh_button = tool_button()
        self.refresh_button.clicked.connect(commands.refresh_shown.trigger)
        commands.refresh_shown.enabledChanged.connect(self.refresh_button.setEnabled)
        # Inventory: adding printers and groups; its menu is filled by the tool.
        self.inventory_button = tool_button(dropdown=True)
        self.inventory_menu = QMenu(self.inventory_button)
        self.inventory_button.setMenu(self.inventory_menu)
        self.report_button = tool_button()
        self.report_button.clicked.connect(commands.export_printers.trigger)
        self.add_group([self.web_button, self.refresh_button])
        self.add_group([self.inventory_button])
        self.add_group([self.report_button])
        self.retranslate()

    def retranslate(self) -> None:
        gap = " "  # the stylesheet drops the gap between icon and text
        self.web_button.setText(gap + _("Open web page"))
        self.web_button.setToolTip(_("Open the selected printers' web pages (Enter)"))
        self.refresh_button.setText(gap + _("Refresh"))
        self.refresh_button.setToolTip(
            _("Read the status and supplies of every printer shown (F5)")
        )
        self.inventory_button.setText(gap + _("Inventory"))
        self.inventory_button.setToolTip(_("Add printers and groups, and manage the groups"))
        self.report_button.setText(gap + _("Report"))
        self.report_button.setToolTip(
            _("Save the printers you pick, with the columns you pick, as a CSV file")
        )

    def restyle(self) -> None:
        """Icons in the theme's text colour."""
        color = self.inventory_button.palette().color(QPalette.ColorRole.ButtonText)
        self.web_button.setIcon(tabler_icon("world", color))
        self.refresh_button.setIcon(tabler_icon("refresh", color))
        self.inventory_button.setIcon(tabler_icon("plus", color))
        self.report_button.setIcon(tabler_icon("report-analytics", color))
        self.retranslate()
