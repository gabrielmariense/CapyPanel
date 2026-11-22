from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QTreeWidgetItem

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.remote.status import Status
from capypanel.ui import checks as check_texts
from capypanel.ui.list_workspace.panels import ROLE_NOTHING, ItemTable

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2


@dataclass(frozen=True)
class Cells:
    status: tuple[str, str, QIcon | None, bool] = ("", "", None, False)
    user: tuple[str, str, QIcon | None, bool] = ("", "", None, False)
    unchecked: bool = False


def not_checked() -> Cells:
    tip = _("Not checked: use Refresh")
    return Cells((_("Not checked"), tip, None, True), ("", tip, None, True), unchecked=True)


class HostTable(ItemTable):
    ADDRESS, STATUS, USER, TAGS = 1, 2, 3, 4
    COLUMNS = ("computer", "address", "status", "user", "tags")
    SEARCHED = frozenset({0, USER, ADDRESS, STATUS, TAGS})
    EMPTY = {USER: 24}
    ICONS = frozenset({STATUS})

    def __init__(self) -> None:
        self._cells: Mapping[str, Cells] = {}
        super().__init__()

    def retranslate(self) -> None:
        self.setHeaderLabels([_("Name"), _("Address"), _("Status"), _("User"), _("Tags")])

    def row_texts(self, item: Host) -> list[str]:
        return [item.name, item.address, "", "", ", ".join(item.tags)]

    def longest_texts(self, column: int) -> Sequence[str]:
        if column != self.STATUS:
            return ()
        late = check_texts.clock_text(datetime.now().astimezone().replace(hour=22, minute=58))
        return (
            *(check_texts.status_text(state) for state in Status),
            _("Not checked"),
            _("Restart at {when}").format(when=late),
            _("Shutdown at {when}").format(when=late),
        )

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        self._fill(row, self._cells.get(item.id))

    def show_hosts(self, hosts: Sequence[Host], cells: Mapping[str, Cells]) -> None:
        self._cells = cells
        self.show_items(hosts)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            for row in self._rows.values():
                self._tint(row)

    def shown_ids(self) -> list[str]:
        return list(self._rows)

    def show_cells(self, host_id: str, cells: Cells) -> None:
        row = self._rows.get(host_id)
        if row is not None:
            self._fill(row, cells)

    def _fill(self, row: QTreeWidgetItem, cells: Cells | None) -> None:
        cells = cells or not_checked()
        row.setData(self.STATUS, ROLE_NOTHING, cells.unchecked)
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
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for column in (self.STATUS, self.USER):
            quiet = bool(row.data(column, ROLE_QUIET))
            row.setData(column, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)
