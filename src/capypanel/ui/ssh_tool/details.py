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
    group: str
    checked: Checked | None = None
    reachable: bool = True
    hidden: frozenset[str] = frozenset()
    login: str = ""
    login_group: str = ""


def button_words() -> dict[str, str]:
    return {"connect": pgettext("button", "Connect"), "refresh": pgettext("button", "Refresh")}


class SshDetailsPanel(DetailsPanel):
    connect_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.login_menu = QMenu(self)
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
        dot.setFixedHeight(line + 4)
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
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return grid

    def _row(self, grid: QGridLayout, key: str, label: str, value: str) -> QWidget:
        return self._place(grid, label, self.value(key, value) if value else self.muted("—"))

    @staticmethod
    def _place(grid: QGridLayout, label: str, shown: QWidget) -> QWidget:
        row = grid.rowCount() if grid.count() else 0
        name = QLabel(label)
        name.setObjectName("hint")
        grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(shown, row, 1, Qt.AlignmentFlag.AlignVCenter)
        return shown

    def _login_picker(self, shown: SshDetails) -> ValuePicker:
        own = bool(info_of(shown.host).login)
        tip = _("Only this host") if own else empty_text(shown.login, shown.login_group)
        picker = ValuePicker(shown.login or "—", ("pin",) if own else (), tip)
        picker.clicked.connect(lambda: self._open_menu(self.login_menu, picker))
        return picker

    @staticmethod
    def _open_menu(menu: QMenu, picker: QWidget) -> None:
        menu.aboutToShow.emit()
        menu.popup(picker.mapToGlobal(QPoint(0, picker.height())))
