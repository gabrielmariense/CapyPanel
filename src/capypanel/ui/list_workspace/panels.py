"""The panels of a list tool: groups and tags, the search above the items, and the items table."""

import html
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QPainter,
    QPalette,
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
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.core.i18n import _
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
from capypanel.ui.menus import popup


@dataclass(frozen=True)
class Filter:
    kind: str  # "all", "nogroup" or "group": where to look (picked tags then narrow it)
    value: str | None = None


def pane_title(text: str, label: QLabel | None = None) -> QLabel:
    """A pane's small bold heading: a new label, or `label` styled as one."""
    label = label if label is not None else QLabel()
    label.setText(text)
    label.setObjectName("paneTitle")
    label.setContentsMargins(4, 4, 4, 2)
    font = label.font()
    font.setBold(True)
    label.setFont(font)
    return label


class NavigationPane(QWidget):
    """One card, like the other panels: "All hosts" (or the tool's own word) pinned on top, then
    the groups (in the list's own order, rearranged by dragging) and the tags, each under a small
    heading and split by thin lines. A group (or All hosts, or No group) picks where to look;
    tags, any number of them, then keep only the items that have them all."""

    filter_changed = Signal()

    def __init__(self, everything: Callable[[], str]) -> None:
        super().__init__()
        self._filter = Filter("all")
        self._everything_text = everything  # "All hosts", in the current language
        self.add_group_button = QToolButton()
        self.add_group_button.setText("+")
        self.groups_heading = GroupsHeading()  # drop a group here: it goes to the top level
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

        # Its own small list above the tree: it never scrolls away under a long tree. "No group"
        # is always there, so hosts can be dragged onto it even before any host is in it.
        self.everything = PinnedList()
        self._everything_item = QTreeWidgetItem([""])
        self._everything_item.setData(0, ROLE_KIND, "all")
        self._everything_item.setIcon(
            0, self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.everything.addTopLevelItem(self._everything_item)
        self._no_group_item = QTreeWidgetItem([""])
        self._no_group_item.setData(0, ROLE_KIND, "nogroup")
        self._no_group_item.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        self.everything.addTopLevelItem(self._no_group_item)
        self.groups = GroupTree()
        self.groups.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # A tree like the groups (not QListWidget), so both lists have the same row height.
        self.tags = QTreeWidget()
        self.tags.setHeaderHidden(True)
        self.tags.setRootIsDecorated(False)
        # A click picks a tag or drops it again, without Ctrl.
        self.tags.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        tags_header = QHBoxLayout()
        tags_header.addWidget(self._tags_title, 1)
        tags_header.addWidget(self.clear_tags_button)

        # The lists drop their own frames ("flat"): the card around them is the only box.
        for tree in (self.everything, self.groups, self.tags):
            tree.setObjectName("flat")
        self._tags_line = _divider()
        card = self._card = QFrame()
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
        inside.addLayout(tags_header)
        inside.addWidget(self.tags, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(card)

        self.everything.itemSelectionChanged.connect(self._everything_picked)
        self.groups.itemSelectionChanged.connect(self._groups_picked)
        self.tags.itemSelectionChanged.connect(self._tags_picked)
        self.retranslate()

    def natural_width(self) -> int:
        """As wide as its widest group or tag in full, and anything above the card (the list
        dropdown), with the card's margins."""
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

    def retranslate(self) -> None:
        """Titles only; the lists' own texts come back with the next show_list()."""
        self.add_group_button.setToolTip(_("Add group"))
        self.groups_heading.setText(_("Groups"))
        self.groups_heading.setToolTip(_("Drop a group here to put it directly under Groups"))
        self.clear_tags_button.setToolTip(_("Clear the picked tags"))
        self._show_tag_count()

    def set_tags_visible(self, visible: bool) -> None:
        """View > Tags pane. Hiding it drops the picked tags: nothing filters out of sight."""
        for widget in (self._tags_line, self._tags_title, self.clear_tags_button, self.tags):
            widget.setVisible(visible)
        if not visible and self._picked_tags:
            self.clear_tags()

    def current_filter(self) -> Filter:
        return self._filter

    def picked_tags(self) -> list[str]:
        return list(self._picked_tags)

    def clear_tags(self) -> None:
        self.tags.clearSelection()  # _tags_picked() follows

    def set_searching(self, searching: bool) -> None:
        """A search looks through every item, so no group shows as picked meanwhile. The picked
        tags stay: they narrow the search too."""
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
        """The group under a point of the groups tree; None on empty space."""
        item = self.groups.itemAt(position)
        return item.data(0, ROLE_ID) if item else None

    def show_view(self, kind: str, value: str) -> None:
        """A view as saved ("group", "nogroup" or "all"); All hosts when it's gone. A "tag" view
        (saved by 0.19) shows everything with that tag picked."""
        if kind == "tag":
            self._pick_tags([value])
            kind = "all"
        self._filter = self._select(Filter(kind, value or None))

    def select_group(self, group_id: str) -> None:
        """A group, or NO_GROUP for the hosts in none."""
        wanted = Filter("nogroup") if group_id == NO_GROUP else Filter("group", group_id)
        self._filter = self._select(wanted)

    def show_list(self, host_list: HostList | None) -> None:
        """Rebuilds the lists from the host list, keeping the current pick when it still exists."""
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
                item.setSelected(tag in self._picked_tags)  # still picked, while it exists
        self._filter = self._select(wanted) if host_list is not None else Filter("all")
        self._read_picked_tags()
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
        """Exactly as tall as its two rows, whatever padding the theme gives rows and frames, and
        never narrower than "All hosts (N)": the pane can't be dragged past it. Group names don't
        count, so a long one can't make the pane huge (they show a tooltip)."""
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
        self._filter = Filter(items[0].data(0, ROLE_KIND))  # "all" or "nogroup"
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
        self.clear_tags_button.setEnabled(bool(picked))  # kept in place, greyed out


class PinnedList(HostDropTree):
    """ "All hosts" and "No group". Hosts dragged from the table onto "No group" leave their
    group (`hosts_dropped` with NO_GROUP)."""

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
    """Above the items table: its placeholder says what's searched. Esc clears it; Down or Enter
    moves to the results (never acts on them, so a typo can't reach a wrong PC)."""

    to_results = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("paneSearch")  # the panels' corners and border, so its edges match
        self.setClearButtonEnabled(True)
        self._icon = self.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        self._paint_icon()

    def set_fields(self, fields: Sequence[str], tip: str) -> None:
        """The placeholder names exactly what's searched: each a lower-case word."""
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
        if event.type() == QEvent.Type.PaletteChange:  # the new theme's colour
            self._paint_icon()

    def _paint_icon(self) -> None:
        self._icon.setIcon(
            tabler_icon("search", self.palette().color(QPalette.ColorRole.PlaceholderText))
        )


class TagStrip(QFrame):
    """Between the search box and the table while tags are picked: which ones, how many items
    they leave, and Clear. It's there so nobody wonders where the other items went."""

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
        row.setContentsMargins(10, 4, 4, 4)
        row.addWidget(self._text, 1)
        row.addWidget(self.clear_button)
        self.hide()

    def show_tags(self, tags: Sequence[str], text: str) -> None:
        """text: the tool's sentence, with {tags} where the picked tags go (in bold)."""
        self.setVisible(bool(tags))
        if tags:
            names = html.escape(", ".join(tags))
            self._text.setText(text.replace("{tags}", f"<b>{names}</b>"))
            self._text.setToolTip(", ".join(tags))
            self.clear_button.setText(_("Clear"))
            self.clear_button.setToolTip(_("Clear the picked tags"))


def natural_key(text: str) -> tuple[tuple[int, int | str], ...]:
    """Sorts "Room 2" before "Room 10", and ignores case. Empty cells go last."""
    if not text:
        return ((2, ""),)
    parts = re.split(r"(\d+)", text.casefold())
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p)


class SortedRow(QTreeWidgetItem):
    """A table row that sorts naturally (A–Z or Z–A by the clicked column), ties by its name,
    A–Z either way."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        mine, theirs = natural_key(self.text(column)), natural_key(other.text(column))
        if mine != theirs:
            return mine < theirs
        names = natural_key(self.text(0)), natural_key(other.text(0))
        # Z–A sorts by asking the other row: so a tie stays A–Z, the names answer the other way.
        descending = tree is not None and tree.header().sortIndicatorOrder() == (
            Qt.SortOrder.DescendingOrder
        )
        return names[0] > names[1] if descending else names[0] < names[1]


def _tree_width(tree: QTreeWidget) -> int:
    """A list's widest row in full, with its frame and, when shown, its scroll bar."""
    bar = tree.verticalScrollBar()
    extra = bar.sizeHint().width() if bar.isVisible() else 0
    return tree.sizeHintForColumn(0) + 2 * tree.frameWidth() + extra


class ItemTable(QTreeWidget):
    """A list tool's items as a table. A QTreeView-based widget: it selects whole rows in
    Windows 11. A tool says its columns (COLUMNS, saved by those keys; the first always shows),
    their titles (retranslate) and each row's texts (row_texts)."""

    COLUMNS: tuple[str, ...] = ()
    SEARCHED: frozenset[int] = frozenset({0})  # columns where a search's text is marked
    # Empty until something fills them later: a starting width, in average characters.
    EMPTY: dict[int, int] = {}
    columns_changed = Signal()  # a column was shown or hidden

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("grid")  # lines between rows and columns
        self._rows: dict[str, QTreeWidgetItem] = {}
        # The user's column widths, by key: saved, shared by every list, changed only by them.
        self._widths: dict[str, int] = {}
        self._sizing = False  # the table is resizing a column, not the user
        self._marker = MatchMarker(self, columns=set(self.SEARCHED))
        self.setItemDelegate(self._marker)
        self.retranslate()
        header = self.header()
        # _fill_last_column stretches the last one. Off before any column hides: a column hidden
        # while it's on kept counting 100 px, and the scroll bar showed with nothing to scroll.
        header.setStretchLastSection(False)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._columns_menu)
        header.sectionResized.connect(self._resized)
        # Double-clicking a column's edge fits it (Qt's own); keep that width as the user's.
        header.sectionHandleDoubleClicked.connect(self._keep_width)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        # Selected items can be dragged onto a group in the Groups panel, to move them there.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        # Centred in the empty table when the picked tags leave nothing.
        self._empty = QWidget(self.viewport())
        self._empty_text = QLabel()
        self._empty_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_text.setWordWrap(True)
        self.clear_tags_button = QPushButton()
        self.clear_tags_button.setAutoDefault(False)
        note = QVBoxLayout(self._empty)
        note.addWidget(self._empty_text)
        note.addWidget(self.clear_tags_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self._empty.hide()

    def retranslate(self) -> None:
        """The column titles, in the current language."""

    def row_texts(self, item: Host) -> list[str]:
        """What each column shows for an item."""
        raise NotImplementedError

    def decorate(self, row: QTreeWidgetItem, item: Host) -> None:
        """Anything a row shows besides its texts (icons, tooltips, colours)."""

    def set_editable(self, editable: bool) -> None:
        self.setDragEnabled(editable)

    def mimeTypes(self) -> list[str]:
        return [HOSTS_MIME]

    def mimeData(self, items: Sequence[QTreeWidgetItem]) -> QMimeData:
        return hosts_mime([item.data(0, ROLE_ID) for item in items])

    def set_search(self, needle: str) -> None:
        """Marks the searched text."""
        self._marker.needle = needle
        self.viewport().update()

    def show_items(self, items: Sequence[Host]) -> None:
        keep = set(self.selected_ids())
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
        self.blockSignals(False)
        self._place_columns()
        self.itemSelectionChanged.emit()

    def show_no_match(self, text: str) -> None:
        """The note in the empty table when the picked tags leave nothing; "" hides it."""
        self._empty_text.setText(text)
        self.clear_tags_button.setText(_("Clear tags"))
        self._empty.setVisible(bool(text))
        self._place_empty()

    def _place_empty(self) -> None:
        if not self._empty.isVisible():
            return
        area = self.viewport().rect()
        # One line when the table is wide enough, wrapped only when it isn't.
        line = self._empty_text.fontMetrics().horizontalAdvance(self._empty_text.text())
        layout = self._empty.layout()
        margins = layout.contentsMargins() if layout is not None else None
        sides = margins.left() + margins.right() if margins is not None else 0
        width = min(line + sides + 4, area.width())
        size = QSize(width, self._empty.heightForWidth(width)).boundedTo(area.size())
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
            self.setColumnHidden(index, index > 0 and key in hidden)  # the first always shows
        self._place_columns()

    def _columns_menu(self, position: QPoint) -> None:
        """Right-click on the column titles: tick the columns to show."""
        menu = QMenu(self)
        header = self.headerItem()
        for index in range(1, len(self.COLUMNS)):
            item = menu.addAction(header.text(index))
            item.setCheckable(True)
            item.setChecked(not self.isColumnHidden(index))
            item.toggled.connect(lambda shown, i=index: self._show_column(i, shown))
        menu.addSeparator()
        menu.addAction(_("&Fit columns to content"), self.fit_columns)
        popup(menu, self.header().viewport().mapToGlobal(position))

    def _show_column(self, index: int, shown: bool) -> None:
        self.setColumnHidden(index, not shown)
        self._place_columns()  # one shown for the first time is fitted, once
        self.columns_changed.emit()

    def minimum_width(self, index: int) -> int:
        """A column is never narrower than its title. Qt keeps room for the sort arrow in every
        title; only the sorted column shows it, so the others leave it out."""
        header = self.header()
        if index == header.sortIndicatorSection():
            width = header.sectionSizeHint(index)
        else:
            header.setSortIndicatorShown(False)
            width = header.sectionSizeHint(index)
            header.setSortIndicatorShown(True)
        # Windows' own header draws a little wider than Qt measures (the column line, bolder
        # text): a few pixels more keep the last letter.
        return width + 6

    # ---- column widths: the user's ----

    def widths(self) -> dict[str, int]:
        return dict(self._widths)

    def set_widths(self, saved: object) -> None:
        """Widths saved by an earlier run; anything unknown (an old "notes" column) is skipped."""
        known = set(self.COLUMNS)
        self._widths = {
            k: v for k, v in (saved.items() if isinstance(saved, dict) else ())
            if k in known and isinstance(v, int) and v > 0
        }  # fmt: skip
        self._place_columns()

    def fit_columns(self) -> None:
        """Column titles' menu > Fit columns to content: every column shown, to its full text."""
        for column in self._shown():
            self._widths[self.COLUMNS[column]] = self._content_width(column)
        self._place_columns()

    def _place_columns(self) -> None:
        """Sizes each column shown: the user's width; a column with none yet (the first start,
        or switched on for the first time) is fitted once, and keeps that width from then on."""
        header = self.header()
        self._sizing = True
        for column in self._shown():
            key = self.COLUMNS[column]
            if key not in self._widths and (self.topLevelItemCount() or column in self.EMPTY):
                self._widths[key] = self._first_width(column)
            header.resizeSection(column, self._widths.get(key, self.minimum_width(column)))
        self._sizing = False
        self._fill_last_column()

    def _first_width(self, column: int) -> int:
        width = self._content_width(column)
        if column in self.EMPTY:
            width = max(width, self.fontMetrics().averageCharWidth() * self.EMPTY[column] + 16)
        return width

    def _content_width(self, column: int) -> int:
        """Its widest text, in full, and never narrower than its title."""
        return max(self.sizeHintForColumn(column), self.minimum_width(column))

    def _shown(self) -> list[int]:
        header = self.header()
        return [
            header.logicalIndex(v) for v in range(header.count())
            if not header.isSectionHidden(header.logicalIndex(v))
        ]  # fmt: skip

    def _fill_last_column(self) -> None:
        """The last column stretches into the room left on a wide window, so no gap shows on
        the right; on a narrow one it keeps its width and the scroll bar appears."""
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
        """A column dragged by the user keeps that width, never narrower than its title."""
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
        """As wide as its columns, the last at its own width (not stretched to fill), with the
        frame and the scroll bar."""
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
