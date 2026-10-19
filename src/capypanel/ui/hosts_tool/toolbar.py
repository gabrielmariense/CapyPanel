"""The Hosts toolbar: Connect and Refresh, Inventory, Report. Refresh always checks every host the
table shows (the group picked on the left); one host is checked from its own right-click menu.
Left-click picks one check; right-click opens a panel to run several at once."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.hosts_tool.actions import HostsActions
from capypanel.ui.icons import tabler_icon
from capypanel.ui.main_window.toolbar import ToolBar, tool_button


class RefreshPanel(QFrame):
    """Right-click on Refresh: tick what to check on the hosts shown, then Run. It stays open
    while boxes are ticked; the ticks are kept for next time."""

    run_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self._check_title = _section("")
        self.status_box, self.users_box = QCheckBox(), QCheckBox()
        self.run_button = QPushButton()
        self.run_button.setDefault(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        for widget in (self._check_title, self.status_box, self.users_box):
            layout.addWidget(widget)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.run_button)
        layout.addSpacing(6)
        layout.addLayout(row)
        self.status_box.toggled.connect(self._update)
        self.users_box.toggled.connect(self._update)
        self.run_button.clicked.connect(self._run)
        self.retranslate()

    def retranslate(self) -> None:
        self._check_title.setText(_("Refresh every host shown"))
        self.status_box.setText(_("&Status"))
        self.users_box.setText(_("&Logged-on users"))
        self.run_button.setText(_("&Run"))

    def choices(self) -> dict[str, bool]:
        return {"status": self.status_box.isChecked(), "users": self.users_box.isChecked()}

    def set_choices(self, saved: object) -> None:
        saved = saved if isinstance(saved, dict) else {}
        self.status_box.setChecked(saved.get("status", True) is not False)
        self.users_box.setChecked(saved.get("users", True) is not False)
        self._update()

    def _update(self) -> None:
        self.run_button.setEnabled(self.status_box.isChecked() or self.users_box.isChecked())

    def _run(self) -> None:
        self.hide()
        self.run_clicked.emit()


class HostsToolBar(ToolBar):
    refresh_panel_requested = Signal(QPoint)
    refresh_requested = Signal(bool, bool)  # status, users: on every host shown

    def __init__(self, commands: HostsActions) -> None:
        super().__init__()
        # Connect: a dropdown like the others, never greyed out. Its menu connects the selected
        # hosts (also Enter or a double-click), once with another profile, or by address.
        self.connect_button = tool_button(dropdown=True)
        self.connect_menu = QMenu(self.connect_button)
        self.connect_button.setMenu(self.connect_menu)
        self.refresh_button = tool_button(dropdown=True)
        self.refresh_menu = QMenu(self.refresh_button)
        self.refresh_status = self.refresh_menu.addAction("")
        self.refresh_users = self.refresh_menu.addAction("")
        self.refresh_status.triggered.connect(lambda: self.refresh_requested.emit(True, False))
        self.refresh_users.triggered.connect(lambda: self.refresh_requested.emit(False, True))
        self.refresh_button.setMenu(self.refresh_menu)
        self.refresh_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.refresh_button.customContextMenuRequested.connect(
            lambda _pos: self.refresh_panel_requested.emit(
                self.refresh_button.mapToGlobal(QPoint(0, self.refresh_button.height()))
            )
        )
        # Inventory: adding hosts and groups, and importing them; its menu is filled by the tool.
        self.inventory_button = tool_button(dropdown=True)
        self.inventory_menu = QMenu(self.inventory_button)
        self.inventory_button.setMenu(self.inventory_menu)
        self.report_button = tool_button()
        self.report_button.clicked.connect(commands.export_hosts.trigger)
        self.add_group([self.connect_button, self.refresh_button])
        self.add_group([self.inventory_button])
        self.add_group([self.report_button])
        self.retranslate()

    def retranslate(self) -> None:
        gap = " "  # the stylesheet drops the gap between icon and text
        self.connect_button.setText(gap + _("Connect"))
        self.connect_button.setToolTip(
            _("Connect to the selected hosts, once with another profile, or by address")
        )
        self.refresh_button.setText(gap + _("Refresh"))
        self.refresh_button.setToolTip(
            _("Refresh every host shown. Right-click to choose what Run and F5 check")
        )
        self.refresh_status.setText(_("&Status"))
        self.refresh_users.setText(_("&Logged-on users"))
        self.inventory_button.setText(gap + _("Inventory"))
        self.inventory_button.setToolTip(_("Add hosts and groups, or import a list of hosts"))
        self.report_button.setText(gap + _("Report"))
        self.report_button.setToolTip(
            _("Save the hosts you pick, with the columns you pick, as a CSV file")
        )

    def restyle(self) -> None:
        """Icons in the theme's text colour."""
        color = self.connect_button.palette().color(QPalette.ColorRole.ButtonText)  # its text's
        self.connect_button.setIcon(tabler_icon("plug-connected", color))
        self.refresh_button.setIcon(tabler_icon("refresh", color))
        self.inventory_button.setIcon(tabler_icon("plus", color))
        self.report_button.setIcon(tabler_icon("report-analytics", color))
        self.retranslate()


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("menuSection")
    return label
