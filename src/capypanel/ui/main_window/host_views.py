"""The three panes of the main window: groups and tags, the host table, and host details."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedLayout,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host, HostList
from capypanel.core.i18n import _, ngettext
from capypanel.ui.groups import HOSTS_MIME, ROLE_ID, ROLE_KIND, GroupTree, hosts_mime


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
    """ "All computers" pinned on top, the groups below it (in the list's own order, rearranged
    by dragging), and the tags. Picking one filters the table."""

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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(header)
        layout.addWidget(self.everything)
        layout.addWidget(self.groups, 3)
        layout.addWidget(self._tags_title)
        layout.addWidget(self.tags, 1)

        self.everything.itemSelectionChanged.connect(self._everything_picked)
        self.groups.itemSelectionChanged.connect(self._groups_picked)
        self.tags.itemSelectionChanged.connect(self._tags_picked)
        self.retranslate()

    def retranslate(self) -> None:
        """Titles only; the lists' own texts come back with the next show_list()."""
        self.add_group_button.setToolTip(_("Add group"))
        self._groups_title.setText(_("Groups"))
        self._tags_title.setText(_("Tags"))

    def current_filter(self) -> Filter:
        return self._filter

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
            self._everything_item.setText(0, f"{_('All computers')} ({len(host_list.hosts)})")
            self.groups.fill(host_list)
            for tag, count in sorted(host_list.all_tags().items(), key=lambda t: t[0].casefold()):
                item = QTreeWidgetItem([f"{tag} ({count})"])
                item.setData(0, ROLE_KIND, "tag")
                item.setData(0, ROLE_ID, tag)
                self.tags.addTopLevelItem(item)
        self._filter = self._select(wanted) if host_list is not None else Filter("all")
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_everything()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_everything()

    def _fit_everything(self) -> None:
        """Exactly one row tall, whatever padding the theme gives rows and frames."""
        self.everything.doItemsLayout()
        row = self.everything.visualItemRect(self._everything_item).height()
        frame = self.everything.height() - self.everything.viewport().height()
        self.everything.setFixedHeight(max(row, self.everything.sizeHintForRow(0)) + frame)

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


def _walk(root: QTreeWidgetItem) -> Iterable[QTreeWidgetItem]:
    for index in range(root.childCount()):
        child = root.child(index)
        if child is not None:
            yield child
            yield from _walk(child)


class HostTable(QTreeWidget):
    """The host list as a table. A QTreeView-based widget: it selects whole rows in Windows 11."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("grid")  # lines between rows and columns
        self.retranslate()
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
        self.setHeaderLabels([_("Computer"), _("Address"), _("Tags"), _("Notes")])

    def show_hosts(self, hosts: Sequence[Host]) -> None:
        keep = set(self.selected_ids())
        self.blockSignals(True)
        self.setSortingEnabled(False)
        self.clear()
        for host in hosts:
            item = QTreeWidgetItem(
                [host.name, host.address, ", ".join(host.tags), _one_line(host.notes)]
            )
            item.setData(0, ROLE_ID, host.id)
            self.addTopLevelItem(item)
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

    def _fit_columns(self) -> None:
        # Once, on the first real content: fit the first columns (capped) and let Notes stretch
        # into the rest. Fixed starting widths overflowed narrow windows. Columns stay draggable.
        self._sized = True
        for column in range(self.columnCount() - 1):
            self.resizeColumnToContents(column)
            self.setColumnWidth(column, min(self.columnWidth(column) + 16, 260))

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
        for key in ("name", "address", "group", "connection", "tags", "notes"):
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
            ("tags", _("Tags")),
            ("notes", _("Notes")),
        ):
            self._labels[key].setText(text)

    def show_host(self, host: Host | None, group: str, selected: int, connection: str = "") -> None:
        if host is None:
            if selected > 1:
                self._hint.setText(
                    ngettext("{n} host selected", "{n} hosts selected", selected).format(n=selected)
                )
            else:
                self._hint.setText(_("Select a host to see its details."))
            self._pages.setCurrentIndex(0)
            return
        values = {
            "name": host.name,
            "address": host.address or "—",
            "group": group,
            "connection": connection or "—",
            "tags": ", ".join(host.tags) or "—",
            "notes": host.notes or "—",
        }
        for key, text in values.items():
            self._values[key].setText(text)
        self._pages.setCurrentIndex(1)

    def shown_value(self, key: str) -> str:
        return self._values[key].text()
