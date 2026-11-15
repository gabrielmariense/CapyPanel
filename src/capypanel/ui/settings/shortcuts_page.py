"""Settings › CapyPanel › Keyboard shortcuts: every command a key can run, with its key. A
double-click (or Enter) on a command waits for its new key; Clear and Restore default under the
list act on the picked command. A key another command runs is moved only after a question."""

from PySide6.QtCore import QKeyCombination, Qt, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QLineEdit, QMessageBox, QPushButton, QTreeWidgetItem

from capypanel.core.i18n import _
from capypanel.ui import shortcuts
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import hint
from capypanel.ui.settings.pages import Page, Section
from capypanel.ui.shortcuts import Keys, Row
from capypanel.ui.tables import fit_rows, grid_table, with_buttons

COMMAND, WHERE, KEY = range(3)  # the table's columns
ROW_ROLE = Qt.ItemDataRole.UserRole  # the row's command id
MODIFIERS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
             Qt.Key.Key_AltGr, Qt.Key.Key_unknown)  # fmt: skip
HELD = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)  # fmt: skip


class KeyCatcher(QLineEdit):
    """In a command's Key cell while it waits: the next key pressed, with Ctrl, Alt or Shift,
    is its new key. Esc, or a click elsewhere, leaves the key as it was."""

    picked = Signal(str)  # the key, in portable text
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText(_("Press the new key…"))
        self._done = False

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002, N802 -- Qt's names
        return False  # Tab is a key pressed here, not a move to the next control

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in MODIFIERS:
            return  # Ctrl alone: wait for the key that goes with it
        held = event.modifiers() & HELD
        if key == Qt.Key.Key_Escape and not held:
            self._end(cancel=True)
            return
        if key == Qt.Key.Key_Backtab:
            key, held = Qt.Key.Key_Tab, held | Qt.KeyboardModifier.ShiftModifier
        keys = QKeySequence(QKeyCombination(held, Qt.Key(key)))
        self._done = True
        self.picked.emit(shortcuts.portable(keys))

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self._end(cancel=True)

    def _end(self, *, cancel: bool) -> None:
        if not self._done:
            self._done = True
            if cancel:
                self.cancelled.emit()


class ShortcutsPage(Page):
    """The commands, where each runs and its key; `keys` keeps and applies every change."""

    def __init__(self, keys: Keys, place_names: dict[str, str]) -> None:
        super().__init__(_("Keyboard shortcuts"))
        self.keys = keys
        self._names = place_names
        self.section = Section(_("Keyboard shortcuts"))
        self.about = hint(
            _(
                "Double-click a command, then press its new key. A command Hosts and Printers "
                "share has one key for both. F1 and Esc stay free for help and closing."
            )  # fmt: skip
        )
        self.table = grid_table([_("Command"), _("Where"), _("Key")])
        self.table.itemActivated.connect(lambda item, _c: self.change(item))
        self.table.itemSelectionChanged.connect(self._enable)
        self.clear = QPushButton(_("C&lear"))
        self.restore = QPushButton(_("Restore &default"))
        self.clear.clicked.connect(lambda: self._set_picked(""))
        self.restore.clicked.connect(self._restore_picked)
        self.problem = hint()  # why a key wasn't taken
        self.problem.hide()
        self.section.content.addWidget(self.about)
        self.section.content.addWidget(with_buttons(self.table, [self.clear, self.restore]))
        self.section.content.addWidget(self.problem)
        self.body.addWidget(self.section)
        self.body.addStretch(1)
        self._catcher: KeyCatcher | None = None
        self._fill()

    # ---- the table ----

    def _fill(self) -> None:
        self.table.clear()
        for row in self.keys.rows:
            item = QTreeWidgetItem([row.name(), shortcuts.places_text(row.places, self._names),
                                    ""])  # fmt: skip
            item.setData(COMMAND, ROW_ROLE, row.id)
            self.table.addTopLevelItem(item)
            self._show_key(item)
        fit_rows(self.table)
        self._enable()

    def _show_key(self, item: QTreeWidgetItem) -> None:
        keys = self.keys.key(self._row(item))
        item.setText(KEY, shortcuts.shown(keys) if keys else "")

    def _row(self, item: QTreeWidgetItem) -> Row:
        return self.keys.row(str(item.data(COMMAND, ROW_ROLE)))

    def item_of(self, row_id: str) -> QTreeWidgetItem:
        found = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return next(i for i in found if i is not None and i.data(COMMAND, ROW_ROLE) == row_id)

    def _picked(self) -> Row | None:
        items = self.table.selectedItems()
        return self._row(items[0]) if items else None

    def _enable(self) -> None:
        row = self._picked()
        self.clear.setEnabled(row is not None and bool(self.keys.key(row)))
        self.restore.setEnabled(row is not None and self.keys.key(row) != row.default)

    def _refresh(self) -> None:
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if item is not None:
                self._show_key(item)
        self._enable()

    # ---- changing a key ----

    def change(self, item: QTreeWidgetItem) -> None:
        """Waits in the command's Key cell for its new key."""
        self._stop_catching()
        self.table.setCurrentItem(item)
        self.problem.hide()
        catcher = self._catcher = KeyCatcher()
        catcher.picked.connect(lambda keys: self._caught(item, keys))
        catcher.cancelled.connect(self._stop_catching)
        self.table.setItemWidget(item, KEY, catcher)
        catcher.setFocus()

    def _stop_catching(self) -> None:
        if self._catcher is None:
            return
        self._catcher = None
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if item is not None and self.table.itemWidget(item, KEY) is not None:
                self.table.removeItemWidget(item, KEY)
        self.table.setFocus()

    def _caught(self, item: QTreeWidgetItem, keys: str) -> None:
        self._stop_catching()
        why = shortcuts.refused(keys)
        if why:
            self._say(why)
            return
        self._give(self._row(item), keys)

    def _give(self, row: Row, keys: str) -> None:
        """`keys` to `row`, once a command that has them now may give them up."""
        other = self.keys.clash(row, keys) if keys else None
        if other is not None and not self._move_asked(row, other, keys):
            return
        self.keys.set(row, keys)
        self.problem.hide()
        self._refresh()
        self.changed.emit()

    def _move_asked(self, row: Row, other: Row, keys: str) -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, _("Keyboard shortcuts"),
                          _("{key} runs {other} now. Give it to {command} instead?").format(
                              key=shortcuts.shown(keys), other=other.name(),
                              command=row.name()),
                          QMessageBox.StandardButton.Cancel, self)  # fmt: skip
        move = box.addButton(_("&Give it"), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(move)
        box.setInformativeText(_("{other} is left with no key.").format(other=other.name()))
        run_modal(box)
        return box.clickedButton() is move

    def _say(self, why: str) -> None:
        self.problem.setText(why)
        self.problem.show()

    def _set_picked(self, keys: str) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, keys)

    def _restore_picked(self) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, row.default)
