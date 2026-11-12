"""Choosing the quick commands: the first tab of "Customize the details panel".

One table, in the Commands window's order under its group headings, and that order is the
buttons' too: ticking never moves a row (it made the list jump). The first four ticked are
also in a host's right-click menu. It applies as you tick."""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts import commands as host_commands
from capypanel.core.hosts.commands import CAN_BE_QUICK, GROUP_NAMES, QUICK, quick_from
from capypanel.core.i18n import _, ngettext
from capypanel.ui.hosts import confirm
from capypanel.ui.hosts_tool import quick
from capypanel.ui.icons import tabler_icon
from capypanel.ui.list_workspace.details import COLUMNS
from capypanel.ui.notes import hint
from capypanel.ui.tables import grid_table, with_buttons
from capypanel.ui.themes import engine as themes

ID = Qt.ItemDataRole.UserRole  # a command row's id; headings have none
SHORTCUT = Qt.ItemDataRole.UserRole + 1  # its shortcut, drawn in grey after the name
ICON = 16


class _Name(QStyledItemDelegate):
    """The command's name, then its shortcut in grey."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        shortcut = index.data(SHORTCUT)
        if not shortcut:
            return
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        widget = shown.widget  # type: ignore[attr-defined]
        style = widget.style() if widget is not None else None
        if style is None:
            return
        text = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, shown, widget)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1
        left = text.left() + margin + shown.fontMetrics.horizontalAdvance(shown.text) + 12  # type: ignore[attr-defined]
        if left >= text.right():
            return
        painter.save()
        painter.setPen(shown.palette.color(QPalette.ColorRole.PlaceholderText))  # type: ignore[attr-defined]
        painter.drawText(
            QRect(left, text.top(), text.right() - left, text.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(shortcut),
        )
        painter.restore()


class QuickChooser(QWidget):
    changed = Signal(list)  # the picked commands' ids, in order

    def __init__(self, picked: Sequence[str], shortcuts: Mapping[str, str]) -> None:
        """`shortcuts`: each command's keys as text ("Ctrl+E"), by command id."""
        super().__init__()
        self._picked: list[str] = list(quick_from(list(picked)))
        self._shortcuts = dict(shortcuts)
        self._filling = False
        self.table = grid_table([_("Command"), _("On the button")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setItemDelegateForColumn(0, _Name(self.table))
        header = self.table.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._ticked)
        self.restore = QPushButton(_("&Restore default…"))
        self.restore.clicked.connect(self._restore)
        self.count = hint()
        layout = QVBoxLayout(self)
        layout.addWidget(
            hint(
                _(
                    "Tick the ones you want, or none. They sit on top of the Details panel, in "
                    "this order."
                )
            )  # fmt: skip
        )
        layout.addWidget(hint(_("The choice is yours on this PC; it doesn't go into the list.")))
        layout.addWidget(with_buttons(self.table, [self.restore]), 1)
        layout.addWidget(self.count)
        layout.addWidget(hint(_("The first four ticked are also in a host's right-click menu.")))
        layout.addWidget(
            hint(
                _(
                    "Restart, Shut down, Log off and Disconnect can't be quick commands: they "
                    "cut someone off."
                )
            )  # fmt: skip
        )
        self._fill()

    def picked(self) -> list[str]:
        return list(self._picked)

    # ---- the rows ----

    def _fill(self) -> None:
        self._filling = True
        self.table.clear()
        for group in host_commands.Group:
            ids = [c.id for c in host_commands.in_group(group) if c.id in CAN_BE_QUICK]
            if ids:
                self._heading(_(GROUP_NAMES[group]))
                for command_id in ids:
                    self._row(command_id, ticked=command_id in self._picked)
        self._filling = False
        self._update()

    def _heading(self, text: str) -> None:
        row = QTreeWidgetItem([text.upper(), ""])
        row.setFlags(Qt.ItemFlag.ItemIsEnabled)  # can't be picked or ticked
        font = QFont(self.table.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 0.88)
        row.setFont(0, font)
        row.setForeground(0, self.palette().color(QPalette.ColorRole.PlaceholderText))
        self.table.addTopLevelItem(row)

    def _row(self, command_id: str, *, ticked: bool) -> None:
        command = host_commands.command(command_id)
        row = QTreeWidgetItem([_(command.name), quick.short_labels()[command_id]])
        row.setData(0, ID, command_id)
        row.setData(0, SHORTCUT, self._shortcuts.get(command_id, ""))
        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        row.setCheckState(0, Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)
        text = self.palette().color(QPalette.ColorRole.Text)
        color = QColor(themes.status_color("attention")) if command.risky else text
        row.setIcon(0, tabler_icon(command.icon, color, ICON))
        if command.risky:  # amber here as everywhere
            row.setForeground(0, color)
        row.setToolTip(0, _(command.description))
        self.table.addTopLevelItem(row)

    # ---- changes: each one applies at once ----

    def _ticked(self, row: QTreeWidgetItem, _column: int) -> None:
        command_id = row.data(0, ID)
        if self._filling or not command_id:
            return
        wanted = set(self._picked)
        if row.checkState(0) == Qt.CheckState.Checked:
            wanted.add(command_id)
        else:
            wanted.discard(command_id)
        self._picked = list(quick_from(list(wanted)))  # the one order; no row moves
        self.changed.emit(self.picked())
        self._update()

    def _restore(self) -> None:
        if not confirm(
            self,
            _("Restore default"),
            _("Go back to the quick commands CapyPanel starts with?"),
            _("&Restore default"),
            _("Your picks are replaced."),
        ):
            return
        self._picked = list(QUICK)
        self._fill()  # a button's click, not a row's change: rebuilding here is safe
        self.changed.emit(self.picked())

    def _update(self) -> None:
        self.restore.setEnabled(self._picked != list(QUICK))
        ticked, total = len(self._picked), len(CAN_BE_QUICK)
        rows = -(-ticked // COLUMNS)  # rows of four on the panel, rounded up
        text = _("{n} of {total} ticked").format(n=ticked, total=total)
        if rows:
            text += " · " + ngettext(
                "{n} row on the panel", "{n} rows on the panel", rows
            ).format(n=rows)  # fmt: skip
        self.count.setText(text)
