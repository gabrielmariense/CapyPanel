"""The parts of the User profiles page: the PCs on the left, the header and the profiles table in
the middle (or a card saying what to do, or what went wrong), a profile's details on the right."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote.user_profiles import Deleted, Kind, Outcome, Profile
from capypanel.ui.hosts_tool.command_windows import Question, output_box
from capypanel.ui.hosts_tool.runner import HostTarget, escape
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import SearchBox, natural_key, pane_title
from capypanel.ui.menus import MenuCombo
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.rows import Filters, Result
from capypanel.ui.tables import fit_rows, grid_table

LEFT, RIGHT = 206, 284  # px: the PCs panel and Details, at a normal font size
TICK, USER, USED, SIZE, KIND, STATE = range(6)  # the table's columns
SORT_ROLE = Qt.ItemDataRole.UserRole + 1  # what a cell sorts by
ARROW = 16  # px a column title needs for the sort arrow
IDENT_ROLE = Qt.ItemDataRole.UserRole  # the row's profile
ALL_GROUPS = "*"  # the group dropdown's first choice: every PC of the list


def card() -> QFrame:
    """A box with the lists' background, as the other tools' panels."""
    frame = QFrame()
    frame.setObjectName("card")
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setBackgroundRole(QPalette.ColorRole.Base)
    frame.setAutoFillBackground(True)
    return frame


def hint(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("divider")
    line.setFixedHeight(1)
    return line


def _fold(text: str) -> str:
    return text.strip().casefold()


# ---- the PCs ----


class PcPane(QWidget):
    """The open host list's PCs, a group at a time: a dropdown picks the group (as the Groups
    panel does in Hosts; a list of hundreds of PCs is no place to look for one), and a search
    looks through the whole list. Under them, a field for any other PC. One Scan button names
    what it would scan: the PC picked in the list, or the one typed. Picking a PC empties the
    field and typing clears the pick, so there's never a doubt which. A double-click on a PC
    scans it; typing never does by itself."""

    scan_requested = Signal(object)  # a HostTarget
    list_picked = Signal(object)  # a host list's file (Path)
    group_picked = Signal(str)  # a group's id, ALL_GROUPS or NO_GROUP

    def __init__(self, choices: Callable[[], list[tuple[Path, str, bool]]]) -> None:
        super().__init__()
        self._choices = choices
        self._hosts: list[Host] = []  # every PC of the list that can be reached
        self._list: HostList | None = None
        self._group = ALL_GROUPS
        self.picker = MenuCombo()
        self.picker.setObjectName("listPicker")
        self.picker.menu().setToolTipsVisible(True)  # each list's path
        self.picker.menu().aboutToShow.connect(self._fill_menu)
        self.groups = QComboBox()
        self.groups.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )  # a long group name never widens the panel; the list that drops down shows it whole
        self.groups.setMinimumContentsLength(8)
        self.groups.activated.connect(self._group_chosen)
        self.search = SearchBox()
        self.search.textChanged.connect(self._show_hosts)
        self.search.to_results.connect(self._to_list)
        self.tree = QTreeWidget()
        self.tree.setObjectName("flat")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnCount(2)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._picked)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._scan())
        self.other_title = pane_title("")
        self.other = QLineEdit()
        self.other.textEdited.connect(self._typed)
        self.scan_button = QPushButton()
        self.scan_button.setAutoDefault(False)  # Enter in the field never scans
        self.scan_button.clicked.connect(self._scan)
        self.tip = hint()
        self.tip.setContentsMargins(6, 0, 0, 2)
        self.tip.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        box = card()
        inside = QVBoxLayout(box)
        inside.setContentsMargins(4, 4, 4, 6)
        inside.setSpacing(4)
        inside.addWidget(self.groups)
        inside.addWidget(self.search)
        inside.addWidget(self.tree, 1)
        inside.addWidget(_divider())
        inside.addWidget(self.other_title)
        for widget, gap in ((self.other, 6), (self.scan_button, 0)):
            row = QHBoxLayout()
            row.setContentsMargins(4, 0, 4, 0)
            row.addWidget(widget)
            inside.addLayout(row)
            inside.addSpacing(gap)
        inside.addWidget(self.tip)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.picker)
        layout.addWidget(box, 1)
        self.retranslate()

    def retranslate(self) -> None:
        # Not "Search name, address" as the wider panels say: it's cut at this width.
        self.search.setPlaceholderText(_("Search PCs"))
        self.search.setToolTip(_("Looks through every group for PCs with this name or address"))
        self.groups.setToolTip(_("Shows the PCs of one group"))
        self._fill_groups()
        self.other_title.setText(_("Another PC"))
        self.other.setPlaceholderText(_("Name or address"))
        self.tip.setText(_("Or double-click a PC in the list."))
        self._name_button()

    def show_list(
        self, name: str, tip: str, host_list: HostList | None, group: str = ALL_GROUPS
    ) -> None:
        """The open host list: its name on the dropdown, its groups, and the PCs of `group`
        that can be reached (ALL_GROUPS when the list has no such group any more)."""
        self.picker.setText(name)
        self.picker.setToolTip(tip)
        self._list = host_list
        hosts = host_list.hosts if host_list is not None else ()
        self._hosts = sorted(
            (h for h in hosts if h.connect_address), key=lambda h: natural_key(h.name)
        )
        self._group = group
        self._fill_groups()
        self._show_hosts()

    def group(self) -> str:
        """The group on show: its id, ALL_GROUPS or NO_GROUP."""
        return self._group

    def _fill_groups(self) -> None:
        """Every PC first, then the PCs in no group, then the groups as Hosts' Groups panel
        lists them, a level deeper a step to the right, each with how many PCs it holds."""
        host_list = self._list
        self.groups.blockSignals(True)
        self.groups.clear()
        self.groups.addItem(f"{_('All hosts')} ({len(self._hosts)})", ALL_GROUPS)
        if host_list is not None:
            loose = sum(1 for h in self._hosts if h.group == NO_GROUP)
            if loose:
                self.groups.addItem(f"{_('No group')} ({loose})", NO_GROUP)
            reachable = {h.id for h in self._hosts}

            def add(parent: str | None, depth: int) -> None:
                for group in host_list.children(parent):
                    inside = sum(1 for h in host_list.hosts_in(group.id) if h.id in reachable)
                    self.groups.addItem(f"{'    ' * depth}{group.name} ({inside})", group.id)
                    add(group.id, depth + 1)

            add(None, 0)
        index = self.groups.findData(self._group)
        if index < 0:  # the group is gone, or another list was opened
            index, self._group = 0, ALL_GROUPS
        self.groups.setCurrentIndex(index)
        self.groups.setEnabled(self.groups.count() > 1)
        self.groups.blockSignals(False)

    def _group_chosen(self, index: int) -> None:
        picked = self.groups.itemData(index)
        if isinstance(picked, str) and picked != self._group:
            self._group = picked
            self.search.clear()  # the group is on show, not the last search
            self._show_hosts()
            self.group_picked.emit(picked)

    def _in_group(self) -> list[Host]:
        """The PCs of the group on show, the ones in its groups inside it too."""
        if self._group == ALL_GROUPS or self._list is None:
            return self._hosts
        if self._group == NO_GROUP:
            return [h for h in self._hosts if h.group == NO_GROUP]
        inside = {h.id for h in self._list.hosts_in(self._group)}
        return [h for h in self._hosts if h.id in inside]

    def target(self) -> HostTarget | None:
        """What Scan would scan now."""
        typed = self.other.text().strip()
        if typed:
            known = next(
                (h for h in self._hosts if _fold(typed) in (_fold(h.name), _fold(h.address))),
                None,
            )
            return _target(known) if known else HostTarget(f"@{typed}", typed, typed)
        item = self.tree.currentItem()
        picked = item.data(0, IDENT_ROLE) if item is not None and item.isSelected() else None
        host = next((h for h in self._hosts if h.id == picked), None)
        return _target(host) if host else None

    def pick(self, key: str) -> None:
        """Marks the PC with this id, when the list has it."""
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(0, IDENT_ROLE) == key:
                self.tree.setCurrentItem(item)
                return

    def _show_hosts(self) -> None:
        kept = self.tree.currentItem()
        picked = kept.data(0, IDENT_ROLE) if kept is not None and kept.isSelected() else None
        needle = _fold(self.search.text())
        self.tree.blockSignals(True)
        self.tree.clear()
        muted = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
        for host in self._hosts if needle else self._in_group():  # a search: the whole list
            if needle and needle not in _fold(host.name) and needle not in _fold(host.address):
                continue
            item = QTreeWidgetItem([host.name, host.address])
            item.setData(0, IDENT_ROLE, host.id)
            item.setForeground(1, muted)
            self.tree.addTopLevelItem(item)
            if host.id == picked:
                self.tree.setCurrentItem(item)
        self.tree.resizeColumnToContents(0)
        self.tree.setColumnWidth(0, self.tree.columnWidth(0) + 14)
        self.tree.blockSignals(False)
        self._name_button()

    def _picked(self) -> None:
        if self.tree.selectedItems():
            self.other.clear()
        self._name_button()

    def _typed(self, text: str) -> None:
        if text.strip():
            self.tree.clearSelection()
        self._name_button()

    def _to_list(self) -> None:
        first = self.tree.topLevelItem(0)
        if first is not None:
            self.tree.setCurrentItem(first)
            self.tree.setFocus(Qt.FocusReason.TabFocusReason)

    def _name_button(self) -> None:
        target = self.target()
        self.scan_button.setEnabled(target is not None)
        self.scan_button.setText(
            _("Scan {pc}").format(pc=target.name) if target is not None else _("Scan")
        )

    def _scan(self) -> None:
        target = self.target()
        if target is not None:
            self.scan_requested.emit(target)

    def _fill_menu(self) -> None:
        menu = self.picker.menu()
        menu.clear()
        for path, name, current in self._choices():
            item = menu.addAction(name.replace("&", "&&"))
            item.setCheckable(True)
            item.setChecked(current)
            item.setToolTip(str(path))
            item.triggered.connect(lambda _c=False, p=path: self.list_picked.emit(p))


def _target(host: Host) -> HostTarget:
    return HostTarget(host.id, host.name, host.connect_address)


# ---- above the table ----


class HeaderCard(QFrame):
    """Which PC this is, always in sight; under it the filters, while there's a table."""

    filters_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        self.name = QLabel()
        font = QFont(self.name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        self.name.setFont(font)
        self.about = hint()
        self.about.setWordWrap(False)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.name)
        top.addWidget(self.about, 1)
        self.hide_own = QCheckBox()
        self.hide_own.setChecked(True)
        self.leftovers = QCheckBox()
        self.since_label = QLabel()
        self.since = QComboBox()
        self.shown = hint()
        self.shown.setWordWrap(False)
        self.filters = QWidget()
        row = QHBoxLayout(self.filters)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        row.addWidget(self.hide_own)
        row.addWidget(self.leftovers)
        row.addSpacing(6)
        pair = QHBoxLayout()
        pair.setSpacing(6)
        pair.addWidget(self.since_label)
        pair.addWidget(self.since)
        row.addLayout(pair)
        row.addStretch(1)
        row.addWidget(self.shown)
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 8, 10, 8)
        column.setSpacing(6)
        column.addLayout(top)
        column.addWidget(self.filters)
        self.retranslate()
        self.hide_own.toggled.connect(self.filters_changed)
        self.leftovers.toggled.connect(self.filters_changed)
        self.since.currentIndexChanged.connect(self.filters_changed)

    def retranslate(self) -> None:
        self.hide_own.setText(_("Hide Windows' own"))
        self.hide_own.setToolTip(
            _("Public, Default, the built-in Administrator and the like: never deleted here")
        )
        self.leftovers.setText(_("Only leftovers"))
        self.leftovers.setToolTip(
            _("Only registry entries without a folder and folders without a registry entry")
        )
        self.since_label.setText(_("Unused for:"))
        tip = _(
            "By the last sign-in or sign-out Windows wrote down; a row that has none goes by "
            "its folder's date"
        )
        self.since.setToolTip(tip)
        picked = max(self.since.currentIndex(), 0)
        self.since.blockSignals(True)
        self.since.clear()
        self.since.addItems([rows.months_text(months) for months in rows.MONTHS])
        self.since.setCurrentIndex(picked)
        self.since.blockSignals(False)

    def show_pc(self, name: str, about: str) -> None:
        self.name.setText(name)
        self.about.setText(about)

    def chosen(self) -> Filters:
        return Filters(
            hide_own=self.hide_own.isChecked(),
            leftovers=self.leftovers.isChecked(),
            months=rows.MONTHS[max(self.since.currentIndex(), 0)],
        )


class HintCard(QFrame):
    """The middle of the page when there's no table to show: what to do, or what happened."""

    def __init__(
        self,
        icon: str,
        color: QColor,
        title: str,
        lines: Sequence[str],
        buttons: Sequence[tuple[str, Callable[[], None]]] = (),
    ) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)
        sign = QLabel()
        sign.setPixmap(tabler_icon(icon, color, 40).pixmap(40, 40))
        sign.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.heading = QLabel(title)
        font = QFont(self.heading.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.heading.setFont(font)
        self.heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.heading.setWordWrap(True)
        self.body = hint("\n".join(lines))
        self.body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body.setFixedWidth(500)
        self.body.setMinimumHeight(self.body.heightForWidth(500))
        self.buttons: list[QPushButton] = []
        row = QHBoxLayout()
        row.addStretch(1)
        for text, run in buttons:
            button = QPushButton(text)
            button.setAutoDefault(False)
            button.clicked.connect(lambda _c=False, r=run: r())
            self.buttons.append(button)
            row.addWidget(button)
        row.addStretch(1)
        column = QVBoxLayout(self)
        column.addStretch(2)
        column.addWidget(sign)
        column.addSpacing(6)
        column.addWidget(self.heading)
        column.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(8)
        column.addLayout(row)
        column.addStretch(3)


# ---- the table ----


class _Row(QTreeWidgetItem):
    """Sorts by what a cell means (a date, a size), not by how it's written; rows that tie stay
    in name order."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else USER
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine == theirs:  # by name, A to Z, whichever way the column is sorted
            names = self.data(USER, SORT_ROLE), other.data(USER, SORT_ROLE)
            down = tree is not None and (
                tree.header().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
            )
            return bool(names[1] < names[0]) if down else bool(names[0] < names[1])
        return bool(mine < theirs)


class ProfilesTable(QWidget):
    """One row per profile and leftover. Only a row that can be deleted has a tick box; the
    others are greyed, with their state saying why. A row that was in a delete run shows how it
    ended instead of its state. A click on a column's title sorts by it."""

    picked = Signal()  # another row has the selection
    ticked_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 6)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.setSortingEnabled(True)
        # Newest first, as people scan the list for who still uses the PC; a click on Last used
        # turns it round, the oldest on top.
        self.tree.sortByColumn(USED, Qt.SortOrder.DescendingOrder)
        self.tree.itemSelectionChanged.connect(self.picked)
        self.tree.itemChanged.connect(self._changed)
        self._profiles: dict[str, Profile] = {}
        self._ticked: set[str] = set()
        self._results: dict[str, Result] = {}
        self._locked = False  # during a delete run no tick changes
        self._fitted = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.retranslate()

    def retranslate(self) -> None:
        self.tree.setHeaderLabels(["", _("User"), _("Last used"), _("Size"), _("Kind"), _("State")])

    def show_profiles(
        self,
        profiles: Sequence[Profile],
        sizes: dict[str, int | None],
        results: dict[str, Result] | None = None,
    ) -> None:
        """`sizes`: bytes for the rows counted; None for one being counted now. `results`: how
        the rows of a delete run stand. A tick on a row no longer shown is dropped: what's
        ticked is always in sight."""
        kept = self.selected()
        self._profiles = {p.ident: p for p in profiles}
        self._results = dict(results or {})
        before = set(self._ticked)
        self._ticked = {i for i in self._ticked if self._tickable(i)}
        self.tree.setSortingEnabled(False)  # or each cell set would move its row
        self.tree.blockSignals(True)
        self.tree.clear()
        for profile in profiles:
            item = _Row()
            item.setData(USER, IDENT_ROLE, profile.ident)
            self.tree.addTopLevelItem(item)
            self._fill(item, profile, sizes)
            if kept is not None and profile.ident == kept.ident:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        if not self._fitted and profiles:  # once: widths the admin drags afterwards stay
            self.fit()
        self.picked.emit()
        if before != self._ticked:
            self.ticked_changed.emit()

    def show_size(self, ident: str, sizes: dict[str, int | None]) -> None:
        """One row's size changed: counted, or being counted."""
        item = self._item(ident)
        if item is not None:
            self._fill_size(item, ident, sizes)

    def show_result(self, ident: str, result: Result | None) -> None:
        """One row moved on in a delete run; None takes it out of the run again."""
        if result is None:
            self._results.pop(ident, None)
        else:
            self._results[ident] = result
            if result in rows.ENDED:
                self._ticked.discard(ident)
        item = self._item(ident)
        if item is not None:
            self.tree.blockSignals(True)
            self._fill_state(item, self._profiles[ident])
            self.tree.blockSignals(False)

    def lock(self, locked: bool) -> None:
        """While profiles are deleted, the ticks can't change."""
        self._locked = locked
        self.tree.blockSignals(True)
        for ident in self._profiles:
            item = self._item(ident)
            if item is not None:
                self._fill_state(item, self._profiles[ident])
        self.tree.blockSignals(False)

    def fit(self) -> None:
        """Each column as wide as its text, and no wider: State, the last one, must stay in
        sight when the progress panel takes room on the right."""
        header = self.tree.header()
        header.setSortIndicatorShown(False)  # or every title is sized for an arrow it lacks
        for column in range(USER, STATE):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, self.tree.columnWidth(column) + 6)
        header.setSortIndicatorShown(True)
        sorted_by = header.sortIndicatorSection()
        if USER <= sorted_by < STATE:  # the one title that does have the arrow
            self.tree.setColumnWidth(sorted_by, self.tree.columnWidth(sorted_by) + ARROW)
        self.tree.setColumnWidth(TICK, 34)
        # Size starts empty: room for "counting…" and a size, so neither is ever cut.
        widest = max(
            self.tree.fontMetrics().horizontalAdvance(text)
            for text in (_("counting…"), rows.size_text(888 * rows.GB))
        )
        self.tree.setColumnWidth(SIZE, max(self.tree.columnWidth(SIZE), widest + 20))
        self._fitted = True

    def selected(self) -> Profile | None:
        items = self.tree.selectedItems()
        return self._profiles.get(items[0].data(USER, IDENT_ROLE)) if items else None

    def shown(self) -> list[Profile]:
        """The rows, in the order on screen."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [self._profiles[item.data(USER, IDENT_ROLE)] for item in found if item]

    def ticked(self) -> list[Profile]:
        """The rows ticked, in the order on screen."""
        return [p for p in self.shown() if p.ident in self._ticked]

    def tick(self, ident: str, on: bool = True) -> None:
        """Ticks a row as a click on its box does; a row without a box stays as it is."""
        item = self._item(ident)
        if item is not None and self._tickable(ident) and not self._locked:
            item.setCheckState(TICK, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def texts(self) -> list[list[str]]:
        """Every row's cells, in the order on screen (for tests); the tick's cell has no text."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [[item.text(c) for c in range(STATE + 1)] for item in found if item]

    def _item(self, ident: str) -> QTreeWidgetItem | None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(USER, IDENT_ROLE) == ident:
                return item
        return None

    def _tickable(self, ident: str) -> bool:
        """Ready, and not already through a delete run."""
        profile = self._profiles.get(ident)
        return profile is not None and profile.ready and self._results.get(ident) not in rows.ENDED

    def _changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != TICK:
            return
        ident = item.data(USER, IDENT_ROLE)
        on = item.checkState(TICK) == Qt.CheckState.Checked
        if on == (ident in self._ticked) or not self._tickable(ident):
            return
        (self._ticked.add if on else self._ticked.discard)(ident)
        self.tree.blockSignals(True)
        item.setData(TICK, SORT_ROLE, 0 if on else 1)
        self.tree.blockSignals(False)
        self.ticked_changed.emit()

    def _fill(self, item: QTreeWidgetItem, profile: Profile, sizes: dict[str, int | None]) -> None:
        item.setText(USER, rows.user_text(profile))
        item.setData(USER, SORT_ROLE, natural_key(profile.user))
        item.setText(USED, rows.date_text(profile.last_used) or "—")
        used = profile.last_used.timestamp() if profile.last_used else float("-inf")
        item.setData(USED, SORT_ROLE, used)
        item.setText(KIND, _(rows.KIND_NAMES[profile.kind]))
        item.setData(KIND, SORT_ROLE, list(Kind).index(profile.kind))
        item.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._fill_state(item, profile)
        self._fill_size(item, profile.ident, sizes)

    def _fill_state(self, item: QTreeWidgetItem, profile: Profile) -> None:
        """The tick box, the State cell and the row's colour: its state, or where it stands in
        a delete run."""
        ident, result = profile.ident, self._results.get(profile.ident)
        if result is None:
            item.setText(STATE, rows.state_name(profile.state))
            item.setIcon(STATE, dot_icon(rows.STATE_COLORS[profile.state], 10))
            item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
        else:
            icon, color = rows.RESULT_ICONS[result]
            item.setText(STATE, _(rows.RESULT_NAMES[result]))
            item.setIcon(STATE, tabler_icon(icon, QColor(color), 16))
            item.setData(STATE, SORT_ROLE, 10 + list(Result).index(result))
        flags = item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable
        if self._tickable(ident):
            if not self._locked:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            on = ident in self._ticked
            item.setCheckState(TICK, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
            item.setData(TICK, SORT_ROLE, 0 if on else 1)
        else:
            item.setData(TICK, Qt.ItemDataRole.CheckStateRole, None)  # no box at all
            item.setData(TICK, SORT_ROLE, 2)
        item.setFlags(flags)
        greyed = not profile.ready or result in (Result.DELETED, Result.QUEUED)
        role = QPalette.ColorRole.PlaceholderText if greyed else QPalette.ColorRole.Text
        brush = QBrush(self.palette().color(role))
        for column in (USER, USED, KIND, STATE):
            item.setForeground(column, brush)
        if item.text(SIZE) != _("counting…"):
            item.setForeground(SIZE, brush)

    def _fill_size(self, item: QTreeWidgetItem, ident: str, sizes: dict[str, int | None]) -> None:
        profile = self._profiles[ident]
        muted = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
        normal = QBrush(self.palette().color(QPalette.ColorRole.Text))
        if ident not in sizes:
            item.setText(SIZE, "")
            item.setData(SIZE, SORT_ROLE, -1)
            return
        size = sizes[ident]
        if size is None:
            item.setText(SIZE, _("counting…"))
            item.setForeground(SIZE, muted)
            item.setData(SIZE, SORT_ROLE, -1)
        else:
            greyed = not profile.ready or self._results.get(ident) is Result.DELETED
            item.setText(SIZE, rows.size_text(size))
            item.setForeground(SIZE, muted if greyed else normal)
            item.setData(SIZE, SORT_ROLE, size)


# ---- a profile's details ----


@dataclass(frozen=True)
class Shown:
    """What Details shows of one row."""

    profile: Profile
    root: str  # the PC's Users folder
    size: int | None  # bytes, once counted
    counting: bool = False
    result: Result | None = None  # where it stands in a delete run
    done: Deleted | None = None  # how its delete ended


class ProfileDetails(DetailsPanel):
    def __init__(self) -> None:
        self._hint_text = ""
        super().__init__()

    def pick_hint(self) -> str:
        return self._hint_text or _("Select a profile to see its details.")

    def selected_text(self, selected: int) -> str:
        return _("{n} profiles selected").format(n=selected)

    def item_id(self, shown: object) -> str:
        return shown.profile.ident if isinstance(shown, Shown) else ""

    def show_hint(self, text: str) -> None:
        """Nothing picked: `text` in the middle of the panel."""
        self._hint_text = text
        self.show_item(None, 0)

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, Shown)
        profile, result = shown.profile, shown.result
        name = self.value("name", profile.user)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        color = rows.RESULT_ICONS[result][1] if result else rows.STATE_COLORS[profile.state]
        dot = QLabel()
        dot.setPixmap(dot_icon(color, 12).pixmap(12, 12))
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(dot)
        top.addWidget(name, 1)
        layout.addLayout(top)
        state = _(rows.RESULT_NAMES[result]) if result else rows.state_name(profile.state)
        layout.addWidget(self.muted(f"{state} · {_(rows.KIND_NAMES[profile.kind])}"))

        if result is not None:
            self.section(layout, _("Result"))
            if shown.done is not None:
                layout.addWidget(self.muted(rows.result_why(shown.done)))
                if shown.done.detail and shown.done.outcome is not Outcome.DELETED:
                    layout.addSpacing(4)
                    layout.addWidget(self.muted(_("Windows answered:")))
                    layout.addWidget(self.value("windows", shown.done.detail))
            else:
                layout.addWidget(self.muted(_(rows.RESULT_NAMES[result])))
        else:
            self.section(layout, _("State"))
            layout.addWidget(self.muted(rows.state_why(profile, shown.root)))

        self.section(layout, _("Account"))
        account = self.value("account", profile.user) if profile.known else self.muted(_("Unknown"))
        sid = self.value("sid", profile.sid) if profile.sid else self.muted("—")
        self._pairs(layout, ((_("Account"), account), (_("SID"), sid)))
        if not profile.known and profile.sid:
            layout.addWidget(
                self.muted(_("Windows no longer knows this account; it was probably deleted."))
            )

        self.section(layout, _("Folder"))
        used, changed = rows.date_text(profile.last_used), rows.date_text(profile.modified)
        if shown.counting:
            size: QLabel = self.muted(_("counting…"))
        elif shown.size is None:
            size = self.muted(_("Not counted"))
        else:
            size = self.value("size", rows.size_text(shown.size))
        self._pairs(
            layout,
            (
                (_("Path"), self.value("path", profile.path) if profile.path else self.muted("—")),
                (_("Last used"), self.value("used", used) if used else self.muted("—")),
                (_("Folder changed"), self.value("changed", changed) if changed
                 else self.muted("—")),
                (_("Size"), size),
            ),
        )  # fmt: skip

        if result is None:
            self.section(layout, _("Kind"))
            layout.addWidget(self.muted(_(rows.KIND_WHY[profile.kind])))

    def _pairs(self, layout: QVBoxLayout, pairs: Sequence[tuple[str, QLabel]]) -> None:
        """A label on the left, its value on the same line, every value at the same x."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 92)
        for index, (label, value) in enumerate(pairs):
            name = QLabel(label)
            name.setObjectName("hint")
            name.setContentsMargins(0, 2, 0, 2)
            if value.objectName() == "hint":
                value.setContentsMargins(7, 2, 4, 2)  # as a copyable value's padding
            grid.addWidget(name, index, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, index, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(grid)


# ---- deleting ----


class DeleteDialog(Question):
    """The question before profiles are deleted: which ones, that it's final, and a word to
    type. The amber button lights only once the word is there; Cancel stays the default, so
    Enter in the field never confirms by itself."""

    def __init__(
        self, parent: QWidget | None, host: str, profiles: Sequence[Profile], sizes: dict[str, int]
    ) -> None:
        n = len(profiles)
        super().__init__(
            parent,
            _("Delete profiles from {host}").format(host=host),
            ngettext(
                "Delete {n} profile from {host}?", "Delete {n} profiles from {host}?", n
            ).format(n=n, host=host),
            _(
                "This is <b>final</b>. With local profiles, each person's desktop and documents "
                "go too: there's no recycle bin and no copy."
            ),
            ngettext("Delete {n} profile", "Delete {n} profiles", n).format(n=n),
        )
        self.table = grid_table([_("User"), _("Last used"), _("Size")])
        for profile in profiles:
            size = sizes.get(profile.ident)
            self.table.addTopLevelItem(
                QTreeWidgetItem(
                    [
                        rows.user_text(profile),
                        rows.date_text(profile.last_used) or "—",
                        rows.size_text(size) if size is not None else "",
                    ]
                )
            )
        total = ngettext("{n} profile", "{n} profiles", n).format(n=n)
        counted = [sizes[p.ident] for p in profiles if p.ident in sizes]
        if counted and len(counted) == n:
            total += " · " + rows.size_text(sum(counted))
        elif counted:
            total += " · " + _("{size} in the {n} counted").format(
                size=rows.size_text(sum(counted)), n=len(counted)
            )
        self.total = hint(total)
        note = hint(
            _(
                "The PC is checked again before each delete: anyone who signed in since the "
                "scan is skipped. Every delete goes in the log."
            )
        )
        self.word = QLineEdit()
        ask = QLabel(_("To confirm, type <b>{word}</b>:").format(word=escape(rows.confirm_word())))
        self.body.addSpacing(4)
        for widget in (self.table, self.total, note):
            self.body.addWidget(widget)
        self.body.addSpacing(6)
        self.body.addWidget(ask)
        self.body.addWidget(self.word)
        self.action.setEnabled(False)
        self.word.textChanged.connect(lambda text: self.action.setEnabled(rows.confirms(text)))
        self.resize(540, 10)
        fit_rows(self.table)
        self.word.setFocus()

    def accept(self) -> None:
        if rows.confirms(self.word.text()):  # never by a stray Enter on a greyed button
            super().accept()


class ProgressPanel(QWidget):
    """In Details' place while profiles are deleted, and after: the queue with each result, a
    line in the log per step, and Cancel the rest. Once it's over, Open the log and Close,
    which brings the details back."""

    cancel_requested = Signal()
    log_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.title = QLabel()
        font = QFont(self.title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        self.title.setFont(font)
        self.first, self.second = DetailsPanel.muted(""), DetailsPanel.muted("")
        self.bar = QProgressBar()
        self.bar.setObjectName("thin")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.queue = grid_table(["", ""])
        self.queue.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log = output_box("")
        self.log.setFont(QFont("Consolas", 8))
        self.cancel_button = QPushButton()
        self.log_button = QPushButton()
        self.close_button = QPushButton()
        for button in (self.cancel_button, self.log_button, self.close_button):
            button.setAutoDefault(False)
        self.note = DetailsPanel.muted("")
        self.cancel_button.clicked.connect(self._cancel)
        self.log_button.clicked.connect(self.log_requested)
        self.close_button.clicked.connect(self.closed)
        self._queue_title, self._log_title = QLabel(), QLabel()
        box = card()
        column = QVBoxLayout(box)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(3)
        for widget in (self.title, self.first, self.second):
            column.addWidget(widget)
        column.addSpacing(6)
        column.addWidget(self.bar)
        self._section(column, self._queue_title)
        column.addWidget(self.queue)
        self._section(column, self._log_title)
        column.addWidget(self.log)
        column.addSpacing(8)
        buttons = QHBoxLayout()
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.log_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        column.addLayout(buttons)
        column.addWidget(self.note)
        column.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        self._users: dict[str, QTreeWidgetItem] = {}
        self._over = False
        self._show_buttons()  # or the buttons of both states set the panel's narrowest width
        self.retranslate()

    @staticmethod
    def _section(layout: QVBoxLayout, heading: QLabel) -> None:
        """As Details' sections: a thin line, then the heading in the accent colour."""
        rule = QFrame()
        rule.setObjectName("detailsRule")
        layout.addSpacing(10)
        layout.addWidget(rule)
        layout.addSpacing(6)
        heading.setObjectName("detailsSection")
        layout.addWidget(heading)

    def retranslate(self) -> None:
        self._queue_title.setText(_("Queue"))
        self._log_title.setText(_("Log"))
        self.queue.setHeaderLabels([_("User"), _("Result")])
        self.cancel_button.setText(_("Cancel the rest"))
        self.log_button.setText(_("Open the log"))
        self.close_button.setText(_("Close"))
        self.note.setText(_("The current profile finishes first; the queued ones don't start."))
        self._show_title()

    def start(self, profiles: Sequence[Profile]) -> None:
        """A new run: every profile queued, an empty log."""
        self._over = False
        self._users = {}
        self.queue.clear()
        for profile in profiles:
            item = QTreeWidgetItem([rows.user_text(profile), ""])
            self.queue.addTopLevelItem(item)
            self._users[profile.ident] = item
            self.show_result(profile.ident, Result.QUEUED)
        self.queue.header().setStretchLastSection(True)
        self.queue.resizeColumnToContents(0)
        self.queue.setColumnWidth(0, self.queue.columnWidth(0) + 10)
        fit_rows(self.queue)
        self.log.clear()
        self.log.setFixedHeight(110)
        self.bar.setRange(0, len(profiles))
        self.bar.setValue(0)
        self.second.hide()
        self.cancel_button.setEnabled(True)
        self._show_buttons()
        self._show_title()

    def show_result(self, ident: str, result: Result | None) -> None:
        """None: taken out of the run (the rest was cancelled)."""
        item = self._users.get(ident)
        if item is None:
            return
        if result is None:
            item.setText(1, _("Not started"))
            item.setIcon(1, tabler_icon(*self._look(Result.QUEUED), 16))
        else:
            item.setText(1, _(rows.RESULT_NAMES[result]))
            item.setIcon(1, tabler_icon(*self._look(result), 16))
        greyed = result in (None, Result.QUEUED)
        role = QPalette.ColorRole.PlaceholderText if greyed else QPalette.ColorRole.Text
        for column in range(2):
            item.setForeground(column, QBrush(self.palette().color(role)))

    @staticmethod
    def _look(result: Result) -> tuple[str, QColor]:
        icon, color = rows.RESULT_ICONS[result]
        return icon, QColor(color)

    def show_progress(self, text: str, ended: int) -> None:
        """The grey line under the title, and how many of the queue have ended."""
        self.first.setText(text)
        self.bar.setValue(ended)

    def add_line(self, line: str) -> None:
        self.log.appendPlainText(line)

    def finish(self, first: str, second: str) -> None:
        """The run is over: what happened in two lines, the bar full, Open the log and Close."""
        self._over = True
        self.first.setText(first)
        self.second.setText(second)
        self.second.show()
        self.bar.setValue(self.bar.maximum())
        self.log.setFixedHeight(150)
        self._show_buttons()
        self._show_title()

    def over(self) -> bool:
        return self._over

    def _cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_requested.emit()

    def _show_buttons(self) -> None:
        for widget in (self.cancel_button, self.note):
            widget.setVisible(not self._over)
        for widget in (self.log_button, self.close_button):
            widget.setVisible(self._over)

    def _show_title(self) -> None:
        self.title.setText(_("Deletion finished") if self._over else _("Deleting profiles"))
