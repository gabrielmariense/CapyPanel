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
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _
from capypanel.core.remote.user_profiles import Kind, Profile
from capypanel.ui.hosts_tool.runner import HostTarget
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import DetailsPanel
from capypanel.ui.list_workspace.panels import SearchBox, natural_key, pane_title
from capypanel.ui.menus import MenuCombo
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.rows import Filters
from capypanel.ui.tables import grid_table

LEFT, RIGHT = 206, 284  # px: the PCs panel and Details, at a normal font size
USER, USED, SIZE, KIND, STATE = range(5)  # the table's columns
SORT_ROLE = Qt.ItemDataRole.UserRole + 1  # what a cell sorts by
IDENT_ROLE = Qt.ItemDataRole.UserRole  # the row's profile


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
    """The open host list's PCs, with a search; under them, a field for any other PC. One Scan
    button names what it would scan: the PC picked in the list, or the one typed. Picking a PC
    empties the field and typing clears the pick, so there's never a doubt which. A double-click
    on a PC scans it; typing never does by itself."""

    scan_requested = Signal(object)  # a HostTarget
    list_picked = Signal(object)  # a host list's file (Path)

    def __init__(self, choices: Callable[[], list[tuple[Path, str, bool]]]) -> None:
        super().__init__()
        self._choices = choices
        self._hosts: list[Host] = []
        self.picker = MenuCombo()
        self.picker.setObjectName("listPicker")
        self.picker.menu().setToolTipsVisible(True)  # each list's path
        self.picker.menu().aboutToShow.connect(self._fill_menu)
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
        self.search.setToolTip(_("Narrows the PCs to those with this name or address"))
        self.other_title.setText(_("Another PC"))
        self.other.setPlaceholderText(_("Name or address"))
        self.tip.setText(_("Or double-click a PC in the list."))
        self._name_button()

    def show_list(self, name: str, tip: str, hosts: Sequence[Host]) -> None:
        """The open host list: its name on the dropdown, its PCs that can be reached."""
        self.picker.setText(name)
        self.picker.setToolTip(tip)
        self._hosts = sorted(
            (h for h in hosts if h.connect_address), key=lambda h: natural_key(h.name)
        )
        self._show_hosts()

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
        for host in self._hosts:
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
    """One row per profile and leftover. A row that can't be deleted is greyed, with its state
    saying why. A click on a column's title sorts by it."""

    picked = Signal()  # another row has the selection

    def __init__(self) -> None:
        super().__init__()
        self.tree = grid_table([""] * 5)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(True)
        self.tree.setSortingEnabled(True)
        # Newest first, as people scan the list for who still uses the PC; a click on Last used
        # turns it round, the oldest on top.
        self.tree.sortByColumn(USED, Qt.SortOrder.DescendingOrder)
        self.tree.itemSelectionChanged.connect(self.picked)
        self._profiles: dict[str, Profile] = {}
        self._fitted = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tree)
        self.retranslate()

    def retranslate(self) -> None:
        self.tree.setHeaderLabels([_("User"), _("Last used"), _("Size"), _("Kind"), _("State")])

    def show_profiles(self, profiles: Sequence[Profile], sizes: dict[str, int | None]) -> None:
        """`sizes`: bytes for the rows counted; None for one being counted now."""
        kept = self.selected()
        self._profiles = {p.ident: p for p in profiles}
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

    def show_size(self, ident: str, sizes: dict[str, int | None]) -> None:
        """One row's size changed: counted, or being counted."""
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and item.data(USER, IDENT_ROLE) == ident:
                self._fill_size(item, ident, sizes)
                return

    def fit(self) -> None:
        for column in range(STATE):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, self.tree.columnWidth(column) + 6)
        # Size starts empty: room for "counting…" and a size, so neither is ever cut.
        widest = max(
            self.tree.fontMetrics().horizontalAdvance(text)
            for text in (_("counting…"), rows.size_text(888 * rows.GB))
        )
        self.tree.setColumnWidth(SIZE, max(self.tree.columnWidth(SIZE), widest + 24))
        self._fitted = True

    def selected(self) -> Profile | None:
        items = self.tree.selectedItems()
        return self._profiles.get(items[0].data(USER, IDENT_ROLE)) if items else None

    def shown(self) -> list[Profile]:
        """The rows, in the order on screen."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [self._profiles[item.data(USER, IDENT_ROLE)] for item in found if item]

    def texts(self) -> list[list[str]]:
        """Every row's cells, in the order on screen (for tests)."""
        found = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [[item.text(c) for c in range(5)] for item in found if item]

    def _fill(self, item: QTreeWidgetItem, profile: Profile, sizes: dict[str, int | None]) -> None:
        item.setText(USER, rows.user_text(profile))
        item.setData(USER, SORT_ROLE, natural_key(profile.user))
        item.setText(USED, rows.date_text(profile.last_used) or "—")
        used = profile.last_used.timestamp() if profile.last_used else float("-inf")
        item.setData(USED, SORT_ROLE, used)
        item.setText(KIND, _(rows.KIND_NAMES[profile.kind]))
        item.setData(KIND, SORT_ROLE, list(Kind).index(profile.kind))
        item.setText(STATE, rows.state_name(profile.state))
        item.setIcon(STATE, dot_icon(rows.STATE_COLORS[profile.state], 10))
        item.setData(STATE, SORT_ROLE, rows.STATE_ORDER.index(profile.state))
        item.setTextAlignment(SIZE, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if not profile.ready:
            muted = QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText))
            for column in range(5):
                item.setForeground(column, muted)
        self._fill_size(item, profile.ident, sizes)

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
            item.setText(SIZE, rows.size_text(size))
            item.setForeground(SIZE, normal if profile.ready else muted)
            item.setData(SIZE, SORT_ROLE, size)


# ---- a profile's details ----


@dataclass(frozen=True)
class Shown:
    """What Details shows of one row."""

    profile: Profile
    root: str  # the PC's Users folder
    size: int | None  # bytes, once counted
    counting: bool = False


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
        profile = shown.profile
        name = self.value("name", profile.user)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        dot = QLabel()
        dot.setPixmap(dot_icon(rows.STATE_COLORS[profile.state], 12).pixmap(12, 12))
        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(dot)
        top.addWidget(name, 1)
        layout.addLayout(top)
        state, kind = rows.state_name(profile.state), _(rows.KIND_NAMES[profile.kind])
        layout.addWidget(self.muted(f"{state} · {kind}"))

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
