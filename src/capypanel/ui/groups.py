"""The groups as a tree that can be rearranged by dragging, "Move to", and Inventory > Manage
groups….
Groups show in the list's own order (not sorted), so a team can arrange them as it likes;
"Sort A–Z" is a one-time button."""

from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QImage,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOptionMenuItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.ui.hosts import group_path
from capypanel.ui.menus import popup
from capypanel.ui.notes import notes
from capypanel.ui.themes import engine as themes

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ID = Qt.ItemDataRole.UserRole + 1
GROUP_INDENT = 14  # px per nesting level; Windows 11's ~30 px ran deep trees off the pane
HOSTS_MIME = "application/x-capypanel-hosts"  # host ids dragged from the host table
GROUPS_MIME = "application/x-capypanel-groups"  # group ids dragged within the groups tree
TREE_INDENT = "\u2003\u2009"  # per level in a TreeMenu, room for its lines (~16 px)


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

    def set_editable(self, editable: bool) -> None:
        """Read-only lists can't be rearranged."""
        mode = QAbstractItemView.DragDropMode.InternalMove
        self.setDragDropMode(mode if editable else QAbstractItemView.DragDropMode.NoDragDrop)
        self.setAcceptDrops(editable)
        self.setDropIndicatorShown(editable)

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        # The tree's own data, plus the group ids, so the Groups heading can take the drop.
        data = super().mimeData(items)
        data.setData(GROUPS_MIME, "\n".join(i.data(0, ROLE_ID) for i in items).encode())
        return data

    def fill(self, host_list: HostList, counts: bool = True) -> None:
        # Groups closed by hand stay closed when the tree is rebuilt after a change.
        closed = {
            i.data(0, ROLE_ID)
            for i in _all_items(self.invisibleRootItem())
            if i.childCount() and not i.isExpanded()
        }
        self.clear()
        self._add(host_list, None, self.invisibleRootItem(), counts)
        self.expandAll()
        for item in _all_items(self.invisibleRootItem()):
            if item.data(0, ROLE_ID) in closed:
                item.setExpanded(False)

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


class GroupsHeading(QLabel):
    """The "Groups" title above the tree. A group dropped on it moves to the top level."""

    group_dropped = Signal(str)  # group id

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(GROUPS_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)  # the tree keeps its rows
            event.accept()
            self._show_target(True)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._show_target(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._show_target(False)
        ids = bytes(event.mimeData().data(GROUPS_MIME).data()).decode().split("\n")
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        for group_id in (i for i in ids if i):
            self.group_dropped.emit(group_id)

    def _show_target(self, shown: bool) -> None:
        # Stylesheets read the property: the heading lights up while a group is over it.
        self.setProperty("dropTarget", shown)
        self.style().unpolish(self)
        self.style().polish(self)


class TreeMenu(QMenu):
    """A menu indented like a tree, with the tree's lines drawn into the indent. The items stay
    plain menu items, so hover, ticks and the keyboard work as in any menu."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._branches: dict[QAction, tuple[bool, ...]] = {}
        self._text_left: int | None = None
        self.marked: QAction | None = None  # tinted, so it stands out in a long menu

    def add_row(self, text: str, branches: tuple[bool, ...] = ()) -> QAction:
        """`branches`: one per level below the top, whether the group there is its parent's last
        (its line stops)."""
        action = self.addAction(TREE_INDENT * len(branches) + text.replace("&", "&&"))
        if branches:
            self._branches[action] = branches
        return action

    def branches(self, action: QAction) -> tuple[bool, ...]:
        return self._branches.get(action, ())

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        if self.marked is not None:
            # The menu paints its own background, so the tint goes on top and the item is
            # drawn again over it, keeping its text crisp.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(themes.menu_mark())
            rect = self.actionGeometry(self.marked)
            painter.drawRoundedRect(rect.adjusted(1, 0, -1, 0), 6, 6)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, self.marked)
            option.rect = rect
            self.style().drawControl(QStyle.ControlElement.CE_MenuItem, option, painter, self)
        step = self.fontMetrics().horizontalAdvance(TREE_INDENT)
        color = QColor(self.palette().color(QPalette.ColorRole.Text))
        color.setAlpha(90)
        painter.setPen(QPen(color, 1))
        for action, branches in self._branches.items():
            rect = self.actionGeometry(action)
            left, mid = self._find_text_left(action), rect.center().y()
            for level, last in enumerate(branches):
                x = left + level * step + 4
                if level < len(branches) - 1:  # a group further up: its line runs on past us
                    if not last:
                        painter.drawLine(x, rect.top(), x, rect.bottom())
                else:  # this item's own branch
                    painter.drawLine(x, rect.top(), x, mid if last else rect.bottom())
                    painter.drawLine(x, mid, x + step - 6, mid)
        painter.end()

    def _find_text_left(self, action: QAction) -> int:
        """Where the style starts an item's text (each theme pads menus its own way): the item
        is drawn with and without a block of text, and the first column that differs is it."""
        if self._text_left is None:
            option = QStyleOptionMenuItem()
            self.initStyleOption(option, action)
            size = self.actionGeometry(action).size()
            option.rect = QRect(QPoint(0, 0), size)
            option.state &= ~QStyle.StateFlag.State_Selected
            images = []
            for text in ("", "\u2588"):
                option.text = text
                image = QImage(size, QImage.Format.Format_ARGB32)
                image.fill(0)
                painter = QPainter(image)
                self.style().drawControl(QStyle.ControlElement.CE_MenuItem, option, painter, self)
                painter.end()
                images.append(image)
            blank, text = images
            columns = range(size.width())
            rows = range(size.height())
            self._text_left = next(
                (x for x in columns if any(blank.pixel(x, y) != text.pixel(x, y) for y in rows)), 0
            )
        return self.actionGeometry(action).left() + self._text_left


def fill_move_menu(
    menu: TreeMenu, host_list: HostList, group_id: str, apply: Callable[[str | None], None]
) -> None:
    """Move to: "Top level", then every group this one can go into, as a tree. Where it is now
    is ticked and tinted. `apply` gets the new parent's id, or None for the top level."""
    group = host_list.group(group_id)
    current = group.parent if group else None
    exclusive = QActionGroup(menu)
    top = menu.add_row(_("Top level"))
    _tick(menu, exclusive, top, current is None)
    if current is not None:
        top.triggered.connect(lambda _checked=False: apply(None))
    if host_list.groups:
        menu.addSeparator()
    # It can't go into itself or its own groups.
    fill_group_menu(menu, host_list, apply, current=current, skip=host_list.subtree(group_id))
    for item in menu.actions():
        if item.isCheckable():
            exclusive.addAction(item)


def fill_group_menu(
    menu: TreeMenu,
    host_list: HostList,
    apply: Callable[[str], None],
    *,
    current: str | None = None,
    skip: Iterable[str] = (),
) -> None:
    """Every group as a tree (groups in `skip` left out); `current` is ticked and tinted, and
    picking it does nothing. `apply` gets the picked group's id."""
    left_out = set(skip)

    def walk(parent_id: str | None, branches: tuple[bool, ...]) -> None:
        children = [c for c in host_list.children(parent_id) if c.id not in left_out]
        for index, child in enumerate(children):
            # Top-level groups have no line; each level below adds one.
            mine = (*branches, index == len(children) - 1) if parent_id else ()
            item = menu.add_row(child.name, mine)
            item.setData(child.id)
            _tick(menu, None, item, child.id == current)
            if child.id != current:
                item.triggered.connect(lambda _checked=False, g=child.id: apply(g))
            walk(child.id, mine)

    walk(None, ())


def _tick(menu: TreeMenu, exclusive: QActionGroup | None, item: QAction, ticked: bool) -> None:
    item.setCheckable(True)
    item.setChecked(ticked)
    if ticked:
        menu.marked = item
    if exclusive is not None:
        exclusive.addAction(item)


class ManageGroupsDialog(QDialog):
    """Inventory > Manage groups…: reorder and nest every group at once, then OK."""

    def __init__(self, parent: QWidget | None, host_list: HostList) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Manage groups"))
        self._hosts = host_list
        self.tree = GroupTree()
        self.tree.fill(host_list, counts=False)
        self.up_button = QPushButton(_("Move &up"))
        self.down_button = QPushButton(_("Move &down"))
        self.move_button = QPushButton(_("Move &to"))
        self.sort_button = QPushButton(_("&Sort A–Z"))
        self.sort_button.setToolTip(
            _("Sorts every level by name, once; you can rearrange them after")
        )
        buttons = QVBoxLayout()
        for button in (self.up_button, self.down_button, self.move_button, self.sort_button):
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
        self.move_button.clicked.connect(self._show_move_menu)
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
        self.move_button.setEnabled(item is not None)
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

    def move_menu(self) -> TreeMenu:
        """The "Move to" menu for the picked group, from the groups as arranged here so far."""
        menu = TreeMenu("", self)
        item = self.tree.currentItem()
        if item is not None:
            arranged = self._hosts.arrange_groups(self.tree.order())
            fill_move_menu(menu, arranged, item.data(0, ROLE_ID), self._move_to)
        return menu

    def _show_move_menu(self) -> None:
        popup(self.move_menu(), self.move_button.mapToGlobal(self.move_button.rect().bottomLeft()))

    def _move_to(self, new_id: str | None) -> None:
        item = self.tree.currentItem()
        old_parent = self._siblings(item)
        if item is None or old_parent is None:
            return
        expanded = _expanded_ids(item)
        old_parent.removeChild(item)
        target = self.tree.invisibleRootItem()
        for candidate in _all_items(target):
            if new_id is not None and candidate.data(0, ROLE_ID) == new_id:
                target = candidate
        target.addChild(item)
        target.setExpanded(True)
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


def _all_items(root: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    found = []
    for index in range(root.childCount()):
        child = root.child(index)
        if child is not None:
            found.append(child)
            found += _all_items(child)
    return found


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
