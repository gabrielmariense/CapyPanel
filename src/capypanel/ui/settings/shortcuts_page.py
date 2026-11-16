"""Settings › CapyPanel › Keyboard shortcuts: every command a key can run, with its key. A
double-click (or Enter) on a command waits for its new key; Clear and Restore default under the
list act on the picked command. A key another command runs is moved only after a question.
The commands sit under headings, the menu bar's menus first, then each tool, A–Z under each
(War Room topic-shortcuts-page, 2026-11-16: the Where column read as a wall of text)."""

import unicodedata
from typing import cast

from PySide6.QtCore import QKeyCombination, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QFocusEvent,
    QFontMetrics,
    QHideEvent,
    QKeyEvent,
    QKeySequence,
    QPalette,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionFrame,
    QStyleOptionViewItem,
    QTreeWidgetItem,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.ui import shortcuts, spacing
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import hint
from capypanel.ui.settings.pages import Page, Section
from capypanel.ui.shortcuts import Keys, Row
from capypanel.ui.tables import fit_rows, grid_table, with_buttons
from capypanel.ui.themes import engine as themes

COMMAND, KEY = range(2)  # the table's columns
ROWS = 14  # shown before it scrolls: about sixty commands, a page that's mostly this list
ROW_ROLE = Qt.ItemDataRole.UserRole  # the row's command id; a heading has none
KEY_WIDTH = 120  # the Key column at least; wider when "Ctrl+Shift+O (in the list)" needs it
LINE_EDIT_MARGIN = 2  # Qt keeps this much inside a field's contents on each side
HEADING_GAP = 6  # above each heading but the first, as the Commands window's groups have
HEADING_PADDING = 5  # above and under a heading's text, as the rows' cells have
GAP_ROLE = Qt.ItemDataRole.UserRole + 1  # a heading's: whether it has the gap above
MODIFIERS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
             Qt.Key.Key_AltGr, Qt.Key.Key_unknown)  # fmt: skip
HELD = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)  # fmt: skip


def alphabetical(name: str) -> str:
    """A command's name as A–Z sorts it in any language: no accents, no case, no "…"."""
    plain = unicodedata.normalize("NFD", name.replace("…", ""))
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def lead(text: str) -> QLabel:
    """The page's one instruction: this page is only the list, so its line reads as body text,
    one point up from the app's font, not as a grey hint (Dante, 2026-11-16)."""
    label = QLabel(text)
    label.setObjectName("lead")
    label.setWordWrap(True)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + 1)  # follows a larger Windows font
    label.setFont(font)
    return label


def reserved_line() -> str:
    """The line under the buttons, read in the language shown now."""
    return _("F1, Esc, Ctrl+F and Tab are kept for CapyPanel itself.")


def top_menu(action: QAction) -> tuple[int, QMenu] | None:
    """The menu bar's menu `action` is in (through a submenu too) and its place on the bar,
    or None. A menu elsewhere, the tray's, doesn't count. Qt's own class names, not Python's
    isinstance, so a QMenu subclass made anywhere still counts."""
    for menu in action.associatedObjects():
        while isinstance(menu, QWidget) and menu.inherits("QMenu"):
            owners = cast(QMenu, menu).menuAction().associatedObjects()
            bars = [o for o in owners if o.inherits("QMenuBar")]
            if bars:
                place = cast(QMenuBar, bars[0]).actions().index(cast(QMenu, menu).menuAction())
                return place, cast(QMenu, menu)
            menu = next((o for o in owners if o.inherits("QMenu")), None)
    return None


def plain(text: str) -> str:
    """A menu's words without the access key's &."""
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


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
    """The commands under their headings, each with its key; `keys` keeps and applies every
    change."""

    def __init__(self, keys: Keys, place_names: dict[str, str]) -> None:
        super().__init__(_("Keyboard shortcuts"))
        self.keys = keys
        self._names = place_names
        self.section = Section(_("Command keys"))  # not the page's name again: what its list holds
        self.about = lead(_("Double-click a command and press its new key."))
        self.table = grid_table([_("Command"), _("Key")])
        self.table.itemActivated.connect(lambda item, _c: self.change(item))
        self.table.itemSelectionChanged.connect(self._enable)
        self.clear = QPushButton(_("C&lear"))
        self.restore = QPushButton(_("&Restore default"))
        self.clear.clicked.connect(lambda: self._set_picked(""))
        self.restore.clicked.connect(self._restore_picked)
        self.problem = hint(reserved_line())  # the reserved keys, or why a key wasn't taken
        self.section.content.addWidget(self.about)
        self.section.content.addSpacing(spacing.CONTROLS - self.section.content.spacing())
        self.section.content.addWidget(with_buttons(self.table, [self.clear, self.restore]))
        self.section.content.addWidget(self.problem)
        self.body.addWidget(self.section)
        self.body.addStretch(1)
        self._catcher: KeyCatcher | None = None
        self._fill()
        themes.switches().switched.connect(self._restyle)

    # ---- the table ----

    def _heading(self, row: Row) -> tuple[tuple[int, int], str]:
        """Where its heading goes and what it says: the window's own commands under their
        menu (File, View, Help, as on the bar), then each tool's in the tools' order."""
        tools = list(self._names)
        if shortcuts.EVERYWHERE in row.places:
            found = top_menu(row.actions[0]) if row.actions else None
            if found is None:
                return (0, 0), _("Menu bar")
            place, menu = found
            return (0, place), plain(menu.title())
        tool = row.places[0]
        return (1, tools.index(tool) if tool in tools else len(tools)), self._names.get(tool, tool)

    def name(self, row: Row) -> str:
        """A command's name on this page: as its menu has it, but the Copy submenu's Address
        is "Copy address", which out of its menu reads like a column title (Debora)."""
        if row.id.endswith(".copy_address"):
            return plain(ngettext("Copy &address", "Copy &addresses", 1))
        return row.name()

    def _fill(self) -> None:
        self.table.clear()
        groups: dict[tuple[int, int], tuple[str, list[Row]]] = {}
        for row in self.keys.rows:
            where, text = self._heading(row)
            groups.setdefault(where, (text, []))[1].append(row)
        for index, where in enumerate(sorted(groups)):
            text, rows = groups[where]
            self._add_heading(text, gap=index > 0)
            for row in sorted(rows, key=lambda r: alphabetical(self.name(r))):
                item = QTreeWidgetItem([self.name(row), ""])
                item.setData(COMMAND, ROW_ROLE, row.id)
                self.table.addTopLevelItem(item)
                self._show_key(item)
        # The key in a narrow column at the right edge, the commands taking the rest (Dante).
        fit_rows(self.table, ROWS, stretch=COMMAND, least={KEY: self._key_width()})
        self._enable()

    def _add_heading(self, text: str, *, gap: bool) -> None:
        """A heading row over its commands, in the Commands window's group look; it can't be
        picked, and the arrow keys go past it."""
        item = QTreeWidgetItem([text.upper()])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setTextAlignment(COMMAND, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        item.setData(COMMAND, GAP_ROLE, gap)
        self.table.addTopLevelItem(item)
        item.setFirstColumnSpanned(True)
        self._style_heading(item)

    def _headings(self) -> list[QTreeWidgetItem]:
        found = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [i for i in found if i is not None and not i.data(COMMAND, ROW_ROLE)]

    def _style_heading(self, item: QTreeWidgetItem) -> None:
        """The groupHeading label's font and colour, as the theme's stylesheet sets them, and
        6 px more height above every heading but the first."""
        look = QLabel()
        look.setObjectName("groupHeading")
        look.ensurePolished()
        item.setFont(COMMAND, look.font())
        item.setForeground(COMMAND, look.palette().color(QPalette.ColorRole.WindowText))
        height = QFontMetrics(look.font()).height() + 2 * HEADING_PADDING
        gap = HEADING_GAP if item.data(COMMAND, GAP_ROLE) else 0
        item.setSizeHint(COMMAND, QSize(0, height + gap))

    def _restyle(self) -> None:
        """After a theme switch: the headings in the new theme's colour."""
        for item in self._headings():
            self._style_heading(item)

    def _key_width(self) -> int:
        """KEY_WIDTH, or wider for a key with "(in the list)" after it, or for the waiting
        field's "Press the new key…" in this language, so neither is ever cut (Dante)."""
        cells = (self.table.itemWidget(i, KEY) for i in self._items())
        return max([KEY_WIDTH, self._catcher_width(),
                    *(c.sizeHint().width() + 12 for c in cells if c is not None)])  # fmt: skip

    def _catcher_width(self) -> int:
        """The waiting field's placeholder in full, with the field's own frame and padding (as
        this theme's style draws them) and the text margin Qt keeps inside them."""
        catcher = KeyCatcher()
        catcher.setParent(self.table.viewport())  # the table's stylesheet rules for its fields
        catcher.ensurePolished()
        catcher.resize(1000, catcher.sizeHint().height())
        frame = QStyleOptionFrame()
        catcher.initStyleOption(frame)
        inside = catcher.style().subElementRect(
            QStyle.SubElement.SE_LineEditContents, frame, catcher
        )
        around = catcher.width() - inside.width() + 2 * LINE_EDIT_MARGIN
        width = catcher.fontMetrics().horizontalAdvance(catcher.placeholderText()) + around
        catcher.deleteLater()
        # The field sits in the cell's text area, inside the row's padding.
        self.table.ensurePolished()
        cell = QStyleOptionViewItem()
        cell.initFrom(self.table)
        cell.rect = QRect(0, 0, 1000, 30)
        cell.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style = self.table.style()
        text = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, cell, self.table)
        return width + cell.rect.width() - text.width()

    def _items(self) -> list[QTreeWidgetItem]:
        """The commands' rows, not the headings."""
        found = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [i for i in found if i is not None and i.data(COMMAND, ROW_ROLE)]

    def _show_key(self, item: QTreeWidgetItem) -> None:
        """Its key, and after it "(in the list)" for a command whose key works only while its
        list has the focus (Connect, Open web page), whatever key that is (Debora)."""
        row = self._row(item)
        keys = self.keys.key(row)
        shown = shortcuts.shown(keys) if keys else ""
        listed = bool(keys) and any(
            a.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
            for a in row.actions
        )
        self.table.removeItemWidget(item, KEY)
        item.setText(KEY, "" if listed else shown)
        if listed:
            cell = QWidget()
            line = QHBoxLayout(cell)
            line.setContentsMargins(4, 0, 4, 0)
            line.setSpacing(4)
            line.addWidget(QLabel(shown))
            note = QLabel(_("(in the list)"))
            note.setObjectName("hint")
            line.addWidget(note)
            line.addStretch(1)
            self.table.setItemWidget(item, KEY, cell)

    def _row(self, item: QTreeWidgetItem) -> Row:
        return self.keys.row(str(item.data(COMMAND, ROW_ROLE)))

    def item_of(self, row_id: str) -> QTreeWidgetItem:
        return next(i for i in self._items() if i.data(COMMAND, ROW_ROLE) == row_id)

    def _picked(self) -> Row | None:
        items = self.table.selectedItems()
        return self._row(items[0]) if items else None

    def _enable(self) -> None:
        row = self._picked()
        self.clear.setEnabled(row is not None and bool(self.keys.key(row)))
        self.restore.setEnabled(row is not None and self.keys.key(row) != row.default)

    def _refresh(self) -> None:
        for item in self._items():
            self._show_key(item)
        self._enable()

    # ---- changing a key ----

    def change(self, item: QTreeWidgetItem) -> None:
        """Waits in the command's Key cell for its new key."""
        self._stop_catching()
        self.table.setCurrentItem(item)
        self.problem.setText(reserved_line())
        catcher = self._catcher = KeyCatcher()
        catcher.picked.connect(lambda keys: self._caught(item, keys))
        catcher.cancelled.connect(self._stop_catching)
        self.table.setItemWidget(item, KEY, catcher)
        catcher.setFocus()

    def _stop_catching(self) -> None:
        if self._catcher is None:
            return
        self._catcher = None
        for item in self._items():
            self._show_key(item)  # the catcher leaves; the key (and its note) come back
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
        self.problem.setText(reserved_line())
        self._refresh()
        self.changed.emit()

    def _move_asked(self, row: Row, other: Row, keys: str) -> bool:
        question = _("{key} is already the key for {other}. Give it to {command} instead?")
        words = question.format(
            key=shortcuts.shown(keys), other=self.name(other), command=self.name(row)
        )
        box = QMessageBox(QMessageBox.Icon.Question, _("Keyboard shortcuts"), words,
                          QMessageBox.StandardButton.Cancel, self)  # fmt: skip
        move = box.addButton(_("&Give it"), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(move)
        box.setInformativeText(_("{other} is left with no key.").format(other=self.name(other)))
        run_modal(box)
        return box.clickedButton() is move

    def _say(self, why: str) -> None:
        self.problem.setText(why)  # in the reserved keys' place, until the next key is set

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 -- Qt's name
        super().hideEvent(event)
        self.problem.setText(reserved_line())  # a reason shows only while you're on the page

    def _set_picked(self, keys: str) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, keys)

    def _restore_picked(self) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, row.default)
