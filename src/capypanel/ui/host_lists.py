"""The lists a user works with in one tool: the default list, their personal list, the lists
in the tool's lists folders and every list they added (e.g. on a network share). Shown in
Settings (Host lists, for Hosts)."""

import html
import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFile, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog,
    QMenu,
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
from capypanel.ui.list_workspace.texts import ListTexts
from capypanel.ui.new_list import ask_new_list
from capypanel.ui.notes import notes
from capypanel.ui.tables import add_action, fit_rows, grid_table, row_menu, with_buttons

ROLE_PATH = Qt.ItemDataRole.UserRole
REMOVE, DELETE = "remove", "delete"
PATH_WIDTH = 380  # a path in a question box: longer ones are cut in the middle
log = logging.getLogger(__name__)


def access_text(access: Access, kind: ListKind) -> str:
    missing = _("Created when opened") if kind is not ListKind.SHARED else _("File not found")
    return {
        Access.READ_ONLY: _("Read-only"),
        Access.READ_WRITE: _("Read/write"),
        Access.MISSING: missing,
        Access.UNTRUSTED: _("Not used: made by another user"),
    }[access]


def ask_remove(parent: QWidget, path: Path, title: str) -> str | None:
    """Remove from the lists only, or delete the file too; None when cancelled. Cancel is the
    default, so Enter never deletes."""
    box = QMessageBox(
        QMessageBox.Icon.Question,
        title,
        _("Remove “{name}” from your lists, or delete its file too?").format(name=path.stem),
        parent=parent,
    )
    # The path on one line of its own, cut in the middle when long, so the window looks the
    # same whatever the path; the whole path is in the tooltip.
    bold = QFont(box.font())
    bold.setBold(True)
    shown = QFontMetrics(bold).elidedText(str(path), Qt.TextElideMode.ElideMiddle, PATH_WIDTH)
    gone = _("Deleting moves it to the Recycle Bin, for everyone who uses it:")
    box.setInformativeText(
        f'{html.escape(gone)}<p style="white-space: pre; margin: 0"><b>{html.escape(shown)}</b></p>'
    )
    box.setToolTip(str(path))
    delete = box.addButton(_("&Delete the file"), QMessageBox.ButtonRole.DestructiveRole)
    remove = box.addButton(_("&Remove from my lists"), QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    return DELETE if clicked is delete else REMOVE if clicked is remove else None


class ListsView(QWidget):
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
        texts: ListTexts,
    ) -> None:
        """found: the lists in the lists folders, shown with no adding, except the `hidden` ones
        the user removed here."""
        super().__init__()
        self.texts = texts
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
        self.new_button = QPushButton(_("&New…"))
        self.add_button = QPushButton(_("&Add existing…"))
        self.remove_button = QPushButton(_("&Remove"))
        self.remove_button.setToolTip(_("Takes it out of your lists, or deletes its file too"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        buttons = [self.new_button, self.add_button, self.remove_button]
        layout.addWidget(with_buttons(self.tree, buttons))
        row_menu(self.tree, self.fill_row_menu)  # Open, Save a copy and Open folder too
        layout.addWidget(
            notes(
                _("Lists saved in a lists folder show up here by themselves; Remove asks "
                  "whether to delete the file too.")
            )
        )  # fmt: skip

        self.add_button.clicked.connect(self._add_existing)
        self.new_button.clicked.connect(self._new)
        self.remove_button.clicked.connect(self._remove)
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
        self.remove_button.setEnabled(self._removable(path))

    def _removable(self, path: Path | None) -> bool:
        return path is not None and self._kind(path) is ListKind.SHARED

    def fill_row_menu(self, menu: QMenu) -> None:
        path = self.selected()
        readable = path is not None and path.is_file() and self.can_open(path)
        add_action(menu, _("&Open"), self.open_picked, self.can_open(path))
        add_action(menu, _("Save a &copy…"), self.copy_picked, readable)
        add_action(
            menu,
            _("Open &folder"),
            self.open_picked_folder,
            path is not None and path.parent.is_dir(),
        )
        menu.addSeparator()
        add_action(menu, _("&Remove"), self._remove, self._removable(path))

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
            self, self.texts.add, start, self.texts.file_filter
        )
        if name:
            self._keep(Path(name))

    def _new(self) -> None:
        # The default list is in the shared lists folder, the personal one in the user's.
        path = ask_new_list(
            self, shared_dir=self._default.parent, user_dir=self._personal.parent, texts=self.texts
        )
        kind = self.texts.kind
        if path is not None and self._write(
            path, lambda: OpenList.create(path, replace_existing=path.exists(), kind=kind)
        ):
            self._keep(path)
            self.open_requested.emit(path)  # made to be used: it opens now

    def copy_picked(self) -> None:
        """A copy of the list picked, as a new file kept in the lists."""
        source = self.selected()
        if source is None:
            return
        doc = self._document
        try:
            hosts = (
                doc.hosts
                if doc is not None and locations.same_path(source, doc.path)
                else OpenList.open(source, kind=self.texts.kind).hosts
            )
        except (HostListFileError, OSError) as e:
            message = _("Couldn't open “{path}”: {error}").format(path=source, error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return
        path = self._ask_path(_("Save a copy of the list"))
        if path is not None and self._write(
            path,
            lambda: OpenList.save_as(
                path, hosts, replace_existing=path.exists(), kind=self.texts.kind
            ),
        ):
            self._keep(path)

    def _remove(self) -> None:
        """Out of the user's lists, and, when they say so, its file into the Recycle Bin, so
        lists folders don't fill up with lists nobody uses."""
        path = self.selected()
        if path is None or self._kind(path) is not ListKind.SHARED:
            return
        answer = ask_remove(self, path, self.texts.remove) if self._can_delete(path) else REMOVE
        if answer is None:
            return
        if answer == DELETE:
            if not QFile.moveToTrash(str(path)):
                message = _("Couldn't move “{path}” to the Recycle Bin.").format(path=path)
                QMessageBox.warning(self, "CapyPanel", message)
                return
            log.info("Host list moved to the Recycle Bin: %s", path)
            self._all_found = [p for p in self._all_found if not locations.same_path(p, path)]
            self.hidden = [p for p in self.hidden if not locations.same_path(p, path)]
        elif self._in_folder(path):  # it would show up again by itself: hidden instead
            self.hidden.append(path)
        self.added = [p for p in self.added if not locations.same_path(p, path)]
        was_open = self._document is not None and locations.same_path(path, self._document.path)
        self._fill(self._default)
        self.changed.emit()
        if was_open:  # the default list takes its place
            self.open_requested.emit(self._default)

    def _can_delete(self, path: Path) -> bool:
        return locations.list_access(path) is Access.READ_WRITE

    def open_picked_folder(self) -> None:
        path = self.selected()
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _ask_path(self, title: str) -> Path | None:
        start = self._document.path.parent if self._document else self._personal.parent
        # The file dialog already asks before choosing an existing file.
        name, _filter = QFileDialog.getSaveFileName(self, title, str(start), self.texts.file_filter)
        return Path(name) if name else None

    def _write(self, path: Path, write: Callable[[], object]) -> bool:
        try:
            write()
        except (HostListFileError, OSError) as e:
            message = _("Couldn't write “{path}”: {error}").format(path=path, error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return False
        return True
