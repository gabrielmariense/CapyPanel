"""The "Customize the details panel" window: which parts of the Details panel show, one tick per
part, and any tab a tool adds in front (Hosts: its quick commands). It applies as you tick and
ends in a plain Close; the choice is each person's own, on this PC."""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.notes import hint
from capypanel.ui.tables import fit_rows, grid_table, with_buttons

SIZE = (680, 670)


@dataclass(frozen=True)
class Part:
    """A part of the Details panel that can be hidden."""

    key: str
    name: str  # as its heading in the panel
    shows: str  # a few words on what it holds


class PartsTab(QWidget):
    """The Information tab: every part with a tick. Unticking one hides it in the panel."""

    changed = Signal(list)  # the hidden parts' keys

    def __init__(self, parts: Sequence[Part], hidden: Sequence[str], always: str) -> None:
        super().__init__()
        self._filling = False
        self.table = grid_table([_("Part of the panel"), _("Shows")])
        for part in parts:
            row = QTreeWidgetItem([part.name, part.shows])
            row.setData(0, Qt.ItemDataRole.UserRole, part.key)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.table.addTopLevelItem(row)
        self.table.itemChanged.connect(self._ticked)
        self.restore = QPushButton(_("&Restore default"))
        self.restore.clicked.connect(lambda: self.show_hidden(()))
        layout = QVBoxLayout(self)
        layout.addWidget(hint(_("Untick what you don't use. Hiding a part never stops a check.")))
        layout.addWidget(with_buttons(self.table, [self.restore]))
        layout.addWidget(hint(always))
        layout.addStretch(1)
        self._show(hidden)
        fit_rows(self.table)  # once the ticks are there: they take room too

    def hidden(self) -> list[str]:
        rows = [self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())]
        return [
            str(row.data(0, Qt.ItemDataRole.UserRole))
            for row in rows
            if row is not None and row.checkState(0) != Qt.CheckState.Checked
        ]

    def show_hidden(self, hidden: Sequence[str]) -> None:
        """Ticks every part but `hidden`, and says so."""
        self._show(hidden)
        self.changed.emit(self.hidden())

    def _show(self, hidden: Sequence[str]) -> None:
        self._filling = True
        for index in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(index)
            assert row is not None
            shown = row.data(0, Qt.ItemDataRole.UserRole) not in hidden
            row.setCheckState(0, Qt.CheckState.Checked if shown else Qt.CheckState.Unchecked)
            row.setDisabled(False)
        self._filling = False
        self.restore.setEnabled(bool(self.hidden()))

    def _ticked(self, _row: QTreeWidgetItem, _column: int) -> None:
        if self._filling:
            return
        self.restore.setEnabled(bool(self.hidden()))
        self.changed.emit(self.hidden())


class CustomizeDialog(QDialog):
    """Tabs: a tool's own (in front), then Information."""

    def __init__(
        self,
        parent: QWidget | None,
        parts: PartsTab,
        first: Sequence[tuple[str, QWidget]] = (),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Customize the details panel"))
        self.parts = parts
        self.tabs = QTabWidget()
        for title, tab in first:
            self.tabs.addTab(tab, title)
        self.tabs.addTab(parts, _("Information"))
        if self.tabs.count() == 1:
            self.tabs.tabBar().hide()  # one tab needs no bar
        close = QPushButton(_("&Close"))
        close.setAutoDefault(False)  # plain: nothing here is waiting to be confirmed
        close.clicked.connect(self.accept)
        own = QLabel(_("Only for you, on this PC."))
        own.setObjectName("hint")
        bottom = QHBoxLayout()
        bottom.addWidget(own)
        bottom.addStretch(1)
        bottom.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(bottom)
        self.resize(*SIZE)

    def show_tab(self, index: int) -> None:
        self.tabs.setCurrentIndex(max(0, min(index, self.tabs.count() - 1)))
