"""The host table: name, Status, User, address and tags. Status and User come from Refresh; they're
kept in memory, never in the list file."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QTreeWidgetItem

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.ui.list_workspace.panels import ItemTable

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2  # a Status or User cell to show greyed


@dataclass(frozen=True)
class Cells:
    """What the Status and User columns show for one host: text, tooltip, icon, quiet."""

    status: tuple[str, str, QIcon | None, bool] = ("", "", None, False)
    user: tuple[str, str, QIcon | None, bool] = ("", "", None, False)


class HostTable(ItemTable):
    STATUS, USER, ADDRESS, TAGS = 1, 2, 3, 4
    COLUMNS = ("computer", "status", "user", "address", "tags")  # saved by these keys
    # What's searched and shown: notes are searched too, but have no column.
    SEARCHED = frozenset({0, USER, ADDRESS, TAGS})
    EMPTY = {STATUS: 16, USER: 24}  # empty until a check: room for what a check brings

    def __init__(self) -> None:
        self._cells: Mapping[str, Cells] = {}
        super().__init__()

    def retranslate(self) -> None:
        self.setHeaderLabels([_("Name"), _("Status"), _("User"), _("Address"), _("Tags")])

    def row_texts(self, item: Host) -> list[str]:
        return [item.name, "", "", item.address, ", ".join(item.tags)]

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        self._fill(row, self._cells.get(item.id))

    def show_hosts(self, hosts: Sequence[Host], cells: Mapping[str, Cells]) -> None:
        self._cells = cells
        self.show_items(hosts)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:  # the quiet colour of the new theme
            for row in self._rows.values():
                self._tint(row)

    def show_cells(self, host_id: str, cells: Cells) -> None:
        """New Refresh results for one host, without rebuilding the table."""
        row = self._rows.get(host_id)
        if row is not None:
            self._fill(row, cells)  # columns keep their widths: a Refresh never resizes them

    def _fill(self, row: QTreeWidgetItem, cells: Cells | None) -> None:
        cells = cells or Cells()
        for column, (text, tip, icon, quiet) in (
            (self.STATUS, cells.status),
            (self.USER, cells.user),
        ):
            row.setText(column, text)
            row.setToolTip(column, tip)
            row.setIcon(column, icon if icon is not None else QIcon())
            row.setData(column, ROLE_QUIET, quiet)
        self._tint(row)

    def _tint(self, row: QTreeWidgetItem) -> None:
        """Errors and "not checked" read quieter than real results, in the current theme."""
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for column in (self.STATUS, self.USER):
            quiet = bool(row.data(column, ROLE_QUIET))
            row.setData(column, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)
