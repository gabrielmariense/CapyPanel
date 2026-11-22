from collections.abc import Callable, Iterable, Sequence

from PySide6.QtCore import (
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    Qt,
    Signal,
)
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

from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.i18n import _
from capypanel.ui import help_links
from capypanel.ui.dialogs import ok_cancel
from capypanel.ui.hosts import group_path
from capypanel.ui.menus import popup
from capypanel.ui.notes import notes
from capypanel.ui.themes import engine as themes

ROLE_KIND = Qt.ItemDataRole.UserRole
ROLE_ID = Qt.ItemDataRole.UserRole + 1
GROUP_INDENT = 14  # px per nesting level; Windows 11's ~30 px ran deep trees off the pane
HOSTS_MIME = "application/x-capypanel-hosts"
GROUPS_MIME = "application/x-capypanel-groups"
TREE_INDENT = "\u2003\u2009"  # per level in a TreeMenu, room for its lines (~16 px)


def hosts_mime(host_ids: list[str]) -> QMimeData:
    data = QMimeData()
    data.setData(HOSTS_MIME, "\n".join(host_ids).encode())
    return data


def dropped_hosts(event: QDropEvent) -> list[str]:
    text = bytes(event.mimeData().data(HOSTS_MIME).data()).decode()
    return [i for i in text.split("\n") if i]


class HostDropTree(QTreeWidget):
    hosts_dropped = Signal(list, str)

    def __init__(self) -> None:
        super().__init__()
        self._picked_before: list[QTreeWidgetItem] | None = None

    def drop_group(self, item: QTreeWidgetItem) -> str | None:
        return item.data(0, ROLE_ID)

    def _host_target(self, event: QDragMoveEvent | QDropEvent) -> QTreeWidgetItem | None:
        item = self.itemAt(event.position().toPoint())
        if item is None or not self.acceptDrops() or self.drop_group(item) is None:
            return None
        return item

    def _mark(self, item: QTreeWidgetItem | None) -> None:
        if item is None:
            self._unmark()
            return
        if self._picked_before is None:
            self._picked_before = self.selectedItems()
        self.blockSignals(True)
        self.setCurrentItem(item)
        self.blockSignals(False)

    def _unmark(self) -> None:
        if self._picked_before is None:
            return
        self.blockSignals(True)
        self.clearSelection()
        for item in self._picked_before:
            item.setSelected(True)
        self.blockSignals(False)
        self._picked_before = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME) and self.acceptDrops():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME):
            item = self._host_target(event)
            self._mark(item)
            if item is not None:
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._unmark()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(HOSTS_MIME):
            item = self._host_target(event)
            self._unmark()
            ids = dropped_hosts(event)
            group_id = self.drop_group(item) if item is not None else None
            if group_id is not None and ids:
                event.acceptProposedAction()
                self.hosts_dropped.emit(ids, group_id)
            return
        super().dropEvent(event)


class GroupTree(HostDropTree):
    rearranged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setIndentation(GROUP_INDENT)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.set_editable(True)
        self._root: QTreeWidgetItem | None = None
        self.tree_lines = False
        self.itemCollapsed.connect(self._keep_root_open)

    def drawBranches(
        self, painter: QPainter, rect: QRect, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().drawBranches(painter, rect, index)
        item = self.itemFromIndex(index) if isinstance(index, QModelIndex) else None
        if not self.tree_lines or item is None:
            return
        lasts: list[bool] = []
        node: QTreeWidgetItem | None = item
        while node is not None:
            siblings = node.parent() or self.invisibleRootItem()
            lasts.insert(0, siblings.indexOfChild(node) == siblings.childCount() - 1)
            node = node.parent()
        depth = len(lasts) - 1
        step = self.indentation()
        left = rect.right() + 1 - (depth + 1) * step

        def middle(level: int) -> int:
            return left + level * step + step // 2

        arrow = max(4, step // 3)
        top, mid, bottom = rect.top(), rect.center().y(), rect.bottom() + 1
        color = QColor(self.palette().color(QPalette.ColorRole.Text))
        color.setAlpha(90)
        painter.save()
        painter.setPen(QPen(color, 1))
        if item.childCount() and item.isExpanded():
            painter.drawLine(middle(depth), mid + arrow, middle(depth), bottom)
        if depth == 0:
            painter.restore()
            return
        for level in range(1, depth):
            if not lasts[level]:
                painter.drawLine(middle(level - 1), top, middle(level - 1), bottom)
        x = middle(depth - 1)
        painter.drawLine(x, top, x, mid if lasts[depth] else bottom)
        end = middle(depth) - arrow if item.childCount() else left + (depth + 1) * step - 3
        painter.drawLine(x, mid, end, mid)
        painter.restore()

    def top(self) -> QTreeWidgetItem:
        return self._root or self.invisibleRootItem()

    def _keep_root_open(self, item: QTreeWidgetItem) -> None:
        if item is self._root:
            item.setExpanded(True)

    def set_editable(self, editable: bool) -> None:
        mode = QAbstractItemView.DragDropMode.InternalMove
        self.setDragDropMode(mode if editable else QAbstractItemView.DragDropMode.NoDragDrop)
        self.setAcceptDrops(editable)
        self.setDropIndicatorShown(editable)

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        data = super().mimeData(items)
        data.setData(GROUPS_MIME, "\n".join(i.data(0, ROLE_ID) for i in items).encode())
        return data

    def fill(self, host_list: HostList, counts: bool = True, rooted: bool = False) -> None:
        closed = {
            i.data(0, ROLE_ID)
            for i in _all_items(self.invisibleRootItem())
            if i.childCount() and not i.isExpanded()
        }
        self.clear()
        self._root = None
        if rooted:
            self._root = QTreeWidgetItem([_("Groups")])
            self._root.setData(0, ROLE_KIND, "root")
            self._root.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            self.addTopLevelItem(self._root)
            top = self.invisibleRootItem()
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        self._add(host_list, None, self.top(), counts)
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
            item.setToolTip(0, group_path(host_list, group.id))
            parent.addChild(item)
            self._add(host_list, group.id, item, counts)

    def order(self) -> list[tuple[str, str | None]]:
        found: list[tuple[str, str | None]] = []

        def walk(item: QTreeWidgetItem, parent: str | None) -> None:
            for index in range(item.childCount()):
                child = item.child(index)
                if child is not None:
                    found.append((child.data(0, ROLE_ID), parent))
                    walk(child, child.data(0, ROLE_ID))

        walk(self.top(), None)
        return found

    def _onto_empty_space(self, event: QDragMoveEvent | QDropEvent) -> bool:
        return (
            self._root is not None
            and event.mimeData().hasFormat(GROUPS_MIME)
            and self.itemAt(event.position().toPoint()) is None
        )

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._onto_empty_space(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def onto_root(self, event: QDropEvent) -> QDropEvent:
        """As if dropped onto "Groups": moving the group by hand made Qt delete the dragged row."""
        assert self._root is not None
        self.scrollToItem(self._root)  # the row must be in view for the drop to land on it
        point = QPointF(self.visualItemRect(self._root).center())
        moved = QDropEvent(
            point, event.possibleActions(), event.mimeData(), event.buttons(), event.modifiers()
        )
        moved.setDropAction(event.dropAction())
        return moved

    def dropEvent(self, event: QDropEvent) -> None:
        if self._onto_empty_space(event):
            ids = bytes(event.mimeData().data(GROUPS_MIME).data()).decode().split("\n")
            dragged = [i for i in _all_items(self.top()) if i.data(0, ROLE_ID) in ids]
            open_ids = set().union(*(_expanded_ids(i) for i in dragged))
            scrolled = self.verticalScrollBar().value()
            moved = self.onto_root(event)
            super().dropEvent(moved)
            event.setDropAction(moved.dropAction())
            event.setAccepted(moved.isAccepted())
            for item in _all_items(self.top()):
                if item.data(0, ROLE_ID) in ids:
                    _expand(item, open_ids)
            self.verticalScrollBar().setValue(scrolled)
            self.rearranged.emit()
            return
        hosts = event.mimeData().hasFormat(HOSTS_MIME)
        super().dropEvent(event)
        if not hosts:
            self.rearranged.emit()


class GroupsHeading(QLabel):
    group_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(GROUPS_MIME):
            event.setDropAction(Qt.DropAction.CopyAction)
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
        self.setProperty("dropTarget", shown)
        self.style().unpolish(self)
        self.style().polish(self)


class TreeMenu(QMenu):
    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._branches: dict[QAction, tuple[bool, ...]] = {}
        self._text_left: int | None = None
        self.marked: QAction | None = None

    def add_row(self, text: str, branches: tuple[bool, ...] = ()) -> QAction:
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
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(themes.menu_mark())
            rect = self.actionGeometry(self.marked)
            corner = themes.current().control
            painter.drawRoundedRect(rect.adjusted(1, 0, -1, 0), corner, corner)
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
                if level < len(branches) - 1:
                    if not last:
                        painter.drawLine(x, rect.top(), x, rect.bottom())
                else:
                    painter.drawLine(x, rect.top(), x, mid if last else rect.bottom())
                    painter.drawLine(x, mid, x + step - 6, mid)
        painter.end()

    def _find_text_left(self, action: QAction) -> int:
        """Each theme pads menus its own way: it's the first column where the item drawn with
        and without text differs."""
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
    group = host_list.group(group_id)
    current = group.parent if group else None
    exclusive = QActionGroup(menu)
    top = menu.add_row(_("Groups"))
    _tick(menu, exclusive, top, current is None)
    if current is not None:
        top.triggered.connect(lambda _checked=False: apply(None))
    fill_group_menu(
        menu, host_list, apply, current=current, skip=host_list.subtree(group_id), rooted=True
    )
    for item in menu.actions():
        if item.isCheckable():
            exclusive.addAction(item)


def fill_host_move_menu(
    menu: TreeMenu,
    host_list: HostList,
    apply: Callable[[str], None],
    *,
    current: str | None = None,
    skip: Iterable[str] = (),
) -> None:
    left_out = set(skip)
    loose = menu.add_row(_("No group"))
    loose.setData(NO_GROUP)
    _tick(menu, None, loose, current == NO_GROUP)
    if current != NO_GROUP:
        loose.triggered.connect(lambda _checked=False: apply(NO_GROUP))
    if any(g.id not in left_out for g in host_list.groups):
        menu.addSeparator()
    fill_group_menu(menu, host_list, apply, current=current or None, skip=left_out)


def fill_group_menu(
    menu: TreeMenu,
    host_list: HostList,
    apply: Callable[[str], None],
    *,
    current: str | None = None,
    skip: Iterable[str] = (),
    rooted: bool = False,
) -> None:
    left_out = set(skip)

    def walk(parent_id: str | None, branches: tuple[bool, ...]) -> None:
        children = [c for c in host_list.children(parent_id) if c.id not in left_out]
        for index, child in enumerate(children):
            last = index == len(children) - 1
            mine = (*branches, last) if parent_id or rooted else ()
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
    def __init__(self, parent: QWidget | None, host_list: HostList) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Manage groups"))
        self._hosts = host_list
        self.tree = GroupTree()
        self.tree.fill(host_list, counts=False, rooted=True)
        self.tree.tree_lines = True
        self.tree.setIndentation(GROUP_INDENT + 8)
        self.up_button = QPushButton(_("Move &up"))
        self.down_button = QPushButton(_("Move &down"))
        self.move_button = QPushButton(_("Move &to"))
        self.sort_button = QPushButton(_("&Sort A–Z"))
        self.sort_button.setToolTip(
            _("Sorts every level by name, once; you can rearrange them after")
        )
        buttons = QHBoxLayout()
        for button in (self.up_button, self.down_button, self.move_button, self.sort_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.box = ok_cancel(self, _("Save"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        layout.addWidget(
            notes(
                _("Drag a group to move it, or drop it onto another group to put it inside."),
                _("Nothing changes until you click Save."),
            )
        )
        self.help_button = help_links.HelpButton("host-lists-arrange-hosts-in-groups")
        layout.addLayout(help_links.row(self.help_button, self.box))
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.move_button.clicked.connect(self._show_move_menu)
        self.sort_button.clicked.connect(self._sort)
        self.tree.itemSelectionChanged.connect(self._update)
        self._update()
        self.resize(max(460, self.sizeHint().width()), 480)

    def order(self) -> list[tuple[str, str | None]]:
        return self.tree.order()

    def _update(self) -> None:
        item = self.tree.currentItem()
        siblings = self._siblings(item)
        index = siblings.indexOfChild(item) if item is not None and siblings else -1
        self.up_button.setEnabled(index > 0)
        self.move_button.setEnabled(siblings is not None)
        self.down_button.setEnabled(0 <= index < (siblings.childCount() - 1 if siblings else 0))

    def _siblings(self, item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        if item is None or item is self.tree.top():
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
        target = self.tree.top()
        for candidate in _all_items(target):
            if new_id is not None and candidate.data(0, ROLE_ID) == new_id:
                target = candidate
        target.addChild(item)
        target.setExpanded(True)
        _expand(item, expanded)
        self.tree.setCurrentItem(item)
        self._update()

    def _sort(self) -> None:
        root = self.tree.top()
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
