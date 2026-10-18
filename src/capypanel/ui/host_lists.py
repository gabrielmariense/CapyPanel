"""The host lists a user works with: the default list, their personal list, the lists in the
lists folders and every list they added (e.g. on a network share). Shown in Settings > Host
lists."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
    QPushButton,
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
from capypanel.ui.tables import fit_rows, grid_table, with_buttons

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
    `changed` fires when the lists change; `open_requested` asks to open one now: a double-click,
    a new list, or the default list when the open one is removed."""

    changed = Signal()
    open_requested = Signal(object)  # a list's Path

    def __init__(
        self,
        *,
        default_list: Path,
        personal_list: Path,
        added: list[Path],
        document: OpenList | None,
        found: list[Path] | None = None,
        hidden: list[Path] | None = None,
    ) -> None:
        """found: the lists in the lists folders, shown with no adding, except the `hidden` ones
        the user removed here."""
        super().__init__()
        self._default, self._personal, self._document = default_list, personal_list, document
        self._all_found = found or []
        self.hidden = [p for p in hidden or [] if self._in_folder(p)]
        self.added = [
            p for p in added
            if self._kind(p) is ListKind.SHARED and not self._in_folder(p)
        ]  # fmt: skip

        self.tree = grid_table([_("List"), _("Type"), _("Access")])  # the path: tooltip
        self.tree.setColumnWidth(0, 170)
        self.tree.setColumnWidth(1, 105)
        self.add_button = QPushButton(_("&Add existing…"))
        self.new_button = QPushButton(_("&New…"))
        self.copy_button = QPushButton(_("Save a &copy…"))
        self.copy_button.setToolTip(_("Saves a copy of the list in use as a new file"))
        self.copy_button.setEnabled(document is not None)
        self.remove_button = QPushButton(_("&Remove"))
        self.remove_button.setToolTip(_("Forgets it here; the file itself is never deleted"))
        self.open_folder = QPushButton(_("Open folder"))
        self.open_folder.setToolTip(_("Opens the folder the list is in"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        buttons = [
            self.add_button, self.new_button, self.copy_button, self.remove_button,
            self.open_folder,
        ]  # fmt: skip
        layout.addWidget(with_buttons(self.tree, buttons))
        layout.addWidget(
            notes(
                _("Lists saved in a lists folder show up here by themselves; removing one never "
                  "deletes its file.")
            )
        )  # fmt: skip

        self.add_button.clicked.connect(self._add_existing)
        self.new_button.clicked.connect(self._new)
        self.copy_button.clicked.connect(self._copy_current)
        self.remove_button.clicked.connect(self._remove)
        self.open_folder.clicked.connect(self._open_folder)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.open_picked())
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

    def list_opened(self, document: OpenList | None) -> None:
        """The main window opened a list: it's the one marked in use now."""
        selected = self.selected()
        self._document = document
        self.copy_button.setEnabled(document is not None)
        self._fill(selected)

    def open_picked(self) -> None:
        path = self.selected()
        if path is None:
            return
        if not self.can_open(path):
            message = _("“{name}” can't be opened: {why}").format(
                name=path.name,
                why=self.tree.currentItem().text(2).lower(),  # type: ignore[union-attr]
            )
            QMessageBox.warning(self, "CapyPanel", message)
            return
        self.open_requested.emit(path)

    # ---- building ----

    def _kind(self, path: Path) -> ListKind:
        return locations.list_kind(path, default=self._default, personal=self._personal)

    def _fill(self, select: Path | None) -> None:
        self.tree.clear()
        current = self._document.path if self._document else None
        paths: list[Path] = []
        for path in (self._default, self._personal, *self._found(), *self.added):
            if not any(locations.same_path(path, p) for p in paths):  # each once
                paths.append(path)
        names = locations.list_names(paths, default=self._default, personal=self._personal)
        for path, name in zip(paths, names, strict=True):
            kind = self._kind(path)
            kind_text = self._type_text(path, kind)
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
        fit_rows(self.tree)
        if select is not None:
            self.select(select)
        self._selection_changed()

    def _type_text(self, path: Path, kind: ListKind) -> str:
        """Who it's for: shared with everyone on the PC, yours alone, or added from elsewhere."""
        if kind is ListKind.PERSONAL:
            return _("Yours")
        if kind is ListKind.DEFAULT:
            return _("Shared")
        if self._in_folder(path):
            mine = locations.same_path(path.parent, self._personal.parent)
            return _("Yours") if mine else _("Shared")
        return _("Added")

    def _found(self) -> list[Path]:
        return [
            p for p in self._all_found if not any(locations.same_path(p, h) for h in self.hidden)
        ]

    def _in_folder(self, path: Path) -> bool:
        return any(locations.same_path(path, p) for p in self._all_found)

    def _selection_changed(self) -> None:
        path = self.selected()
        self.remove_button.setEnabled(path is not None and self._kind(path) is ListKind.SHARED)
        self.open_folder.setEnabled(path is not None and path.parent.is_dir())

    # ---- changing ----

    def _keep(self, path: Path) -> None:
        if self._in_folder(path):  # one removed before comes back
            self.hidden = [p for p in self.hidden if not locations.same_path(p, path)]
        elif self._kind(path) is ListKind.SHARED and not any(
            locations.same_path(path, p) for p in self.added
        ):
            self.added.append(path)
        self._fill(path)
        self.changed.emit()

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
            self.open_requested.emit(path)  # made to be used: it opens now

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
        if self._in_folder(path):  # it would show up again by itself: hidden instead
            self.hidden.append(path)
        self.added = [p for p in self.added if not locations.same_path(p, path)]
        was_open = self._document is not None and locations.same_path(path, self._document.path)
        self._fill(self._default)
        self.changed.emit()
        if was_open:  # the default list takes its place
            self.open_requested.emit(self._default)

    def _open_folder(self) -> None:
        path = self.selected()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

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
        return True
