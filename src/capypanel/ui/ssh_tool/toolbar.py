from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QMenu

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon
from capypanel.ui.main_window.toolbar import ToolBar, tool_button
from capypanel.ui.shortcuts import key_tip
from capypanel.ui.ssh_tool.actions import SshActions


class SshToolBar(ToolBar):
    def __init__(self, commands: SshActions) -> None:
        super().__init__()
        self.connect_button = tool_button()
        self.connect_button.clicked.connect(commands.connect_host.trigger)
        commands.connect_host.enabledChanged.connect(self.connect_button.setEnabled)
        self.connect_button.setEnabled(commands.connect_host.isEnabled())
        self.refresh_button = tool_button()
        self.refresh_button.clicked.connect(commands.refresh_shown.trigger)
        commands.refresh_shown.enabledChanged.connect(self.refresh_button.setEnabled)
        self._refresh = commands.refresh_shown
        self._refresh.changed.connect(self._key_tips)
        self.inventory_button = tool_button(dropdown=True)
        self.inventory_menu = QMenu(self.inventory_button)
        self.inventory_button.setMenu(self.inventory_menu)
        self.add_group([self.connect_button, self.refresh_button])
        self.add_group([self.inventory_button])
        self.retranslate()

    def retranslate(self) -> None:
        gap = " "
        self.connect_button.setText(gap + _("Connect"))
        self.connect_button.setToolTip(_("Connect to the selected hosts with Windows' ssh.exe"))
        self.refresh_button.setText(gap + _("Refresh all"))
        self._key_tips()
        self.inventory_button.setText(gap + _("Inventory"))
        self.inventory_button.setToolTip(_("Add hosts and groups, and manage the groups"))

    def _key_tips(self) -> None:
        self.refresh_button.setToolTip(
            key_tip(_("Check the SSH port of every host shown"), self._refresh)
        )

    def restyle(self) -> None:
        color = self.inventory_button.palette().color(QPalette.ColorRole.ButtonText)
        self.connect_button.setIcon(tabler_icon("plug-connected", color))
        self.refresh_button.setIcon(tabler_icon("refresh", color))
        self.inventory_button.setIcon(tabler_icon("plus", color))
        self.retranslate()
