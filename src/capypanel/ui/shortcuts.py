"""A command that disturbs a PC never gets a key."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

from capypanel.core.i18n import _
from capypanel.ui import menus

PREFS_KEY = "shortcuts"
EVERYWHERE = ""  # a command of the window itself (its menu bar), not of one tool
OLD_SHARED = "list."  # before 0.28's last builds, one id for a command every list tool has
RESERVED = ("F1", "Esc", "Ctrl+F", "Tab", "Shift+Tab", "Ctrl+Tab", "Ctrl+Shift+Tab", "Ctrl+Shift+W")
PAST_TERMINAL = ("app.settings", "go.")
PORTABLE = QKeySequence.SequenceFormat.PortableText
NATIVE = QKeySequence.SequenceFormat.NativeText
DEAD_KEYS_END = 0x01001293  # the last of Qt's dead-key codes


@dataclass(frozen=True)
class KeyCommand:
    id: str
    action: QAction
    where: str
    default: str = ""
    name: Callable[[], str] | None = None
    fixed: bool = False


@dataclass
class Row:
    id: str
    default: str
    places: list[str] = field(default_factory=list)
    actions: list[QAction] = field(default_factory=list)
    named: Callable[[], str] | None = None
    fixed: bool = False

    def name(self) -> str:
        if self.named is not None:
            text = self.named()
        else:
            text = menus.label(self.actions[0]) if self.actions else self.id
        return menus.plain(text)

    def meets(self, other: "Row") -> bool:
        if EVERYWHERE in self.places or EVERYWHERE in other.places:
            return True
        return bool(set(self.places) & set(other.places))


def portable(keys: QKeySequence | str) -> str:
    sequence = keys if isinstance(keys, QKeySequence) else QKeySequence(keys)
    return sequence.toString(PORTABLE)


def shown(keys: str) -> str:
    return QKeySequence(keys).toString(NATIVE).replace("Return", "Enter")


def key_tip(words: str, action: QAction) -> str:
    keys = menus.shortcut_text(action)
    return f"{words} ({keys})" if keys else words


def refused(keys: str) -> str:
    """A reserved key, or text typed without Ctrl or Alt: it would fire while typing a name."""
    sequence = QKeySequence(keys)
    if sequence.isEmpty() or sequence.count() != 1:
        return _("Press one key, with Ctrl, Alt or Shift if you like.")
    if portable(sequence) in {portable(r) for r in RESERVED}:
        return _("Kept for CapyPanel itself: F1 is for help, Esc closes, Ctrl+F searches, "
                 "Tab moves between fields and Ctrl+Shift+W closes a tab.")  # fmt: skip
    combo = sequence[0]  # type: ignore[index]  # PySide6 has [], its stubs lack it
    mods = combo.keyboardModifiers()
    typed = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    key = combo.key()
    if not mods & typed and (
        # Below Esc, Qt's key codes are the characters themselves (Ç, é); dead keys (´ ~ ^) start
        # an accented letter, so they're typed text too.
        key < Qt.Key.Key_Escape or Qt.Key.Key_Dead_Grave <= key <= DEAD_KEYS_END
    ):
        return _("{key} is for typing in names and searches: use it with Ctrl or Alt.").format(
            key=shown(keys)
        )
    return ""


class Keys:
    def __init__(self, prefs: dict[str, Any], save: Callable[[], None]) -> None:
        self._prefs, self._save = prefs, save
        self.rows: list[Row] = []
        self.past_terminal: frozenset[str] = frozenset()

    def _own(self) -> dict[str, str]:
        kept = self._prefs.get(PREFS_KEY)
        if not isinstance(kept, dict):
            kept = self._prefs[PREFS_KEY] = {}
        return kept

    def load(self, commands: Iterable[KeyCommand]) -> None:
        rows: dict[str, Row] = {}
        for command in commands:
            row = rows.setdefault(command.id, Row(command.id, portable(command.default)))
            if command.where not in row.places:
                row.places.append(command.where)
            row.actions.append(command.action)
            row.named = row.named or command.name
            row.fixed = row.fixed or command.fixed
        self.rows = list(rows.values())
        if self._split_old_shared(rows):
            self._save()
        self.apply()

    def _split_old_shared(self, rows: dict[str, Row]) -> bool:
        own = self._own()
        old = [kept for kept in own if kept.startswith(OLD_SHARED) and kept not in rows]
        for kept in old:
            name = kept.removeprefix(OLD_SHARED)
            for row in rows.values():
                if row.id == f"{row.places[0]}.{name}":
                    own.setdefault(row.id, own[kept])
            del own[kept]
        return bool(old)

    def row(self, row_id: str) -> Row:
        return next(row for row in self.rows if row.id == row_id)

    def key(self, row: Row) -> str:
        own = None if row.fixed else self._own().get(row.id)
        return own if isinstance(own, str) else row.default

    def clash(self, row: Row, keys: str) -> Row | None:
        wanted = portable(keys)
        return next(
            (o for o in self.rows if o is not row and wanted and self.key(o) == wanted
             and o.meets(row)),
            None,
        )  # fmt: skip

    def set(self, row: Row, keys: str) -> None:
        if row.fixed:
            return
        keys = portable(keys) if keys else ""
        other = self.clash(row, keys) if keys else None
        if other is not None:
            self._keep(other, "")
        self._keep(row, keys)
        self._save()
        self.apply()

    def restore(self, row: Row) -> None:
        self.set(row, row.default)

    def _keep(self, row: Row, keys: str) -> None:
        own = self._own()
        if keys == row.default:
            own.pop(row.id, None)
        else:
            own[row.id] = keys

    def apply(self) -> None:
        for row in self.rows:
            sequence = QKeySequence(self.key(row))
            for action in row.actions:
                if action.shortcut() != sequence:
                    action.setShortcut(sequence)
                    action.setText(menus.label(action))
        self.past_terminal = frozenset(
            keys
            for row in self.rows
            if row.id.startswith(PAST_TERMINAL) and (keys := self.key(row))
        )
