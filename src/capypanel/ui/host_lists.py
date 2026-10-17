"""The host lists a user works with: the default list, their personal list and every list they
added (e.g. on a network share). The same view sits in File > Host lists… and in Settings."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts import locations
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.listfile import HostListFileError
from capypanel.core.hosts.locations import Access, ListKind
from capypanel.core.i18n import _
from capypanel.ui.hosts import list_file_filter
from capypanel.ui.notes import notes

ROLE_PATH = Qt.ItemDataRole.UserRole


def access_text(access: Access, kind: ListKind) -> str:
    missing = _("Created when opened") if kind is not ListKind.SHARED else _("File not found")
    return {
        Access.READ_ONLY: _("Read-only"),
        Access.READ_WRITE: _("Read/write"),
        Access.MISSING: missing,
        Access.UNTRUSTED: _("Not used: made by another user"),
    }[access]


class HostListsView(QWidget):
    """The lists, with the one in use in bold and marked, and buttons to add, create or forget.
    Adding or forgetting only changes this view's copy; its owner decides when to keep it."""

    changed = Signal()
    activated = Signal()  # a double-click: open it

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        added: list[Path],
        document: OpenList | None,
        found: list[Path] | None = None,
    ) -> None:
        """found: the lists in the lists folders; they show up by themselves and can't be
        removed here."""
        super().__init__()
        self._default, self._personal, self._document = default_list, personal_list, document
        self._found = found or []
        self.added = [
            p for p in added
            if self._kind(p) is ListKind.SHARED and not self._in_folder(p)
        ]  # fmt: skip
        self.written: list[Path] = []  # files created here, so opening them reloads them

        self.tree = QTreeWidget()
        self.tree.setObjectName("grid")  # lines between rows and columns
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([_("List"), _("Type"), _("Access")])  # the path: tooltip
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # drag to resize
        header.setStretchLastSection(True)
        self.tree.setColumnWidth(0, 170)
        self.tree.setColumnWidth(1, 105)
        self.add_button = QPushButton(_("&Add existing…"))
        self.new_button = QPushButton(_("&New…"))
        self.copy_button = QPushButton(_("&Copy current list to…"))
        self.copy_button.setEnabled(document is not None)
        self.remove_button = QPushButton(_("&Remove from the list"))
        self.remove_button.setToolTip(_("Forgets it here; the file itself is never deleted"))
        # A column beside the list, as on the Connections page.
        buttons = QVBoxLayout()
        for button in (self.add_button, self.new_button, self.copy_button, self.remove_button):
            button.setAutoDefault(False)  # Enter opens the list, never adds one
            buttons.addWidget(button)
        buttons.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.tree, 1)
        row.addLayout(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row, 1)
        layout.addWidget(
            notes(
                _("Default list: shared by everyone on this PC."),
                _("Personal list: only yours."),
                _("Lists saved in a lists folder show up by themselves."),
                _("Hover over a list to see where it is."),
                _("Removing a list from here never deletes its file."),
            )
        )

        self.add_button.clicked.connect(self._add_existing)
        self.new_button.clicked.connect(self._new)
        self.copy_button.clicked.connect(self._copy_current)
        self.remove_button.clicked.connect(self._remove)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.activated.emit())
        self._fill(document.path if document else personal_list)

    # ---- reading ----

    def selected(self) -> Path | None:
        items = self.tree.selectedItems()
        return Path(items[0].data(0, ROLE_PATH)) if items else None

    def can_open(self, path: Path | None) -> bool:
        """The default and personal lists are created when missing; other lists must exist."""
        if path is None:
            return False
        access = locations.list_access(path, shared=self._kind(path) is ListKind.DEFAULT)
        if access is Access.UNTRUSTED:
            return False
        return access is not Access.MISSING or self._kind(path) is not ListKind.SHARED

    def select(self, path: Path) -> None:
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item is not None and locations.same_path(Path(item.data(0, ROLE_PATH)), path):
                self.tree.setCurrentItem(item)
                return

    def saved(self, document: OpenList | None) -> None:
        """After a Save that keeps the window open: the open list may have changed."""
        selected = self.selected()
        self._document = document
        self.written.clear()
        self._fill(selected)

    # ---- building ----

    def _kind(self, path: Path) -> ListKind:
        return locations.list_kind(path, default=self._default, personal=self._personal)

    def _fill(self, select: Path | None) -> None:
        self.tree.clear()
        current = self._document.path if self._document else None
        paths: list[Path] = []
        for path in (self._default, self._personal, *self._found, *self.added):
            if not any(locations.same_path(path, p) for p in paths):  # each once
                paths.append(path)
        names = locations.list_names(paths, default=self._default, personal=self._personal)
        for path, name in zip(paths, names, strict=True):
            kind = self._kind(path)
            kind_text = {
                ListKind.DEFAULT: _("Default"),
                ListKind.PERSONAL: _("Personal"),
                ListKind.SHARED: _("Lists folder") if self._in_folder(path) else _("Added"),
            }[kind]
            access = locations.list_access(path, shared=kind is ListKind.DEFAULT)
            is_open = current is not None and locations.same_path(path, current)
            if is_open:
                name = _("{name} (in use)").format(name=name)
            item = QTreeWidgetItem([name, kind_text, access_text(access, kind)])
            item.setData(0, ROLE_PATH, str(path))
            tip = _("{path} (in use)").format(path=path) if is_open else str(path)
            for column in range(3):
                item.setToolTip(column, tip)
            if is_open:
                font = item.font(0)
                font.setBold(True)
                for column in range(3):
                    item.setFont(column, font)
            self.tree.addTopLevelItem(item)
        if select is not None:
            self.select(select)
        self._selection_changed()

    def _in_folder(self, path: Path) -> bool:
        return any(locations.same_path(path, p) for p in self._found)

    def _selection_changed(self) -> None:
        path = self.selected()
        removable = path is not None and self._kind(path) is ListKind.SHARED
        self.remove_button.setEnabled(removable and path is not None and not self._in_folder(path))
        self.changed.emit()

    # ---- changing ----

    def _keep(self, path: Path) -> None:
        if self._kind(path) is ListKind.SHARED and not any(
            locations.same_path(path, p) for p in self.added
        ):
            self.added.append(path)
        self._fill(path)

    def _add_existing(self) -> None:
        start = str((self.selected() or self._personal).parent)
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Add a host list"), start, list_file_filter()
        )
        if name:
            self._keep(Path(name))

    def _new(self) -> None:
        path = self._ask_path(_("New empty host list"))
        if path is not None and self._write(
            path, lambda: OpenList.create(path, replace_existing=path.exists())
        ):
            self._keep(path)

    def _copy_current(self) -> None:
        doc = self._document
        path = self._ask_path(_("Copy the current list to")) if doc else None
        if (
            doc is not None
            and path is not None
            and self._write(
                path, lambda: OpenList.save_as(path, doc.hosts, replace_existing=path.exists())
            )
        ):
            self._keep(path)

    def _remove(self) -> None:
        path = self.selected()
        if path is None or self._kind(path) is not ListKind.SHARED:
            return
        self.added = [p for p in self.added if not locations.same_path(p, path)]
        self._fill(self._default)  # the one opened on Save, if the removed list was open

    def _ask_path(self, title: str) -> Path | None:
        start = self._document.path.parent if self._document else self._personal.parent
        # The file dialog already asks before choosing an existing file.
        name, _filter = QFileDialog.getSaveFileName(self, title, str(start), list_file_filter())
        return Path(name) if name else None

    def _write(self, path: Path, write: Callable[[], object]) -> bool:
        try:
            write()
        except (HostListFileError, OSError) as e:
            message = _("Couldn't write “{path}”: {error}").format(path=path, error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return False
        self.written.append(path)
        return True
