"""Keyboard shortcuts: which key runs which command, as each person sets them in Settings ›
CapyPanel › Keyboard shortcuts. Every command a key can run is a row; today's keys are its
defaults, and a person's changes are kept in their settings file (only what differs). A command
Hosts and Printers share (Edit, Refresh…) is one row and one key for both. Restart, Shut down and
the other Power commands, and every command that disturbs whoever uses a PC, never get a key."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

from capypanel.core.i18n import _
from capypanel.ui import menus

PREFS_KEY = "shortcuts"  # this person's: {command id: "Ctrl+E", or "" for no key}
EVERYWHERE = ""  # a command of the window itself, not of one tool
# Keys no command can take: F1 is help's (0.30), Esc closes and ends a search, Ctrl+F searches
# every list, and the Tab keys move around a window and between tabs.
RESERVED = ("F1", "Esc", "Ctrl+F", "Tab", "Shift+Tab", "Ctrl+Tab", "Ctrl+Shift+Tab")
PORTABLE = QKeySequence.SequenceFormat.PortableText
NATIVE = QKeySequence.SequenceFormat.NativeText


@dataclass(frozen=True)
class KeyCommand:
    """A command a key can run, as a tool or the window offers it: `id` names it in the
    settings file ("list.edit" is the same command in every list tool), `where` is the tool's
    id or EVERYWHERE, and `default` is today's key in portable text ("Ctrl+E"), or ""."""

    id: str
    action: QAction
    where: str
    default: str = ""


@dataclass
class Row:
    """One command on the Keyboard shortcuts page: one or more tools' actions for it."""

    id: str
    default: str
    places: list[str] = field(default_factory=list)  # tool ids, or EVERYWHERE
    actions: list[QAction] = field(default_factory=list)

    def name(self) -> str:
        """The command's name as its menus have it, without the access key's &."""
        text = menus.label(self.actions[0]) if self.actions else self.id
        return text.replace("&&", "\0").replace("&", "").replace("\0", "&")

    def meets(self, other: "Row") -> bool:
        """Whether a key could reach both at once: the window's commands meet every tool's."""
        if EVERYWHERE in self.places or EVERYWHERE in other.places:
            return True
        return bool(set(self.places) & set(other.places))


def portable(keys: QKeySequence | str) -> str:
    """A key as the settings file keeps it: "Ctrl+Shift+O", the same in every language."""
    sequence = keys if isinstance(keys, QKeySequence) else QKeySequence(keys)
    return sequence.toString(PORTABLE)


def shown(keys: str) -> str:
    """A key as a person reads it, Windows' way: "Ctrl+Shift+O", "Enter", "Del"."""
    return QKeySequence(keys).toString(NATIVE).replace("Return", "Enter")


def refused(keys: str) -> str:
    """Why `keys` can't be a shortcut, or "": a reserved key, or one a person types as text
    (a letter, a digit, a space) with no Ctrl or Alt, which would fire while typing a name."""
    sequence = QKeySequence(keys)
    if sequence.isEmpty() or sequence.count() != 1:
        return _("Press one key, with Ctrl, Alt or Shift if you like.")
    if portable(sequence) in {portable(r) for r in RESERVED}:
        return _("{key} is kept for CapyPanel itself: F1 for help, Esc to close, Ctrl+F to "
                 "search, Tab to move around.").format(key=shown(keys))  # fmt: skip
    combo = sequence[0]  # type: ignore[index]  # PySide6 has [], its stubs lack it
    mods = combo.keyboardModifiers()
    typed = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    key = combo.key()
    if not mods & typed and (
        Qt.Key.Key_Space <= key <= Qt.Key.Key_AsciiTilde  # letters, digits, punctuation
    ):
        return _("{key} is typed as text in names and searches: add Ctrl or Alt.").format(
            key=shown(keys)
        )
    return ""


class Keys:
    """The keys this person gave the commands, and the rows of the Keyboard shortcuts page.
    `save` writes the settings file; every change is applied to the actions at once."""

    def __init__(self, prefs: dict[str, Any], save: Callable[[], None]) -> None:
        self._prefs, self._save = prefs, save
        self.rows: list[Row] = []

    def _own(self) -> dict[str, str]:
        kept = self._prefs.get(PREFS_KEY)
        if not isinstance(kept, dict):
            kept = self._prefs[PREFS_KEY] = {}
        return kept

    def load(self, commands: Iterable[KeyCommand]) -> None:
        """The commands the window and its tools offer, in menu order: one row per id, then
        each gets its key."""
        rows: dict[str, Row] = {}
        for command in commands:
            row = rows.setdefault(command.id, Row(command.id, portable(command.default)))
            if command.where not in row.places:
                row.places.append(command.where)
            row.actions.append(command.action)
        self.rows = list(rows.values())
        self.apply()

    def row(self, row_id: str) -> Row:
        return next(row for row in self.rows if row.id == row_id)

    def key(self, row: Row) -> str:
        """Its key now, in portable text, or ""."""
        own = self._own().get(row.id)
        return own if isinstance(own, str) else row.default

    def clash(self, row: Row, keys: str) -> Row | None:
        """The other command `keys` already runs where `row` runs, if one does."""
        wanted = portable(keys)
        return next(
            (o for o in self.rows if o is not row and wanted and self.key(o) == wanted
             and o.meets(row)),
            None,
        )  # fmt: skip

    def set(self, row: Row, keys: str) -> None:
        """Gives `row` the key `keys` ("" for none); a command that had it loses it."""
        keys = portable(keys) if keys else ""
        other = self.clash(row, keys) if keys else None
        if other is not None:
            self._keep(other, "")
        self._keep(row, keys)
        self._save()
        self.apply()

    def restore(self, row: Row) -> None:
        """Back to today's key; a command that has that key now loses it."""
        self.set(row, row.default)

    def _keep(self, row: Row, keys: str) -> None:
        own = self._own()
        if keys == row.default:
            own.pop(row.id, None)
        else:
            own[row.id] = keys

    def apply(self) -> None:
        """Every action gets its key. A menu works out the room for its keys when it opens."""
        for row in self.rows:
            sequence = QKeySequence(self.key(row))
            for action in row.actions:
                if action.shortcut() != sequence:
                    action.setShortcut(sequence)
                    action.setText(menus.label(action))  # its old key's room goes


def places_text(places: Sequence[str], names: dict[str, str]) -> str:
    """Where a command runs, in words: "Hosts, Printers", or "Everywhere"."""
    if EVERYWHERE in places:
        return _("Everywhere")
    return ", ".join(names.get(p, p) for p in places)
