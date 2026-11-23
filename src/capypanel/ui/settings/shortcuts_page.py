from typing import cast

import shiboken6
from PySide6.QtCore import (
    QEvent,
    QKeyCombination,
    QMargins,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QHideEvent,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from capypanel.ui.icons import tabler_icon
from capypanel.ui.notes import hint
from capypanel.ui.settings.pages import Page, Section
from capypanel.ui.shortcuts import Keys, Row
from capypanel.ui.tables import fit_rows, grid_table, with_buttons
from capypanel.ui.themes import engine as themes

COMMAND, KEY = range(2)
ROW_ROLE = Qt.ItemDataRole.UserRole
KEY_WIDTH = 120
LINE_EDIT_MARGIN = 2  # Qt keeps this much inside a field's contents on each side
HEADING_GAP = 20
HEADING_PADDING = 8
GAP_ROLE = Qt.ItemDataRole.UserRole + 1
FIXED_ROLE = Qt.ItemDataRole.UserRole + 2
TERMINAL_TOOL = "ssh"
LINE_PADDING = 6
MODIFIERS = (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
             Qt.Key.Key_AltGr, Qt.Key.Key_unknown)  # fmt: skip
HELD = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)  # fmt: skip


def lead(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("lead")
    label.setWordWrap(True)
    font = label.font()
    font.setPointSizeF(font.pointSizeF() + 1)
    label.setFont(font)
    return label


ORDER = (
    "app.settings", "app.exit",
    "go.home", "go.hosts", "go.printers", "go.profiles", "go.ssh", "app.show_toolbar",
    "app.show_status_bar",
    "app.show_guide", "app.show_all_guides", "app.help_screen", "app.documentation",
    "app.report_problem",
    "app.check_updates", "app.about",
    "hosts.connect_host", "hosts.manual_connect", "hosts.connection_profiles",
    "hosts.saved_credentials", "hosts.refresh_shown", "hosts.add_host", "hosts.add_group",
    "hosts.manage_groups", "hosts.import_hosts", "hosts.export_hosts",
    "hosts.copy_address", "hosts.edit", "hosts.remove",
    "hosts.show_groups", "hosts.show_tags", "hosts.show_details", "hosts.customize_details",
    "hosts.show_domains", "hosts.new_list", "hosts.open_list",
    "command.all-checks", "command.status", "command.users", "command.facts", "command.programs",
    "command.c-share", "command.user-folder", "command.startup", "command.path",
    "command.computer-management", "command.event-viewer", "command.services",
    "command.message", "command.drives", "command.printers",
    "printers.open_web_page", "printers.refresh_shown", "printers.add_printer",
    "printers.add_group", "printers.manage_groups", "printers.import_printers",
    "printers.export_printers",
    "printers.refresh_selected", "printers.copy_address", "printers.edit", "printers.remove",
    "printers.show_groups", "printers.show_tags", "printers.show_details",
    "printers.customize_details", "printers.new_list", "printers.open_list",
    "ssh.connect_host", "ssh.connect_window", "ssh.refresh_shown", "ssh.add_host",
    "ssh.add_group", "ssh.manage_groups", "ssh.import_hosts",
    "ssh.refresh_selected", "ssh.copy_address", "ssh.edit", "ssh.remove", "ssh.show_groups",
    "ssh.show_tags", "ssh.show_details", "ssh.customize_details", "ssh.new_list", "ssh.open_list",
)  # fmt: skip


def reserved_line() -> str:
    return _(
        "F1, Esc, Ctrl+F, Tab and Ctrl+Shift+W are kept for CapyPanel itself. In an SSH "
        "terminal, all but Ctrl+Shift+W go to the server."
    )


def terminal_line() -> str:
    return _(
        "Inside a terminal, every key goes to the server except the ones below and the keys "
        "that change tools or open Settings."
    )


def terminal_keys() -> list[tuple[str, str]]:
    return [
        (plain(_("&Copy")), "Ctrl+Shift+C"),
        (_("Copy, with text selected"), "Ctrl+C"),
        (plain(_("&Paste")), "Ctrl+Shift+V"),
        (_("Find"), "Ctrl+Shift+F"),
        (_("Bigger text"), "Ctrl+="),
        (_("Smaller text"), "Ctrl+-"),
        (_("Next tab"), "Ctrl+Tab"),
        (_("Previous tab"), "Ctrl+Shift+Tab"),
        (plain(_("Close &tab")), "Ctrl+Shift+W"),
    ]


def top_menu(action: QAction) -> tuple[int, QMenu] | None:
    """By Qt's class names, not isinstance: any QMenu subclass counts."""
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
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def waiting_text() -> str:
    return _("Press the new key…")


def refused_text() -> str:
    return _("Key not allowed")


def place_in_order(row: Row) -> int:
    return ORDER.index(row.id) if row.id in ORDER else len(ORDER)


def caps_baseline(inside: QRect, caps: QRect) -> int:
    return inside.top() + (inside.height() - caps.height()) // 2 - caps.top()


class KeyCatcher(QLineEdit):
    picked = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText(waiting_text())
        self._done = False
        self._room: QMargins | None = None

    def refuse(self) -> None:
        self._done = False
        if self._room is None:
            words = self.words_rect()
            right, bottom = self.width() - 1 - words.right(), self.height() - 1 - words.bottom()
            self._room = QMargins(words.left(), words.top(), right, bottom)
        self.setProperty("refused", True)
        self.setPlaceholderText(refused_text())
        self.style().unpolish(self)
        self.style().polish(self)  # the red edge; polishing resets the palette, so it goes first
        palette = self.palette()
        red = QColor(themes.status_colors()["stopped"])
        palette.setColor(QPalette.ColorRole.PlaceholderText, red)
        self.setPalette(palette)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002, N802 -- Qt's names
        return False  # Tab is a key pressed here, not a move to the next control

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()  # every key is its answer, F1 too: refused here, not Settings' help
            return True
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 -- Qt's name
        """The words drawn with their capitals in the middle: Qt centres them low."""
        if self.text():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        frame = QStyleOptionFrame()
        self.initStyleOption(frame)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_PanelLineEdit, frame, painter, self)
        room, metrics = self.words_rect(), self.fontMetrics()
        elide = Qt.TextElideMode.ElideRight
        words = metrics.elidedText(self.placeholderText(), elide, room.width())
        baseline = caps_baseline(room, metrics.tightBoundingRect("H"))
        painter.setClipRect(room.adjusted(-LINE_EDIT_MARGIN, 0, LINE_EDIT_MARGIN, 0))
        painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.drawText(QPoint(room.left(), baseline), words)

    def words_rect(self) -> QRect:
        if self._room is not None:
            return self.rect().marginsRemoved(self._room)
        frame = QStyleOptionFrame()
        self.initStyleOption(frame)
        inside = self.style().subElementRect(QStyle.SubElement.SE_LineEditContents, frame, self)
        return inside.adjusted(LINE_EDIT_MARGIN, 0, -LINE_EDIT_MARGIN, 0)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in MODIFIERS:
            return
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
    HELP_PLACE = "settings-capypanel-keyboard-shortcuts"

    def __init__(self, keys: Keys, place_names: dict[str, str]) -> None:
        super().__init__(_("Keyboard shortcuts"))
        self.keys = keys
        self._names = place_names
        self.section = Section(_("Command keys"))
        self.section.heading.hide()
        self.section.inner.setObjectName("")
        self.section.inner.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.section.content.setContentsMargins(0, 0, 0, 0)
        column = self.section.layout()
        if column is not None:
            column.setSpacing(0)
        self.about = lead(
            _("Double-click a command, or press Enter on it, then press its new key.")
        )
        self.table = grid_table([_("Command"), _("Key")])
        self.table.itemActivated.connect(lambda item, _c: self.change(item))
        self.table.itemSelectionChanged.connect(self._enable)
        self.table.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self._show_catching())
        self.clear = QPushButton(_("C&lear"))
        self.restore = QPushButton(_("&Restore default"))
        self.clear.clicked.connect(lambda: self._set_picked(""))
        self.restore.clicked.connect(self._restore_picked)
        self.problem = hint(reserved_line())
        self.problem_icon = QLabel()
        self.problem_icon.hide()
        problem_line = QHBoxLayout()
        problem_line.setContentsMargins(0, 0, 0, 0)
        problem_line.setSpacing(spacing.CONTROLS // 2)
        problem_line.addWidget(self.problem_icon, 0, Qt.AlignmentFlag.AlignTop)
        problem_line.addWidget(self.problem, 1)
        self.section.content.addWidget(self.about)
        self.section.content.addSpacing(spacing.CONTROLS - self.section.content.spacing())
        self.section.content.addWidget(with_buttons(self.table, [self.clear, self.restore]), 1)
        self.section.content.addLayout(problem_line)
        self.body.addWidget(self.section, 1)
        self._catcher: KeyCatcher | None = None
        self._catching: QTreeWidgetItem | None = None
        self._terminal_item: QTreeWidgetItem | None = None
        self.terminal_words = hint(terminal_line())
        self.table.viewport().installEventFilter(self)
        self._fill()
        themes.switches().switched.connect(self._restyle)

    def _heading(self, row: Row) -> tuple[tuple[int, int], str]:
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
        if row.id.endswith(".copy_address"):
            return plain(ngettext("Copy &address", "Copy &addresses", 1))
        return row.name()

    def _fill(self) -> None:
        self.table.clear()
        groups: dict[tuple[int, int], tuple[str, list[Row]]] = {}
        for row in self.keys.rows:
            where, text = self._heading(row)
            groups.setdefault(where, (text, []))[1].append(row)
        self._terminal_item = None
        for index, where in enumerate(sorted(groups)):
            text, rows = groups[where]
            self._add_heading(text, gap=index > 0)
            for row in sorted(rows, key=place_in_order):
                item = QTreeWidgetItem([self.name(row), ""])
                item.setData(COMMAND, ROW_ROLE, row.id)
                if row.fixed:
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    item.setData(COMMAND, FIXED_ROLE, True)
                    tip = _("F1 is kept for help and can't be changed.")
                    item.setToolTip(COMMAND, tip)
                    item.setToolTip(KEY, tip)
                self.table.addTopLevelItem(item)
                self._show_key(item)
            if any(TERMINAL_TOOL in row.places for row in rows):
                self._add_terminal_keys()
        fit_rows(self.table, 0, stretch=COMMAND, least={KEY: self._key_width()})
        self._enable()

    def _add_heading(self, text: str, *, gap: bool) -> None:
        item = QTreeWidgetItem([text])
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        down = Qt.AlignmentFlag.AlignBottom if gap else Qt.AlignmentFlag.AlignVCenter
        item.setTextAlignment(COMMAND, Qt.AlignmentFlag.AlignLeft | down)
        item.setData(COMMAND, GAP_ROLE, gap)
        self.table.addTopLevelItem(item)
        item.setFirstColumnSpanned(True)
        self._style_heading(item)

    def _add_terminal_keys(self) -> None:
        self._add_heading(_("SSH terminal"), gap=True)
        line = QTreeWidgetItem()
        line.setFlags(Qt.ItemFlag.NoItemFlags)
        line.setData(COMMAND, FIXED_ROLE, True)
        self.table.addTopLevelItem(line)
        line.setFirstColumnSpanned(True)
        self.terminal_words = hint(terminal_line())
        self.terminal_words.setContentsMargins(LINE_PADDING, 0, LINE_PADDING, 0)
        self.table.setItemWidget(line, COMMAND, self.terminal_words)
        self._terminal_item = line
        tip = _("The terminal's own keys can't be changed.")
        for name, keys in terminal_keys():
            item = QTreeWidgetItem([name, shortcuts.shown(keys)])
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setData(COMMAND, FIXED_ROLE, True)
            item.setToolTip(COMMAND, tip)
            item.setToolTip(KEY, tip)
            self.table.addTopLevelItem(item)
        self._fit_terminal_line()

    def _fit_terminal_line(self) -> None:
        if self._terminal_item is None:
            return
        width = max(self.table.viewport().width(), 200)
        height = self.terminal_words.heightForWidth(width)
        self._terminal_item.setSizeHint(COMMAND, QSize(0, height + 2 * LINE_PADDING))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 -- Qt's name
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_terminal_line()
        return super().eventFilter(watched, event)

    def _headings(self) -> list[QTreeWidgetItem]:
        found = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [
            i
            for i in found
            if i is not None and not i.data(COMMAND, ROW_ROLE) and not i.data(COMMAND, FIXED_ROLE)
        ]

    def _style_heading(self, item: QTreeWidgetItem) -> None:
        look = QLabel()
        look.setObjectName("sectionTitle")
        look.ensurePolished()
        font = self.table.font()
        font.setPointSizeF(font.pointSizeF() + 1)
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(COMMAND, font)
        item.setForeground(COMMAND, look.palette().color(QPalette.ColorRole.WindowText))
        height = QFontMetrics(font).height() + 2 * HEADING_PADDING
        gap = HEADING_GAP if item.data(COMMAND, GAP_ROLE) else 0
        item.setSizeHint(COMMAND, QSize(0, height + gap))

    def _restyle(self) -> None:
        for item in self._headings():
            self._style_heading(item)

    def _key_width(self) -> int:
        cells = (self.table.itemWidget(i, KEY) for i in self._items())
        return max([KEY_WIDTH, self._catcher_width(),
                    *(c.sizeHint().width() + 12 for c in cells if c is not None)])  # fmt: skip

    def _catcher_width(self) -> int:
        catcher = KeyCatcher()
        catcher.setParent(self.table.viewport())
        catcher.ensurePolished()
        catcher.resize(1000, catcher.sizeHint().height())
        frame = QStyleOptionFrame()
        catcher.initStyleOption(frame)
        inside = catcher.style().subElementRect(
            QStyle.SubElement.SE_LineEditContents, frame, catcher
        )
        around = catcher.width() - inside.width() + 2 * LINE_EDIT_MARGIN
        words = max(
            catcher.fontMetrics().horizontalAdvance(t) for t in (waiting_text(), refused_text())
        )
        width = words + around
        # Out at once: deleteLater waits for the loop it was called from, and Settings runs its own.
        catcher.setParent(None)
        shiboken6.delete(catcher)
        self.table.ensurePolished()
        cell = QStyleOptionViewItem()
        cell.initFrom(self.table)
        cell.rect = QRect(0, 0, 1000, 30)
        cell.features = QStyleOptionViewItem.ViewItemFeature.HasDisplay
        style = self.table.style()
        text = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, cell, self.table)
        return width + cell.rect.width() - text.width()

    def _items(self) -> list[QTreeWidgetItem]:
        found = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [i for i in found if i is not None and i.data(COMMAND, ROW_ROLE)]

    def _show_key(self, item: QTreeWidgetItem) -> None:
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

    def change(self, item: QTreeWidgetItem) -> None:
        """A heading has none: Qt's tree still activates a disabled row on a double-click."""
        if not item.data(COMMAND, ROW_ROLE) or item.data(COMMAND, FIXED_ROLE):
            return
        self._stop_catching()
        self.table.setCurrentItem(item)
        self._show_problem("")
        catcher = self._catcher = KeyCatcher()
        self._catching = item
        catcher.picked.connect(lambda keys: self._caught(item, keys))
        catcher.cancelled.connect(self._stop_catching)
        self.table.setItemWidget(item, KEY, catcher)
        catcher.setFocus()

    def _stop_catching(self) -> None:
        if self._catcher is None:
            return
        self._catcher = None
        if self._catching is not None:
            self.table.removeItemWidget(self._catching, KEY)
            self._catching = None
        self._show_problem("")
        for item in self._items():
            self._show_key(item)
        self.table.setFocus()

    def _show_catching(self) -> None:
        if self._catching is None:
            return
        # By the row's place, not scrollToItem's own check: scrolling a row at a time, Qt
        # counts the rows that fit at the list's end, and the headings are taller.
        row, view = self.table.visualItemRect(self._catching), self.table.viewport().rect()
        if row.bottom() > view.bottom():
            self.table.scrollToItem(self._catching, QAbstractItemView.ScrollHint.PositionAtBottom)
        elif row.top() < view.top():
            self.table.scrollToItem(self._catching, QAbstractItemView.ScrollHint.PositionAtTop)

    def _caught(self, item: QTreeWidgetItem, keys: str) -> None:
        why = shortcuts.refused(keys)
        if why and self._catcher is not None:
            self._catcher.refuse()
            self._show_problem(why)
            return
        self._stop_catching()
        self._give(self._row(item), keys)

    def _give(self, row: Row, keys: str) -> None:
        other = self.keys.clash(row, keys) if keys else None
        if other is not None and not self._move_asked(row, other, keys):
            return
        self.keys.set(row, keys)
        self._show_problem("")
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

    def _show_problem(self, why: str) -> None:
        self.problem.setText(why or reserved_line())
        self.problem.setObjectName("refusal" if why else "hint")
        self.problem.style().unpolish(self.problem)
        self.problem.style().polish(self.problem)
        if why:
            red = QColor(themes.status_colors()["stopped"])
            side = self.problem.fontMetrics().height()
            self.problem_icon.setPixmap(tabler_icon("circle-x", red, side).pixmap(side, side))
        self.problem_icon.setVisible(bool(why))

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802 -- Qt's name
        super().hideEvent(event)
        self._show_problem("")

    def _set_picked(self, keys: str) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, keys)

    def _restore_picked(self) -> None:
        row = self._picked()
        if row is not None:
            self._give(row, row.default)
