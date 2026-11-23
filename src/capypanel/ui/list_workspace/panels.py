import html
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QPainter,
    QPalette,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.core.i18n import _
from capypanel.ui import keyboard, spacing
from capypanel.ui.groups import (
    HOSTS_MIME,
    ROLE_ID,
    ROLE_KIND,
    GroupsHeading,
    GroupTree,
    HostDropTree,
    hosts_mime,
)
from capypanel.ui.icons import tabler_icon
from capypanel.ui.menus import MenuCombo, label, popup
from capypanel.ui.notes import divider


@dataclass(frozen=True)
class Filter:
    kind: str
    value: str | None = None


def pane_title(text: str, label: QLabel | None = None) -> QLabel:
    label = label if label is not None else QLabel()
    label.setText(text)
    label.setObjectName("paneTitle")
    label.setContentsMargins(4, 4, 4, 2)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class NavigationPane(QWidget):
    filter_changed = Signal()

    def add_list_picker(self, fill: Callable[[], None]) -> MenuCombo:
        picker = MenuCombo()
        picker.setObjectName("listPicker")
        picker.menu().setToolTipsVisible(True)
        picker.menu().aboutToShow.connect(fill)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.insertWidget(0, picker)
        self._picker = picker
        return picker

    def __init__(self, everything: Callable[[], str], icon: str = "device-desktop") -> None:
        super().__init__()
        self._filter = Filter("all")
        self._picker: MenuCombo | None = None
        self._everything_text = everything
        self._icon = icon
        self.add_group_button = QToolButton()
        self.add_group_button.setText("+")
        self.groups_heading = GroupsHeading()
        pane_title("", self.groups_heading)
        self.groups_heading.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tags_title = pane_title("")
        self.clear_tags_button = QToolButton()
        self.clear_tags_button.setText("×")
        self.clear_tags_button.clicked.connect(self.clear_tags)
        self._picked_tags: list[str] = []
        header = QHBoxLayout()
        header.addWidget(self.groups_heading, 1)
        header.addWidget(self.add_group_button)

        self.everything = PinnedList()
        self._everything_item = QTreeWidgetItem([""])
        self._everything_item.setData(0, ROLE_KIND, "all")
        self.everything.addTopLevelItem(self._everything_item)
        self._no_group_item = QTreeWidgetItem([""])
        self._no_group_item.setData(0, ROLE_KIND, "nogroup")
        self.everything.addTopLevelItem(self._no_group_item)
        self._paint_icons()
        self.groups = GroupTree()
        self.groups.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # A tree like the groups (not QListWidget), so both lists have the same row height.
        self.tags = QTreeWidget()
        self.tags.setHeaderHidden(True)
        self.tags.setRootIsDecorated(False)
        self.tags.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        tags_header = QHBoxLayout()
        tags_header.addWidget(self._tags_title, 1)
        tags_header.addWidget(self.clear_tags_button)

        for tree in (self.everything, self.groups, self.tags):
            tree.setObjectName("flat")
        self._tags_line = divider()
        card = self._card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        top, bottom = QWidget(), QWidget()
        above = QVBoxLayout(top)
        above.setContentsMargins(0, 0, 0, 0)
        above.setSpacing(2)
        above.addWidget(self.everything)
        above.addWidget(divider())
        above.addLayout(header)
        above.addWidget(self.groups, 1)
        below = QVBoxLayout(bottom)
        below.setContentsMargins(0, 0, 0, 0)
        below.setSpacing(2)
        below.addWidget(self._tags_line)
        below.addLayout(tags_header)
        below.addWidget(self.tags, 1)
        self._tags_part = bottom
        self.split = QSplitter(Qt.Orientation.Vertical)
        self.split.setObjectName("navSplit")
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(5)
        self.split.addWidget(top)
        self.split.addWidget(bottom)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([300, 130])
        inside = QVBoxLayout(card)
        inside.setContentsMargins(4, 4, 4, 4)
        inside.addWidget(self.split)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)

        self.everything.itemSelectionChanged.connect(self._everything_picked)
        self.groups.itemSelectionChanged.connect(self._groups_picked)
        self.tags.itemSelectionChanged.connect(self._tags_picked)
        self.retranslate()

    def natural_width(self) -> int:
        lists = [_tree_width(t) for t in (self.everything, self.groups, self.tags) if t.isVisible()]
        heading = self.groups_heading.sizeHint().width() + self.add_group_button.sizeHint().width()
        card = max([heading, *lists]) + 8 + 2 * self._card.frameWidth()  # 4 px margins
        layout = self.layout()
        above = [
            w.sizeHint().width()
            for i in range(layout.count() if layout else 0)
            if (w := layout.itemAt(i).widget()) is not None and w is not self._card  # type: ignore[union-attr]
        ]
        return max([card, *above])

    def card_top(self) -> int:
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        top = 0
        for index in range(layout.indexOf(self._card)):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None and not widget.isHidden():
                top += widget.sizeHint().height() + layout.spacing()
        return top

    def retranslate(self) -> None:
        self.add_group_button.setToolTip(_("Add group"))
        self.groups_heading.setText(_("Groups"))
        self.groups_heading.setToolTip(_("Drop a group here to put it directly under Groups"))
        self.clear_tags_button.setToolTip(_("Clear the picked tags"))
        self._show_tag_count()

    def set_tags_visible(self, visible: bool) -> None:
        for widget in (self._tags_line, self._tags_title, self.clear_tags_button, self.tags):
            widget.setVisible(visible)
        self._tags_part.setVisible(visible)
        if not visible and self._picked_tags:
            self.clear_tags()

    def current_filter(self) -> Filter:
        return self._filter

    def picked_tags(self) -> list[str]:
        return list(self._picked_tags)

    def clear_tags(self) -> None:
        self.tags.clearSelection()

    def set_searching(self, searching: bool) -> None:
        for tree in (self.everything, self.groups):
            tree.blockSignals(True)
        if searching:
            self._clear(self.everything, self.groups)
        else:
            self._filter = self._select(self._filter)
        for tree in (self.everything, self.groups):
            tree.blockSignals(False)

    def selected_group_id(self) -> str | None:
        return self._filter.value if self._filter.kind == "group" else None

    def group_at(self, position: QPoint) -> str | None:
        item = self.groups.itemAt(position)
        return item.data(0, ROLE_ID) if item else None

    def show_view(self, kind: str, value: str) -> None:
        if kind == "tag":
            self._pick_tags([value])
            kind = "all"
        self._filter = self._select(Filter(kind, value or None))

    def select_group(self, group_id: str) -> None:
        wanted = Filter("nogroup") if group_id == NO_GROUP else Filter("group", group_id)
        self._filter = self._select(wanted)

    def show_list(self, host_list: HostList | None) -> None:
        wanted = self._filter
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(True)
        self.tags.clear()
        self.everything.setVisible(host_list is not None)
        if host_list is None:
            self.groups.clear()
        else:
            self._everything_item.setText(0, f"{self._everything_text()} ({len(host_list.hosts)})")
            loose = sum(1 for h in host_list.hosts if h.group == NO_GROUP)
            self._no_group_item.setText(0, f"{_('No group')} ({loose})")
            self.groups.fill(host_list)
            for tag, count in sorted(host_list.all_tags().items(), key=lambda t: t[0].casefold()):
                item = QTreeWidgetItem([f"{tag} ({count})"])
                item.setData(0, ROLE_KIND, "tag")
                item.setData(0, ROLE_ID, tag)
                self.tags.addTopLevelItem(item)
                item.setSelected(tag in self._picked_tags)
        self._filter = self._select(wanted) if host_list is not None else Filter("all")
        self._read_picked_tags()
        for tree in (self.everything, self.groups, self.tags):
            tree.blockSignals(False)
        self._fit_everything()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_everything()
        # Qt puts the pane's widgets back in the order they were made when it moves into its
        # window, which put the list picker last.
        parts = (self._picker, self.everything, self.add_group_button, self.groups,
                 self.clear_tags_button, self.tags)  # fmt: skip
        keyboard.chain([w for w in parts if w is not None])

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self._fit_everything()
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icons()

    def _paint_icons(self) -> None:
        color = self.palette().color(QPalette.ColorRole.Text)
        self._everything_item.setIcon(0, tabler_icon(self._icon, color, 16))
        self._no_group_item.setIcon(0, tabler_icon("folder", color, 16))

    def split_state(self) -> str:
        return self.split.saveState().toBase64().toStdString()

    def restore_split(self, saved: object) -> None:
        if isinstance(saved, str):
            self.split.restoreState(QByteArray.fromBase64(saved.encode()))
            self.split.setChildrenCollapsible(False)

    def _fit_everything(self) -> None:
        self.everything.doItemsLayout()
        row = self.everything.visualItemRect(self._everything_item).height()
        frame = self.everything.height() - self.everything.viewport().height()
        height = max(row, self.everything.sizeHintForRow(0)) * 2
        self.everything.setFixedHeight(height + frame)
        sides = self.everything.width() - self.everything.viewport().width()
        self.everything.setMinimumWidth(self.everything.sizeHintForColumn(0) + sides + 12)

    def _select(self, wanted: Filter) -> Filter:
        if wanted.kind == "group":
            for item in _walk(self.groups.invisibleRootItem()):
                if item.data(0, ROLE_ID) == wanted.value:
                    self.groups.setCurrentItem(item)
                    return wanted
        if wanted.kind == "nogroup":
            self.everything.setCurrentItem(self._no_group_item)
            self._no_group_item.setSelected(True)
            self._clear(self.groups)
            return wanted
        self.everything.setCurrentItem(self._everything_item)
        self._everything_item.setSelected(True)
        self._clear(self.groups)
        return Filter("all")

    def _clear(self, *trees: QTreeWidget) -> None:
        for tree in trees:
            tree.blockSignals(True)
            tree.clearSelection()
            tree.blockSignals(False)

    def _everything_picked(self) -> None:
        items = self.everything.selectedItems()
        if not items:
            return
        self._clear(self.groups)
        self._filter = Filter(items[0].data(0, ROLE_KIND))
        self.filter_changed.emit()

    def _groups_picked(self) -> None:
        items = self.groups.selectedItems()
        if not items:
            return
        self._clear(self.everything)
        self._filter = Filter("group", items[0].data(0, ROLE_ID))
        self.filter_changed.emit()

    def _tags_picked(self) -> None:
        self._read_picked_tags()
        self.filter_changed.emit()

    def _pick_tags(self, tags: Sequence[str]) -> None:
        self.tags.blockSignals(True)
        for item in _walk(self.tags.invisibleRootItem()):
            item.setSelected(item.data(0, ROLE_ID) in tags)
        self.tags.blockSignals(False)
        self._read_picked_tags()

    def _read_picked_tags(self) -> None:
        items = (self.tags.topLevelItem(i) for i in range(self.tags.topLevelItemCount()))
        self._picked_tags = [i.data(0, ROLE_ID) for i in items if i is not None and i.isSelected()]
        self._show_tag_count()

    def _show_tag_count(self) -> None:
        picked = len(self._picked_tags)
        self._tags_title.setText(_("Tags ({n})").format(n=picked) if picked else _("Tags"))
        self.clear_tags_button.setEnabled(bool(picked))


class PinnedList(HostDropTree):
    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def drop_group(self, item: QTreeWidgetItem) -> str | None:
        return NO_GROUP if item.data(0, ROLE_KIND) == "nogroup" else None


def _walk(root: QTreeWidgetItem) -> Iterable[QTreeWidgetItem]:
    for index in range(root.childCount()):
        child = root.child(index)
        if child is not None:
            yield child
            yield from _walk(child)


class SearchBox(QLineEdit):
    """Enter only moves to the results, never acts on them: a typo can't reach a wrong PC."""

    to_results = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("paneSearch")
        self.setClearButtonEnabled(True)
        self._icon = self.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self._paint_icon()

    def set_fields(self, fields: Sequence[str], tip: str) -> None:
        self.setPlaceholderText(_("Search {fields}").format(fields=", ".join(fields)))
        self.setToolTip(tip)

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
        if event.type() == QEvent.Type.PaletteChange:
            self._paint_icon()

    def _paint_icon(self) -> None:
        self._icon.setIcon(
            tabler_icon("search", self.palette().color(QPalette.ColorRole.PlaceholderText))
        )


class TagStrip(QFrame):
    clear_clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("tagStrip")
        self._text = QLabel()
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setWordWrap(True)
        self.clear_button = QPushButton()
        self.clear_button.setAutoDefault(False)
        self.clear_button.clicked.connect(self.clear_clicked)
        row = QHBoxLayout(self)
        row.setContentsMargins(spacing.CONTROLS, spacing.ICON, spacing.ICON, spacing.ICON)
        row.addWidget(self._text, 1)
        row.addWidget(self.clear_button)
        self.hide()

    def show_tags(self, tags: Sequence[str], text: str) -> None:
        self.setVisible(bool(tags))
        if tags:
            names = html.escape(", ".join(tags))
            self._text.setText(text.replace("{tags}", f"<b>{names}</b>"))
            self._text.setToolTip(", ".join(tags))
            self.clear_button.setText(_("Clear"))
            self.clear_button.setToolTip(_("Clear the picked tags"))


ROLE_NOTHING = Qt.ItemDataRole.UserRole + 9
NOTHING: tuple[tuple[int, int | str], ...] = ((2, ""),)


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    if not text:
        return NOTHING
    parts = re.split(r"(\d+)", text.casefold())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p)


def sorted_by[T](
    rows: Sequence[T], name: Callable[[T], str], cell: Callable[[T], str], descending: bool
) -> list[T]:
    by_name = sorted(rows, key=lambda r: natural_key(name(r)))
    filled = [r for r in by_name if cell(r)]
    filled.sort(key=lambda r: natural_key(cell(r)), reverse=descending)
    return filled + [r for r in by_name if not cell(r)]


SAMPLE_ID = "guide-sample"  # a guide's sample item: never saved, never read from the network


def sample_tag() -> str:
    return _("2nd floor")


def is_sample(item_id: object) -> bool:
    return isinstance(item_id, str) and item_id.startswith(SAMPLE_ID)


class SortedRow(QTreeWidgetItem):
    def sort_text(self, column: int) -> str:
        return "" if self.data(column, ROLE_NOTHING) else self.text(column)

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        theirs_text = (
            other.sort_text(column) if isinstance(other, SortedRow) else other.text(column)
        )
        mine, theirs = natural_key(self.sort_text(column)), natural_key(theirs_text)
        # Z–A sorts by asking the other row: what must stay in place answers the other way.
        descending = tree is not None and tree.header().sortIndicatorOrder() == (
            Qt.SortOrder.DescendingOrder
        )
        sample, other_sample = is_sample(self.data(0, ROLE_ID)), is_sample(other.data(0, ROLE_ID))
        if sample != other_sample:
            return sample != descending
        if mine != theirs:
            if NOTHING in (mine, theirs):
                return (theirs == NOTHING) != descending
            return mine < theirs
        names = natural_key(self.text(0)), natural_key(other.text(0))
        return names[0] > names[1] if descending else names[0] < names[1]


def _tree_width(tree: QTreeWidget) -> int:
    bar = tree.verticalScrollBar()
    extra = bar.sizeHint().width() if bar.isVisible() else 0
    return tree.sizeHintForColumn(0) + 2 * tree.frameWidth() + extra


def offers_typed(typed: str, rows: Iterable[Host]) -> bool:
    wanted = typed.strip().casefold()
    if not wanted or any(c.isspace() for c in wanted):
        return False
    return not any(wanted in (row.name.casefold(), row.address.casefold()) for row in rows)


class RowsOffer(QObject):
    GAP = 6

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self._tree = tree
        self.box = QWidget(tree.viewport())
        self._row = QHBoxLayout(self.box)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)
        self.buttons: list[QPushButton] = []
        self.box.hide()
        tree.installEventFilter(self)
        tree.viewport().installEventFilter(self)
        tree.verticalScrollBar().valueChanged.connect(self.place)
        tree.horizontalScrollBar().valueChanged.connect(self.place)

    def show_actions(self, actions: Sequence[QAction]) -> None:
        for button in self.buttons:
            self._row.removeWidget(button)
            button.hide()  # gone now: deleteLater alone leaves it drawn until Qt gets to it
            button.deleteLater()
        self.buttons = []
        for action in actions:
            button = QPushButton(label(action).replace("&", ""))
            button.setAutoDefault(False)
            button.setEnabled(action.isEnabled())
            button.clicked.connect(action.trigger)
            self._row.addWidget(button)
            button.show()  # added to a box already on screen, it would stay hidden
            self.buttons.append(button)
        self.place()

    def place(self) -> None:
        tree = self._tree
        count = tree.topLevelItemCount()
        last = tree.topLevelItem(count - 1) if count and self.buttons else None
        if last is None:
            self.box.hide()
            return
        layout = self.box.layout()
        assert layout is not None
        layout.activate()
        size = self.box.sizeHint()
        top = tree.visualItemRect(last).bottom() + 1 + self.GAP
        self.box.setGeometry(self._text_left(last), top, size.width(), size.height())
        self.box.setVisible(top + size.height() <= tree.viewport().height())

    def _text_left(self, item: QTreeWidgetItem) -> int:
        tree = self._tree
        index = tree.indexFromItem(item, 0)
        option = QStyleOptionViewItem()
        tree.initViewItemOption(option)
        option.rect = tree.visualRect(index)
        delegate = tree.itemDelegateForIndex(index)
        if isinstance(delegate, QStyledItemDelegate):
            delegate.initStyleOption(option, index)
        style = tree.style()
        cell = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, tree)
        # Qt draws a cell's text this far inside it (QCommonStyle's item text margin).
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, tree) + 1
        return cell.left() + margin

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.StyleChange, QEvent.Type.FontChange):
            self.place()
        return False


def fill_sort_menu(menu: QMenu, tree: QTreeView) -> None:
    for old in menu.findChildren(QActionGroup):
        old.deleteLater()
    header, model = tree.header(), tree.model()
    section, order = header.sortIndicatorSection(), header.sortIndicatorOrder()
    columns, ways = QActionGroup(menu), QActionGroup(menu)
    for index in range(header.count()):
        title = model.headerData(index, Qt.Orientation.Horizontal)
        if tree.isColumnHidden(index) or not isinstance(title, str) or not title:
            continue
        item = menu.addAction(title)
        item.setCheckable(True)
        item.setChecked(index == section)
        columns.addAction(item)
        item.triggered.connect(lambda _c=False, i=index: tree.sortByColumn(i, order))
    menu.addSeparator()
    for text, way in ((_("&Ascending"), Qt.SortOrder.AscendingOrder),
                      (_("&Descending"), Qt.SortOrder.DescendingOrder)):  # fmt: skip
        item = menu.addAction(text)
        item.setCheckable(True)
        item.setChecked(way == order)
        ways.addAction(item)
        item.triggered.connect(lambda _c=False, w=way: tree.sortByColumn(section, w))


class ItemTable(QTreeWidget):
    COLUMNS: tuple[str, ...] = ()
    SEARCHED: frozenset[int] = frozenset({0})
    EMPTY: dict[int, int] = {}
    ICONS: frozenset[int] = frozenset()
    columns_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("grid")
        self._rows: dict[str, SortedRow] = {}
        self._widths: dict[str, int] = {}
        self._sizing = False
        self._marker = MatchMarker(self, columns=set(self.SEARCHED))
        self.setItemDelegate(self._marker)
        self.retranslate()
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionsMovable(False)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)
        header.sectionResized.connect(self._resized)
        header.sectionHandleDoubleClicked.connect(self._keep_width)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._empty = QWidget(self.viewport())
        self._empty_text = QLabel()
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        self.clear_tags_button = QPushButton()
        self.clear_tags_button.setAutoDefault(False)
        self.note_buttons: list[QPushButton] = []
        self._note_row = QHBoxLayout()
        self._note_row.setSpacing(8)
        self._note_row.addStretch(1)
        self._note_row.addWidget(self.clear_tags_button)
        self._note_row.addStretch(1)
        note = QVBoxLayout(self._empty)
        note.setSpacing(12)
        note.addWidget(self._empty_text)
        note.addLayout(self._note_row)
        self._empty.hide()
        self.offer = RowsOffer(self)

    def retranslate(self) -> None:
        pass

    def row_texts(self, item: Host) -> list[str]:
        raise NotImplementedError

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        pass

    def longest_texts(self, column: int) -> Sequence[str]:
        return ()

    def set_editable(self, editable: bool) -> None:
        self.setDragEnabled(editable)

    def mimeTypes(self) -> list[str]:
        return [HOSTS_MIME]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        return hosts_mime([item.data(0, ROLE_ID) for item in items])

    def set_search(self, needle: str) -> None:
        self._marker.needle = needle
        self.viewport().update()

    def show_items(self, items: Sequence[Host]) -> None:
        keep = set(self.selected_ids())
        current = self.currentItem()
        current_id = current.data(0, ROLE_ID) if current is not None else None
        # A refill after an edit keeps the rows where they were: clear() would jump to the top.
        before, after = set(self._rows), {item.id for item in items}
        same = bool(before) and len(before ^ after) <= max(1, len(keep))
        down = self.verticalScrollBar().value() if same else 0
        across = self.horizontalScrollBar().value()
        self.blockSignals(True)
        self.setSortingEnabled(False)
        self.clear()
        self._rows = {}
        for item in items:
            row = SortedRow(self.row_texts(item))
            row.setData(0, ROLE_ID, item.id)
            self.addTopLevelItem(row)
            self._rows[item.id] = row
            self.decorate(row, item)
            row.setSelected(item.id in keep)
        self.setSortingEnabled(True)
        if current_id in self._rows:
            self.selectionModel().setCurrentIndex(
                self.indexFromItem(self._rows[current_id]),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self.blockSignals(False)
        self._place_columns()
        self.updateGeometries()
        self.verticalScrollBar().setValue(down)
        self.horizontalScrollBar().setValue(across)
        self.offer.place()
        self.itemSelectionChanged.emit()

    def in_shown_order(self, items: Sequence[Host]) -> tuple[Host, ...]:
        column = max(self.sortColumn(), 0)
        descending = self.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
        texts = {item.id: self.row_texts(item) for item in items}

        def cell(item: Host) -> str:
            row = self._rows.get(item.id)
            return row.sort_text(column) if row is not None else texts[item.id][column]

        return tuple(sorted_by(items, lambda h: texts[h.id][0], cell, descending))

    def show_no_match(self, text: str) -> None:
        self.show_note(text, clear_tags=bool(text))

    def show_note(
        self, text: str, actions: Sequence[QAction] = (), *, clear_tags: bool = False
    ) -> None:
        self._empty_text.setText(text)
        self.clear_tags_button.setText(_("Clear tags"))
        self.clear_tags_button.setVisible(clear_tags)
        for button in self.note_buttons:
            self._note_row.removeWidget(button)
            button.hide()  # gone now: deleteLater alone leaves it drawn until Qt gets to it
            button.deleteLater()
        self.note_buttons = []
        for action in actions if text else ():
            button = QPushButton(label(action).replace("&", ""))
            button.setAutoDefault(False)
            button.setEnabled(action.isEnabled())
            button.clicked.connect(action.trigger)
            self._note_row.insertWidget(self._note_row.count() - 1, button)
            button.show()  # added to a note already on screen, it would stay hidden
            self.note_buttons.append(button)
        self._empty.setVisible(bool(text))
        self._place_empty()

    def show_offer(self, actions: Sequence[QAction]) -> None:
        self.offer.show_actions(actions if self.topLevelItemCount() else ())

    def _place_empty(self) -> None:
        if not self._empty.isVisible():
            return
        area = self.viewport().rect()
        metrics = self._empty_text.fontMetrics()
        line = max(metrics.horizontalAdvance(t) for t in self._empty_text.text().split("\n"))
        layout = self._empty.layout()
        assert layout is not None
        layout.activate()
        margins = layout.contentsMargins()
        sides = margins.left() + margins.right()
        buttons = self._note_row.sizeHint().width()
        width = min(max(line + 4, buttons) + sides, area.width())
        size = QSize(width, layout.totalHeightForWidth(width)).boundedTo(area.size())
        self._empty.setGeometry(
            area.x() + (area.width() - size.width()) // 2,
            area.y() + (area.height() - size.height()) // 2,
            size.width(),
            size.height(),
        )

    def hidden_columns(self) -> list[str]:
        return [key for i, key in enumerate(self.COLUMNS) if self.isColumnHidden(i)]

    def set_hidden_columns(self, keys: object) -> None:
        hidden = set(keys) if isinstance(keys, list) else set()
        for index, key in enumerate(self.COLUMNS):
            self.setColumnHidden(index, index > 0 and key in hidden)
        self._place_columns()

    def _columns_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        self.fill_columns_menu(menu)
        popup(menu, self.header().viewport().mapToGlobal(position))

    def fill_columns_menu(self, menu: QMenu) -> None:
        header = self.headerItem()
        for index in range(1, len(self.COLUMNS)):
            item = menu.addAction(header.text(index))
            item.setCheckable(True)
            item.setChecked(not self.isColumnHidden(index))
            item.toggled.connect(lambda shown, i=index: self._show_column(i, shown))
        menu.addSeparator()
        menu.addAction(_("&Fit columns to content"), self.fit_columns)

    def fill_sort_menu(self, menu: QMenu) -> None:
        fill_sort_menu(menu, self)

    def _show_column(self, index: int, shown: bool) -> None:
        self.setColumnHidden(index, not shown)
        self._place_columns()
        self.columns_changed.emit()

    def minimum_width(self, index: int) -> int:
        """Qt keeps room for the sort arrow in every title; only the sorted column needs it."""
        header = self.header()
        if index == header.sortIndicatorSection():
            width = header.sectionSizeHint(index)
        else:
            header.setSortIndicatorShown(False)
            width = header.sectionSizeHint(index)
            header.setSortIndicatorShown(True)
        # Windows' header draws a little wider than Qt measures: 6 px keep the last letter.
        return width + 6

    def widths(self) -> dict[str, int]:
        return dict(self._widths)

    def set_widths(self, saved: object) -> None:
        known = set(self.COLUMNS)
        self._widths = {
            k: v for k, v in (saved.items() if isinstance(saved, dict) else ())
            if k in known and isinstance(v, int) and v > 0
        }  # fmt: skip
        self._place_columns()

    def fit_columns(self) -> None:
        for column in self._shown():
            self._widths[self.COLUMNS[column]] = self._content_width(column)
        self._place_columns()

    def _place_columns(self) -> None:
        header = self.header()
        self._sizing = True
        for column in self._shown():
            key = self.COLUMNS[column]
            known = column in self.EMPTY or bool(self.longest_texts(column))
            if key not in self._widths and (self.topLevelItemCount() or known):
                self._widths[key] = self._first_width(column)
            header.resizeSection(column, self._widths.get(key, self.minimum_width(column)))
        self._sizing = False
        self._fill_last_column()

    def _first_width(self, column: int) -> int:
        width = self._content_width(column)
        if column in self.EMPTY:
            width = max(width, self.fontMetrics().averageCharWidth() * self.EMPTY[column] + 16)
        return max([width, *(self._cell_width(column, t) for t in self.longest_texts(column))])

    def _cell_width(self, column: int, text: str) -> int:
        self.ensurePolished()
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.text = text
        option.features |= QStyleOptionViewItem.ViewItemFeature.HasDisplay
        if column in self.ICONS:
            option.features |= QStyleOptionViewItem.ViewItemFeature.HasDecoration
            option.icon = QIcon(QPixmap(option.decorationSize))
        contents = QStyle.ContentsType.CT_ItemViewItem
        return self.style().sizeFromContents(contents, option, QSize(), self).width()

    def _content_width(self, column: int) -> int:
        return max(self.sizeHintForColumn(column), self.minimum_width(column))

    def _shown(self) -> list[int]:
        header = self.header()
        return [
            header.logicalIndex(v) for v in range(header.count())
            if not header.isSectionHidden(header.logicalIndex(v))
        ]  # fmt: skip

    def _fill_last_column(self) -> None:
        shown = self._shown()
        if not shown:
            return
        last, header = shown[-1], self.header()
        others = sum(header.sectionSize(c) for c in shown[:-1])
        own = self._widths.get(self.COLUMNS[last], self.minimum_width(last))
        self._sizing = True
        header.resizeSection(last, max(own, self.viewport().width() - others))
        self._sizing = False

    def _resized(self, index: int, _old: int, new: int) -> None:
        dragging = QApplication.mouseButtons() & Qt.MouseButton.LeftButton
        if self._sizing or not dragging or self.isColumnHidden(index):
            return
        wanted = max(new, self.minimum_width(index))
        self._widths[self.COLUMNS[index]] = wanted
        if wanted != new:
            self._sizing = True
            self.header().resizeSection(index, wanted)
            self._sizing = False
        self._fill_last_column()

    def natural_width(self) -> int:
        shown, header = self._shown(), self.header()
        width = sum(header.sectionSize(c) for c in shown[:-1])
        if shown:
            width += self._widths.get(self.COLUMNS[shown[-1]], self.minimum_width(shown[-1]))
        bar = self.verticalScrollBar()
        return width + 2 * self.frameWidth() + (bar.sizeHint().width() if bar.isVisible() else 0)

    def _keep_width(self, index: int) -> None:
        if not self.isColumnHidden(index):
            self._widths[self.COLUMNS[index]] = self.header().sectionSize(index)
            self._fill_last_column()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fill_last_column()
        self._place_empty()

    def scrollTo(
        self,
        index: QModelIndex | QPersistentModelIndex,
        hint: QAbstractItemView.ScrollHint = QAbstractItemView.ScrollHint.EnsureVisible,
    ) -> None:
        """Up or down only: Qt also scrolls sideways to a clicked cell, jumping the table right."""
        across = self.horizontalScrollBar().value()
        super().scrollTo(index, hint)
        self.horizontalScrollBar().setValue(across)

    def selected_ids(self) -> list[str]:
        return [item.data(0, ROLE_ID) for item in self.selectedItems()]

    def select_ids(self, ids: Iterable[str]) -> None:
        wanted = set(ids)
        self.clearSelection()
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None and item.data(0, ROLE_ID) in wanted:
                item.setSelected(True)
                self.scrollToItem(item)


class MatchMarker(QStyledItemDelegate):
    COLOR = QColor(255, 196, 0, 96)

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
