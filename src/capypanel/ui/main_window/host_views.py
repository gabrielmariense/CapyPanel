"""The three panes of the main window: groups and tags, the host table, and host details."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QKeyEvent, QPainter, QPalette, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QStackedLayout,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host, HostList
from capypanel.core.i18n import _, ngettext
from capypanel.ui.groups import HOSTS_MIME, ROLE_ID, ROLE_KIND, GroupTree, hosts_mime
from capypanel.ui.icons import tabler_icon
from capypanel.ui.menus import popup

ROLE_QUIET = Qt.ItemDataRole.UserRole + 2  # a Status or User cell to show greyed


@dataclass(frozen=True)
class Filter:
    kind: str  # "all", "group" or "tag"
    value: str | None = None


def pane_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("paneTitle")
    label.setContentsMargins(4, 4, 4, 2)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class NavigationPane(QWidget):
    """One card, like the other panes: "All hosts" pinned on top, then the groups (in the
    list's own order, rearranged by dragging) and the tags, each under a small heading and
    split by thin lines. Picking one filters the table."""

    filter_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._filter = Filter("all")
        self.add_group_button = QToolButton()
        self.add_group_button.setText("+")
        self._groups_title, self._tags_title = pane_title(""), pane_title("")
        header = QHBoxLayout()
        header.addWidget(self._groups_title, 1)
        header.addWidget(self.add_group_button)

        # Its own small list above the tree: it never scrolls away under a long tree.
        self.everything = QTreeWidget()
        self.everything.setHeaderHidden(True)
        self.everything.setRootIsDecorated(False)
        self.everything.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.everything.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._everything_item = QTreeWidgetItem([""])
        self._everything_item.setData(0, ROLE_KIND, "all")
        self._everything_item.setIcon(
            0, self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.everything.addTopLevelItem(self._everything_item)
        self.groups = GroupTree()
        self.groups.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # A tree like the groups (not QListWidget), so both lists have the same row height.
        self.tags = QTreeWidget()
        self.tags.setHeaderHidden(True)
        self.tags.setRootIsDecorated(False)

        # The lists drop their own frames ("flat"): the card around them is the only box.
        for tree in (self.everything, self.groups, self.tags):
            tree.setObjectName("flat")
        self._tags_line = _divider()
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        inside = QVBoxLayout(card)
        inside.setContentsMargins(4, 4, 4, 4)
        inside.setSpacing(2)
        inside.addWidget(self.everything)
        inside.addWidget(_divider())
        inside.addLayout(header)
        inside.addWidget(self.groups, 3)
        inside.addWidget(self._tags_line)
        inside.addWidget(self._tags_title)
        inside.addWidget(self.tags, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)

        self.everything.itemSelectionChanged.connect(self._everything_picked)
        self.groups.itemSelectionChanged.connect(self._groups_picked)
        self.tags.itemSelectionChanged.connect(self._tags_picked)
        self.retranslate()

    def retranslate(self) -> None:
        """Titles only; the lists' own texts come back with the next show_list()."""
        self.add_group_button.setToolTip(_("Add group"))
        self._groups_title.setText(_("Groups"))
        self._tags_title.setText(_("Tags"))

    def set_tags_visible(self, visible: bool) -> None:
        """View > Tags pane. Hiding it while a tag is picked goes back to All hosts."""
        for widget in (self._tags_line, self._tags_title, self.tags):
            widget.setVisible(visible)
        if not visible and self._filter.kind == "tag":
            self._filter = self._select(Filter("all"))
            self.filter_changed.emit()

    def current_filter(self) -> Filter:
        return self._filter

    def set_searching(self, searching: bool) -> None:
        """A search looks through every host, so nothing shows as picked meanwhile."""
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(True)
        if searching:
            self._clear(self.everything, self.groups, self.tags)
        else:
            self._filter = self._select(self._filter)
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(False)

    def selected_group_id(self) -> str | None:
        return self._filter.value if self._filter.kind == "group" else None

    def group_at(self, position: QPoint) -> str | None:
        """The group under a point of the groups tree; None on empty space."""
        item = self.groups.itemAt(position)
        return item.data(0, ROLE_ID) if item else None

    def select_group(self, group_id: str) -> None:
        self._filter = self._select(Filter("group", group_id))

    def show_list(self, host_list: HostList | None) -> None:
        """Rebuilds the lists from the host list, keeping the current pick when it still exists."""
        wanted = self._filter
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(True)
        self.groups.clear()
        self.tags.clear()
        self.everything.setVisible(host_list is not None)
        if host_list is not None:
            self._everything_item.setText(0, f"{_('All hosts')} ({len(host_list.hosts)})")
            self.groups.fill(host_list)
            for tag, count in sorted(host_list.all_tags().items(), key=lambda t: t[0].casefold()):
                item = QTreeWidgetItem([f"{tag} ({count})"])
                item.setData(0, ROLE_KIND, "tag")
                item.setData(0, ROLE_ID, tag)
                self.tags.addTopLevelItem(item)
        self._filter = self._select(wanted) if host_list is not None else Filter("all")
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(False)
        self._fit_everything()  # the count may have grown a digit

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_everything()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_everything()

    def _fit_everything(self) -> None:
        """Exactly one row tall, whatever padding the theme gives rows and frames, and never
        narrower than "All hosts (N)": the pane can't be dragged past it. Group names
        don't count, so a long one can't make the pane huge (they show a tooltip)."""
        self.everything.doItemsLayout()
        row = self.everything.visualItemRect(self._everything_item).height()
        frame = self.everything.height() - self.everything.viewport().height()
        self.everything.setFixedHeight(max(row, self.everything.sizeHintForRow(0)) + frame)
        sides = self.everything.width() - self.everything.viewport().width()
        self.everything.setMinimumWidth(self.everything.sizeHintForColumn(0) + sides + 12)

    def _select(self, wanted: Filter) -> Filter:
        if wanted.kind == "tag":
            for item in _walk(self.tags.invisibleRootItem()):
                if item.data(0, ROLE_ID) == wanted.value:
                    self.tags.setCurrentItem(item)
                    return wanted
        if wanted.kind == "group":
            for item in _walk(self.groups.invisibleRootItem()):
                if item.data(0, ROLE_ID) == wanted.value:
                    self.groups.setCurrentItem(item)
                    return wanted
        self.everything.setCurrentItem(self._everything_item)
        self._everything_item.setSelected(True)
        self._clear(self.groups, self.tags)
        return Filter("all")

    def _clear(self, *trees: QTreeWidget) -> None:
        for tree in trees:
            tree.blockSignals(True)
            tree.clearSelection()
            tree.blockSignals(False)

    def _everything_picked(self) -> None:
        if not self.everything.selectedItems():
            return
        self._clear(self.groups, self.tags)
        self._filter = Filter("all")
        self.filter_changed.emit()

    def _groups_picked(self) -> None:
        items = self.groups.selectedItems()
        if not items:
            return
        self._clear(self.everything, self.tags)
        self._filter = Filter("group", items[0].data(0, ROLE_ID))
        self.filter_changed.emit()

    def _tags_picked(self) -> None:
        items = self.tags.selectedItems()
        if not items:
            return
        self._clear(self.everything, self.groups)
        self._filter = Filter("tag", items[0].data(0, ROLE_ID))
        self.filter_changed.emit()


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def _walk(root: QTreeWidgetItem) -> Iterable[QTreeWidgetItem]:
    for index in range(root.childCount()):
        child = root.child(index)
        if child is not None:
            yield child
            yield from _walk(child)


class SearchBox(QLineEdit):
    """Above the host table: finds hosts by name, address or logged-on user. Esc clears it;
    Down or Enter moves to the results (never connects, so a typo can't reach a wrong PC)."""

    to_results = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("paneSearch")  # the panes' corners and border, so its edges match
        self.setClearButtonEnabled(True)
        self._icon = self.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self._columns = (True, True)  # address, user: searched only while their columns show
        self._paint_icon()
        self.retranslate()

    def set_columns(self, address: bool, user: bool) -> None:
        self._columns = (address, user)
        self.retranslate()

    def retranslate(self) -> None:
        """The placeholder says exactly what's searched."""
        self.setPlaceholderText(
            {
                (True, True): _("Search name, address, user"),
                (True, False): _("Search name, address"),
                (False, True): _("Search name, user"),
                (False, False): _("Search name"),
            }[self._columns]
        )
        self.setToolTip(_("Searches every host in the list (Ctrl+F)"))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.text():
            self.clear()
            return
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.to_results.emit()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:  # the new theme's colour
            self._paint_icon()

    def _paint_icon(self) -> None:
        self._icon.setIcon(
            tabler_icon("search", self.palette().color(QPalette.ColorRole.PlaceholderText))
        )


class HostTable(QTreeWidget):
    """The host list as a table. A QTreeView-based widget: it selects whole rows in Windows 11.
    Status and User come from Refresh; they're kept in memory, never in the list file."""

    STATUS, USER, ADDRESS, NOTES, GROUP = 1, 2, 3, 5, 6
    # Saved by these keys. Group shows only during a search, right after Computer.
    COLUMNS = ("computer", "status", "user", "address", "tags", "notes", "group")
    columns_changed = Signal()  # a column was shown or hidden

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("grid")  # lines between rows and columns
        self._rows: dict[str, QTreeWidgetItem] = {}
        self._marker = MatchMarker(self, columns={0, self.USER, self.ADDRESS})  # what's searched
        self.setItemDelegate(self._marker)
        self.retranslate()
        header = self.header()
        header.moveSection(self.GROUP, 1)
        self.setColumnHidden(self.GROUP, True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)
        header.sectionResized.connect(self._keep_title_visible)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Selected hosts can be dragged onto a group in the Groups pane, to move them there.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._sized = False

    def set_editable(self, editable: bool) -> None:
        self.setDragEnabled(editable)

    def mimeTypes(self) -> list[str]:
        return [HOSTS_MIME]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        return hosts_mime([item.data(0, ROLE_ID) for item in items])

    def retranslate(self) -> None:
        self.setHeaderLabels(
            [_("Computer"), _("Status"), _("User"), _("Address"), _("Tags"), _("Notes"), _("Group")]
        )

    def set_search(self, needle: str) -> None:
        """Marks the searched text, and shows where each host lives while searching."""
        self._marker.needle = needle
        if needle and self.isColumnHidden(self.GROUP):
            self.setColumnHidden(self.GROUP, False)
            self.resizeColumnToContents(self.GROUP)
            fitted = min(self.columnWidth(self.GROUP) + 16, 260)
            self.setColumnWidth(self.GROUP, max(fitted, self.minimum_width(self.GROUP)))
        self.setColumnHidden(self.GROUP, not needle)
        self.viewport().update()

    def show_hosts(
        self,
        hosts: Sequence[Host],
        cells: Mapping[str, "Cells"],
        groups: Mapping[str, str] | None = None,
    ) -> None:
        """groups: each host's group path, for the Group column."""
        groups = groups or {}
        keep = set(self.selected_ids())
        self.blockSignals(True)
        self.setSortingEnabled(False)
        self.clear()
        self._rows = {}
        for host in hosts:
            item = QTreeWidgetItem(
                [
                    host.name,
                    "",
                    "",
                    host.address,
                    ", ".join(host.tags),
                    _one_line(host.notes),
                    groups.get(host.id, ""),
                ]  # fmt: skip
            )
            item.setData(0, ROLE_ID, host.id)
            self.addTopLevelItem(item)
            self._rows[host.id] = item
            self._fill(item, cells.get(host.id))
            item.setSelected(host.id in keep)
        self.setSortingEnabled(True)
        self.blockSignals(False)
        if hosts and not self._sized:
            self._fit_columns()
        self.itemSelectionChanged.emit()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        # A theme with another font (e.g. Paper's Georgia) makes the old widths cut text off.
        if event.type() == QEvent.Type.FontChange and self.topLevelItemCount():
            self._fit_columns()
        if event.type() == QEvent.Type.PaletteChange:  # the quiet colour of the new theme
            for item in self._rows.values():
                self._tint(item)

    def hidden_columns(self) -> list[str]:
        return [
            key for i, key in enumerate(self.COLUMNS) if i != self.GROUP and self.isColumnHidden(i)
        ]

    def set_hidden_columns(self, keys: object) -> None:
        hidden = set(keys) if isinstance(keys, list) else set()
        for index, key in enumerate(self.COLUMNS[: self.GROUP]):  # Group follows the search
            self.setColumnHidden(index, index > 0 and key in hidden)  # Computer always shows

    def _columns_menu(self, position: QPoint) -> None:
        """Right-click on the column titles: tick the columns to show."""
        menu = QMenu(self)
        header = self.headerItem()
        for index in range(1, self.GROUP):
            item = menu.addAction(header.text(index))
            item.setCheckable(True)
            item.setChecked(not self.isColumnHidden(index))
            item.toggled.connect(lambda shown, i=index: self._show_column(i, shown))
        popup(menu, self.header().viewport().mapToGlobal(position))

    def _show_column(self, index: int, shown: bool) -> None:
        self.setColumnHidden(index, not shown)
        if shown:
            self._keep_title_visible(index, 0, self.columnWidth(index))
        self.columns_changed.emit()

    def minimum_width(self, index: int) -> int:
        """A column is never narrower than its title (plus room for the sort arrow)."""
        title = self.headerItem().text(index)
        return self.header().fontMetrics().horizontalAdvance(title) + 34

    def _keep_title_visible(self, index: int, _old: int, new: int) -> None:
        wanted = self.minimum_width(index)
        if 0 < new < wanted and not self.isColumnHidden(index):
            self.header().resizeSection(index, wanted)

    def _fit_columns(self) -> None:
        # Once, on the first real content: fit the first columns (capped) and let Notes stretch
        # into the rest. Fixed starting widths overflowed narrow windows. Columns stay draggable.
        self._sized = True
        for column in range(self.columnCount()):
            if column == self.NOTES:
                continue
            self.resizeColumnToContents(column)
            fitted = min(self.columnWidth(column) + 16, 260)
            self.setColumnWidth(column, max(fitted, self.minimum_width(column)))

    def show_cells(self, host_id: str, cells: "Cells") -> None:
        """New Refresh results for one host, without rebuilding the table."""
        item = self._rows.get(host_id)
        if item is not None:
            self._fill(item, cells)

    def _fill(self, item: QTreeWidgetItem, cells: "Cells | None") -> None:
        cells = cells or Cells()
        for column, (text, tip, icon, quiet) in (
            (self.STATUS, cells.status),
            (self.USER, cells.user),
        ):
            item.setText(column, text)
            item.setToolTip(column, tip)
            item.setIcon(column, icon if icon is not None else QIcon())
            item.setData(column, ROLE_QUIET, quiet)
        self._tint(item)

    def _tint(self, item: QTreeWidgetItem) -> None:
        """Errors and "not checked" read quieter than real results, in the current theme."""
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for column in (self.STATUS, self.USER):
            quiet = bool(item.data(column, ROLE_QUIET))
            item.setData(column, Qt.ItemDataRole.ForegroundRole, muted if quiet else None)

    def selected_ids(self) -> list[str]:
        return [item.data(0, ROLE_ID) for item in self.selectedItems()]

    def select_ids(self, host_ids: Iterable[str]) -> None:
        wanted = set(host_ids)
        self.clearSelection()
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None and item.data(0, ROLE_ID) in wanted:
                item.setSelected(True)
                self.scrollToItem(item)


@dataclass(frozen=True)
class Cells:
    """What the Status and User columns show for one host: text, tooltip, icon, quiet."""

    status: tuple[str, str, QIcon | None, bool] = ("", "", None, False)
    user: tuple[str, str, QIcon | None, bool] = ("", "", None, False)


class MatchMarker(QStyledItemDelegate):
    """Marks the searched text in each cell, like a highlighter."""

    COLOR = QColor(255, 196, 0, 96)  # see-through, so it reads in light and dark themes

    def __init__(self, parent: QWidget, columns: set[int]) -> None:
        super().__init__(parent)
        self.needle = ""
        self._columns = columns

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().paint(painter, option, index)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        searched = self.needle and index.column() in self._columns and isinstance(text, str)
        start = text.casefold().find(self.needle) if searched else -1
        if start < 0:
            return
        shown = QStyleOptionViewItem(option)
        self.initStyleOption(shown, index)
        widget = shown.widget  # type: ignore[attr-defined]
        style = widget.style() if widget is not None else None
        if style is None:
            return
        area = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, shown, widget)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1
        metrics = QFontMetrics(shown.font)  # type: ignore[attr-defined]
        left = area.left() + margin + metrics.horizontalAdvance(text[:start])
        width = metrics.horizontalAdvance(text[start : start + len(self.needle)])
        mark = QRect(left, area.top() + 2, width, area.height() - 4).intersected(area)
        painter.fillRect(mark, self.COLOR)


def _one_line(text: str) -> str:
    return " ".join(text.split())


class DetailsPane(QWidget):
    """Details of the selected host, or a hint when none or several are selected."""

    def __init__(self) -> None:
        super().__init__()
        self._hint = QLabel()
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)

        self._values: dict[str, QLabel] = {}
        form_page = QWidget()
        form = QFormLayout(form_page)
        form.setContentsMargins(12, 10, 12, 10)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._heading = QLabel()
        font = self._heading.font()
        font.setBold(True)
        self._heading.setFont(font)
        form.addRow(self._heading)
        self._labels: dict[str, QLabel] = {}
        for key in ("name", "address", "group", "connection", "status", "users", "tags", "notes"):
            value = QLabel()
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._values[key], self._labels[key] = value, QLabel()
            form.addRow(self._labels[key], value)

        # A card with the lists' background, so the three panes read as a set in every theme.
        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setBackgroundRole(QPalette.ColorRole.Base)
        card.setAutoFillBackground(True)
        self._pages = QStackedLayout(card)
        self._pages.addWidget(self._hint)
        self._pages.addWidget(form_page)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        self.retranslate()
        self.show_host(None, "", 0)

    def retranslate(self) -> None:
        """Headings only; the hint comes back with the next show_host()."""
        self._heading.setText(_("Information"))
        for key, text in (
            ("name", _("Name")),
            ("address", _("Address")),
            ("group", _("Group")),
            ("connection", _("Connection")),
            ("status", _("Status")),
            ("users", _("Logged on")),
            ("tags", _("Tags")),
            ("notes", _("Notes")),
        ):
            self._labels[key].setText(text)

    def show_host(
        self,
        host: Host | None,
        group: str,
        selected: int,
        connection: str = "",
        status: str = "",
        users: str = "",
        users_tip: str = "",
        summary: str = "",
    ) -> None:
        """summary: what the table shows (online, offline…), above the hint when none is picked."""
        if host is None:
            if selected > 1:
                self._hint.setText(
                    ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)
                )
            else:
                hint = _("Select a host to see its details.")
                self._hint.setText(f"{summary}\n\n{hint}" if summary else hint)
            self._pages.setCurrentIndex(0)
            return
        values = {
            "name": host.name,
            "address": host.address or "—",
            "group": group,
            "connection": connection or "—",
            # Not checked yet: say how, rather than a bare dash.
            "status": status or _("Not checked: use Refresh"),
            "users": users or _("Not checked: use Refresh"),
            "tags": ", ".join(host.tags) or "—",
            "notes": host.notes or "—",
        }
        for key, text in values.items():
            self._values[key].setText(text)
        self._values["users"].setToolTip(users_tip)  # full DOMAIN\names when they're hidden
        self._pages.setCurrentIndex(1)

    def shown_value(self, key: str) -> str:
        return self._values[key].text()
