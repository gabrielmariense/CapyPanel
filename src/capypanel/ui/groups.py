"""The groups as a tree that can be rearranged by dragging, and Inventory > Manage groups….
Groups show in the list's own order (not sorted), so a team can arrange them as it likes;
"Sort A–Z" is a one-time button."""

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.ui.hosts import group_path
from capypanel.ui.notes import notes

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ID = Qt.ItemDataRole.UserRole + 1
GROUP_INDENT = 14  # px per nesting level; Windows 11's ~30 px ran deep trees off the pane
HOSTS_MIME = "application/x-capypanel-hosts"  # host ids dragged from the host table


def hosts_mime(host_ids: list[str]) -> QMimeData:
    data = QMimeData()
    data.setData(HOSTS_MIME, "\n".join(host_ids).encode())
    return data


class GroupTree(QTreeWidget):
    """The groups, in the list's order. Dragging a group reorders or nests it (`rearranged`);
    hosts dropped from the host table onto a group move there (`hosts_dropped`)."""

    rearranged = Signal()
    hosts_dropped = Signal(list, str)  # host ids, group id

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setIndentation(GROUP_INDENT)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.set_editable(True)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Rows placed before the theme's padding arrived would stay cramped: place them again.
        self.doItemsLayout()

    def set_editable(self, editable: bool) -> None:
        """Read-only lists can't be rearranged."""
        mode = QAbstractItemView.DragDropMode.InternalMove
        self.setDragDropMode(mode if editable else QAbstractItemView.DragDropMode.NoDragDrop)
        self.setAcceptDrops(editable)
        self.setDropIndicatorShown(editable)

    def fill(self, host_list: HostList, counts: bool = True) -> None:
        self.clear()
        self._add(host_list, None, self.invisibleRootItem(), counts)
        self.expandAll()

    def _add(
        self, host_list: HostList, parent_id: str | None, parent: QTreeWidgetItem, counts: bool
    ) -> None:
        for group in host_list.children(parent_id):
            text = group.name
            if counts:
                text = f"{group.name} ({len(host_list.hosts_in(group.id))})"
            item = QTreeWidgetItem([text])
            item.setData(0, ROLE_KIND, "group")
            item.setData(0, ROLE_ID, group.id)
            item.setToolTip(0, group_path(host_list, group.id))  # full name when cut short
            parent.addChild(item)
            self._add(host_list, group.id, item, counts)

    def order(self) -> list[tuple[str, str | None]]:
        """Every group with its parent, in the tree's order: what arrange_groups() takes."""
        found: list[tuple[str, str | None]] = []

        def walk(item: QTreeWidgetItem, parent: str | None) -> None:
            for index in range(item.childCount()):
                child = item.child(index)
                if child is not None:
                    found.append((child.data(0, ROLE_ID), parent))
                    walk(child, child.data(0, ROLE_ID))

        walk(self.invisibleRootItem(), None)
        return found

    # ---- dropping hosts from the table ----

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME) and self.acceptDrops():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME):
            item = self.itemAt(event.position().toPoint())
            if item is not None and self.acceptDrops():
                self.setCurrentItem(item)  # shows where the hosts will go
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME):
            item = self.itemAt(event.position().toPoint())
            text = bytes(event.mimeData().data(HOSTS_MIME).data()).decode()
            ids = [i for i in text.split("\n") if i]
            if item is not None and ids:
                event.acceptProposedAction()
                self.hosts_dropped.emit(ids, item.data(0, ROLE_ID))
            return
        super().dropEvent(event)
        self.rearranged.emit()


class ManageGroupsDialog(QDialog):
    """Inventory > Manage groups…: reorder and nest every group at once, then OK."""

    def __init__(self, parent: QWidget | None, host_list: HostList) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Manage groups"))
        self.tree = GroupTree()
        self.tree.fill(host_list, counts=False)
        self.up_button = QPushButton(_("Move &up"))
        self.down_button = QPushButton(_("Move &down"))
        self.sort_button = QPushButton(_("&Sort A–Z"))
        self.sort_button.setToolTip(_("Sorts every level by name, once; you can rearrange after"))
        buttons = QVBoxLayout()
        for button in (self.up_button, self.down_button, self.sort_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.tree, 1)
        row.addLayout(buttons)
        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(row, 1)
        layout.addWidget(
            notes(
                _("Drag a group to move it, or drop it onto another group to put it inside."),
                _("Nothing changes until you click OK."),
            )
        )
        layout.addWidget(self.box)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.sort_button.clicked.connect(self._sort)
        self.tree.itemSelectionChanged.connect(self._update)
        self._update()
        self.resize(460, 480)

    def order(self) -> list[tuple[str, str | None]]:
        return self.tree.order()

    def _update(self) -> None:
        item = self.tree.currentItem()
        siblings = self._siblings(item)
        index = siblings.indexOfChild(item) if item is not None and siblings else -1
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < (siblings.childCount() - 1 if siblings else 0))

    def _siblings(self, item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        if item is None:
            return None
        return item.parent() or self.tree.invisibleRootItem()

    def _move(self, step: int) -> None:
        item = self.tree.currentItem()
        siblings = self._siblings(item)
        if item is None or siblings is None:
            return
        index = siblings.indexOfChild(item)
        if not 0 <= index + step < siblings.childCount():
            return
        expanded = _expanded_ids(item)
        siblings.takeChild(index)
        siblings.insertChild(index + step, item)
        _expand(item, expanded)
        self.tree.setCurrentItem(item)
        self._update()

    def _sort(self) -> None:
        root = self.tree.invisibleRootItem()
        # Read before sorting: a group taken out of the tree forgets that it was open.
        expanded: set[str] = set()
        for index in range(root.childCount()):
            child = root.child(index)
            if child is not None:
                expanded |= _expanded_ids(child)

        def sort(parent: QTreeWidgetItem) -> None:
            children = [parent.takeChild(0) for _i in range(parent.childCount())]
            for child in sorted((c for c in children if c), key=lambda c: c.text(0).casefold()):
                parent.addChild(child)
                sort(child)

        sort(root)
        for index in range(root.childCount()):
            child = root.child(index)
            if child is not None:
                _expand(child, expanded)
        self._update()


def _expanded_ids(item: QTreeWidgetItem) -> set[str]:
    """Which of the item's groups are open, so moving it keeps them that way."""
    found = {item.data(0, ROLE_ID)} if item.isExpanded() else set()
    for index in range(item.childCount()):
        child = item.child(index)
        if child is not None:
            found |= _expanded_ids(child)
    return found


def _expand(item: QTreeWidgetItem, ids: set[str]) -> None:
    item.setExpanded(item.data(0, ROLE_ID) in ids)
    for index in range(item.childCount()):
        child = item.child(index)
        if child is not None:
            _expand(child, ids)
