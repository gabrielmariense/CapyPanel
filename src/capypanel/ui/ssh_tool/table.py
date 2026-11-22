from collections.abc import Callable, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QTreeWidgetItem

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.ssh.host import info_of
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.panels import ROLE_NOTHING, ItemTable
from capypanel.ui.ssh_tool.status import Cell, not_checked, status_words
from capypanel.ui.themes import engine as themes

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2


class SshTable(ItemTable):
    ADDRESS, PORT, LOGIN, STATUS, TAGS = 1, 2, 3, 4, 5
    COLUMNS = ("name", "address", "port", "login", "status", "tags")
    HIDDEN = ("port",)
    SEARCHED = frozenset({0, ADDRESS, PORT, LOGIN, STATUS, TAGS})
    ICONS = frozenset({STATUS})

    def __init__(self) -> None:
        self._cells: Callable[[str], Cell] = lambda _id: not_checked()
        self._login: Callable[[Host], str] = lambda host: info_of(host).login
        super().__init__()

    def retranslate(self) -> None:
        self.setHeaderLabels(
            [_("Name"), _("Address"), _("Port"), _("Log in as"), _("Status"), _("Tags")]
        )

    def row_texts(self, item: Host) -> list[str]:
        port, login = str(info_of(item).port), self._login(item)
        return [item.name, item.address, port, login, "", ", ".join(item.tags)]

    def set_logins(self, login: Callable[[Host], str]) -> None:
        self._login = login

    def longest_texts(self, column: int) -> Sequence[str]:
        return status_words() if column == self.STATUS else ()

    def set_hidden_columns(self, keys: object) -> None:
        super().set_hidden_columns(keys if isinstance(keys, list) else list(self.HIDDEN))

    def set_cells(self, cells: Callable[[str], Cell]) -> None:
        self._cells = cells

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        self._fill(row, self._cells(item.id))

    def show_cells(self, host_id: str) -> None:
        row = self._rows.get(host_id)
        if row is not None:
            self._fill(row, self._cells(host_id))

    def refill(self) -> None:
        for host_id, row in self._rows.items():
            self._fill(row, self._cells(host_id))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            for row in self._rows.values():
                self._tint(row)

    def _fill(self, row: QTreeWidgetItem, status: Cell) -> None:
        row.setText(self.STATUS, status.text)
        row.setToolTip(self.STATUS, status.tip)
        dot = dot_icon(themes.status_color(status.color)) if status.color else QIcon()
        row.setIcon(self.STATUS, dot)
        row.setData(self.STATUS, ROLE_QUIET, status.quiet)
        row.setData(self.STATUS, ROLE_NOTHING, status.nothing)
        self._tint(row)

    def _tint(self, row: QTreeWidgetItem) -> None:
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        quiet = bool(row.data(self.STATUS, ROLE_QUIET))
        row.setData(self.STATUS, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)
