"""The SSH host Details panel: status, Connect and Refresh, then Connection (address, port, Log
in as, group), Tags and Notes, each part hideable. Log in as is a picker the tool fills."""

from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QMenu, QVBoxLayout, QWidget

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext, pgettext
from capypanel.core.ssh.host import info_of
from capypanel.ui.checks import clock_text
from capypanel.ui.hosts_tool.details import ValuePicker
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.ssh_tool import status
from capypanel.ui.ssh_tool.dialog import empty_text
from capypanel.ui.ssh_tool.status import Checked
from capypanel.ui.themes import engine as themes


@dataclass(frozen=True)
class SshDetails:
    host: Host
    group: str  # its full path
    checked: Checked | None = None  # its last check
    reachable: bool = True  # it has an address, or a name ssh.exe can take
    hidden: frozenset[str] = frozenset()  # the parts this person chose not to see
    login: str = ""  # the name it logs in with: its own, or its group's
    login_group: str = ""  # the group that name comes from; "" when it's the host's own


def button_words() -> dict[str, str]:
    """The buttons' short words (nine letters at most), as on Hosts' Details buttons."""
    return {"connect": pgettext("button", "Connect"), "refresh": pgettext("button", "Refresh")}


class SshDetailsPanel(DetailsPanel):
    connect_clicked = Signal()  # Connect: this host
    refresh_clicked = Signal()  # Refresh: this host's status

    def __init__(self) -> None:
        super().__init__()
        self.login_menu = QMenu(self)  # Log in as's choices, filled by the tool as it opens
        self.login_button: ValuePicker | None = None

    def show_host(
        self, details: SshDetails | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        self.show_item(details, selected, summary, needle)

    def selected_text(self, selected: int) -> str:
        return ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)

    def pick_hint(self) -> str:
        return _("Select a host to see its details.")

    def item_id(self, shown: object) -> str:
        return shown.host.id if isinstance(shown, SshDetails) else ""

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, SshDetails)
        host, info, hidden = shown.host, info_of(shown.host), shown.hidden
        self._heading(layout, shown)
        layout.addSpacing(6)
        layout.addWidget(self._button_grid(shown))

        if "connection" not in hidden:
            self.section(layout, _("Connection"))
            grid = self._grid(layout)
            self._row(grid, "address", _("Address"), host.address)
            self._row(grid, "port", _("Port"), str(info.port))
            self.login_button = self._login_picker(shown)
            self._place(grid, _("Log in as"), self.login_button)
            self._row(grid, "group", _("Group"), shown.group)

        if "tags" not in hidden:
            self.section(layout, _("Tags"))
            layout.addWidget(self.chips(host.tags) if host.tags else self.muted("—"))

        if "notes" not in hidden:
            self.section(layout, _("Notes"))
            layout.addWidget(self.notes(host.notes, needle) if host.notes else self.muted("—"))
        self.hidden_line(layout, len(hidden))

    def _button_grid(self, shown: SshDetails) -> QWidget:
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        text = self.palette().color(QPalette.ColorRole.Text)
        words = button_words()
        connect = self.word_button("plug-connected", text, words["connect"], _("Connect"))
        connect.clicked.connect(self.connect_clicked)
        refresh = self.word_button("refresh", text, words["refresh"], _("Refresh host"))
        refresh.clicked.connect(self.refresh_clicked)
        for button in (connect, refresh):
            button.setEnabled(shown.reachable)
        self.buttons = {"connect": connect, "refresh": refresh}
        column.addLayout(self.button_rows([connect, refresh], self._button_width()))
        return widget

    def _button_width(self) -> int:
        return self.grid_width(list(button_words().values()))

    def minimum_width(self) -> int:
        return self.grid_minimum(self._button_width())

    def _heading(self, layout: QVBoxLayout, shown: SshDetails) -> None:
        """Like Hosts' and Printers': a status dot by the name, then "status · checked 14:32"."""
        row = QHBoxLayout()
        row.setSpacing(4)
        name = self.value("name", shown.host.name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        cell = status.cell(shown.checked)
        line = QFontMetrics(font).height()
        size = round(line * 0.5)
        dot = QLabel()
        color = themes.status_color(cell.color or "offline")
        dot.setPixmap(dot_icon(color, size).pixmap(size, size))
        dot.setFixedHeight(line + 4)  # centred on the name's first line, even when it wraps
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(name, 1)
        layout.addLayout(row)
        if shown.checked is None:
            words = _("Not checked: use Refresh")
        else:
            words = _("{status} · checked {when}").format(
                status=cell.text, when=clock_text(shown.checked.when)
            )
        under = self.muted(words)
        under.setToolTip(cell.tip)
        layout.addWidget(under)

    @staticmethod
    def _grid(layout: QVBoxLayout) -> QGridLayout:
        """Hosts' label-and-value grid: a label on the left, its value on the same line."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return grid

    def _row(self, grid: QGridLayout, key: str, label: str, value: str) -> QWidget:
        """One label and its value (a dash when there's none), on the grid's next line."""
        return self._place(grid, label, self.value(key, value) if value else self.muted("—"))

    @staticmethod
    def _place(grid: QGridLayout, label: str, shown: QWidget) -> QWidget:
        row = grid.rowCount() if grid.count() else 0
        name = QLabel(label)  # never wraps: the column is as wide as its widest label
        name.setObjectName("hint")
        grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(shown, row, 1, Qt.AlignmentFlag.AlignVCenter)
        return shown

    def _login_picker(self, shown: SshDetails) -> ValuePicker:
        """The name it logs in with, and where that comes from in the tooltip; a pin when it's
        the host's own, as Hosts pins an account only this PC uses."""
        own = bool(info_of(shown.host).login)
        tip = _("Only this host") if own else empty_text(shown.login, shown.login_group)
        picker = ValuePicker(shown.login or "—", ("pin",) if own else (), tip)
        picker.clicked.connect(lambda: self._open_menu(self.login_menu, picker))
        return picker

    @staticmethod
    def _open_menu(menu: QMenu, picker: QWidget) -> None:
        """Under the value, from its left edge, like a dropdown's list (as in Hosts)."""
        menu.aboutToShow.emit()  # filled first
        menu.popup(picker.mapToGlobal(QPoint(0, picker.height())))
