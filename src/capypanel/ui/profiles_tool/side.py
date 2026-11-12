"""The User profiles tool's right panel: cards from top to bottom, the same on every tab, and
never a scrollbar. Progress first, at one fixed height, so nothing under it jumps between tabs.
Then the tab's own card: the hosts on show (the Hosts tab), or a host's ticked profiles, or its
delete run. Then, on a host's tab, the Delete button at the foot, always in sight. A profile's
details open in a window of their own. A card shows what fits and ends with "and 3 more…"."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPalette, QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _, ngettext, pgettext
from capypanel.core.remote.user_profiles import Profile
from capypanel.ui.dialogs import quiet_default
from capypanel.ui.hosts_tool.command_windows import risky_button
from capypanel.ui.icons import dot_icon, tabler_icon
from capypanel.ui.list_workspace.details import CopyValue, DetailsPanel
from capypanel.ui.profiles_tool import rows
from capypanel.ui.profiles_tool.panels import AMBER, ProfileDetails, Shown, card

FOOT = 36  # px: the foot button's height
MARK = 14  # px: a line's icon
TAB_LINES = 4  # Progress shows this many tabs
TICKED_LINES = 6  # a host's card shows this many profiles


@dataclass(frozen=True)
class Entry:
    """One line of a card: a mark, a name, and words on the right."""

    key: str  # what a click on it says
    name: str
    words: str = ""
    icon: str = ""
    color: str = ""  # the icon's
    words_color: str = ""  # "" for grey
    tip: str = ""
    muted: bool = False  # the name in grey too: it waits


@dataclass(frozen=True)
class HostFacts:
    """The picked host, on the Hosts tab."""

    name: str
    dot: str  # its status colour; "" for none
    status: str  # "Offline · checked by Hosts at 10:30"
    address: str
    group: str
    scanned: str  # "10:41", or "—"
    account: str  # who signs in, or "—"


@dataclass(frozen=True)
class GroupFacts:
    """The hosts on show, when no single host is picked: how many answer by Hosts' last check,
    the check under way, and what the scans found so far."""

    name: str  # the group's name, or "All hosts"
    status: str  # "Refreshing status: 12 of 31…", or when Hosts last checked
    checked: str  # "28 online · 3 offline"
    unchecked: int
    scanned: str  # "4 of 31"
    deletable: str  # "66", or "—" before any scan
    empty: bool = False  # no host on show


def caption(text: str = "") -> QLabel:
    """A card's small heading, in capitals: what the card is."""
    label = QLabel(text)
    label.setObjectName("hint")
    font = QFont(label.font())
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 0.85)
    label.setFont(font)
    return label


def big(text: str = "") -> QLabel:
    """A card's main line."""
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.25)
    label.setFont(font)
    return label


def _thin_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setObjectName("thin")
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    return bar


class Name(QWidget):
    """A name on a line: it takes the room the line leaves and ends in "…" when it can't fit,
    the whole name in its tooltip, so the words beside it always show."""

    def __init__(self) -> None:
        super().__init__()
        self._text = ""
        self._muted = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def show_text(self, text: str, muted: bool = False) -> None:
        self._text, self._muted = text, muted
        self.updateGeometry()
        self._tip()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance("…") * 3, metrics.height())

    def shown_text(self) -> str:
        return self.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._tip()

    def _tip(self) -> None:
        self.setToolTip(self._text if self.shown_text() != self._text else "")

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        role = QPalette.ColorRole.PlaceholderText if self._muted else QPalette.ColorRole.Text
        painter.setPen(self.palette().color(role))
        align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(self.rect(), align, self.shown_text())
        painter.end()


class Line(QWidget):
    """One entry: its mark, its name, and its words on the right, which are never cut (the name
    gives way). A click says its key."""

    clicked = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._key = ""
        self._color = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon = QLabel()
        self.icon.setFixedWidth(MARK)
        self.name = Name()
        self.words = QLabel()
        self.words.setObjectName("hint")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 1, 0, 1)
        row.setSpacing(6)
        row.addWidget(self.icon)
        row.addWidget(self.name, 1)
        row.addWidget(self.words)

    def show_entry(self, entry: Entry) -> None:
        self._key = entry.key
        if entry.icon:
            icon = tabler_icon(entry.icon, QColor(entry.color), MARK)
            self.icon.setPixmap(icon.pixmap(MARK, MARK))
        else:
            self.icon.clear()
        self.name.show_text(entry.name, entry.muted)
        self.words.setText(entry.words)
        if entry.words_color != self._color:  # a stylesheet is slow to set: only when it differs
            self._color = entry.words_color
            self.words.setStyleSheet(f"color: {self._color};" if self._color else "")
        self.setToolTip(entry.tip)

    def key(self) -> str:
        return self._key

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._key:
            self.clicked.emit(self._key)
        super().mousePressEvent(event)


class Lines(QWidget):
    """A fixed number of lines, so a card never needs a scrollbar. More entries than lines: the
    rest is a count in grey. With `own_more` that count has a line of its own under the others;
    without, it takes the last line's place, and the widget's height never changes."""

    clicked = Signal(str)

    def __init__(self, slots: int, own_more: bool) -> None:
        super().__init__()
        self._own_more = own_more
        self.slots = [Line() for _slot in range(slots)]
        self.more = QLabel()
        self.more.setObjectName("hint")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        # One height for every line, whatever it holds, so a card's height never depends on
        # which lines have a mark.
        self._line = max(self.fontMetrics().height(), MARK) + 2
        for line in self.slots:
            line.setFixedHeight(self._line)
            line.clicked.connect(self.clicked)
            column.addWidget(line)
        self.more.setFixedHeight(self._line)
        column.addWidget(self.more)
        self.show_entries((), lambda _n: "")

    def show_entries(self, entries: Sequence[Entry], more: Callable[[int], str]) -> None:
        """`more`: the words for the entries that don't fit, given how many."""
        room = len(self.slots)
        if len(entries) > room and not self._own_more:
            room -= 1
        shown = entries[:room]
        for index, line in enumerate(self.slots):
            line.setVisible(index < len(shown))
            if index < len(shown):
                line.show_entry(shown[index])
        left = len(entries) - len(shown)
        self.more.setText(more(left) if left else "")
        self.more.setVisible(bool(left))

    def shown(self) -> list[tuple[str, str]]:
        """Each line on show, as (name, words), then the count of the rest (for tests)."""
        found = [(s.name.text(), s.words.text()) for s in self.slots if not s.isHidden()]
        return found + ([(self.more.text(), "")] if not self.more.isHidden() else [])

    def full_height(self) -> int:
        """Its height with every line on show."""
        return len(self.slots) * self._line + (len(self.slots) - 1) * 2


def _column(frame: QFrame) -> QVBoxLayout:
    column = QVBoxLayout(frame)
    column.setContentsMargins(14, 12, 14, 12)  # as Details' own page
    column.setSpacing(3)
    return column


class ProgressCard(QFrame):
    """Progress, the same card on every tab: how many hosts have a tab and how many are done,
    then a line per tab, the working ones first. A click on a line goes to its tab. Its height
    is fixed, whatever it shows."""

    go_to = Signal(str)  # a host's key: its tab comes to the front

    def __init__(self) -> None:
        super().__init__()
        _as_card(self)
        self.caption = caption()
        self.title = big()
        self.summary = DetailsPanel.muted("")
        self.bar = _thin_bar()
        self.lines = Lines(TAB_LINES, own_more=False)
        self.lines.clicked.connect(self.go_to)
        column = _column(self)
        column.addWidget(self.caption)
        column.addWidget(self.title)
        column.addWidget(self.summary)
        column.addSpacing(4)
        column.addWidget(self.bar)
        column.addSpacing(6)
        column.addWidget(self.lines)
        column.addStretch(1)
        self.show_tabs((), 0)

    def show_tabs(self, entries: Sequence[Entry], done: int) -> None:
        """`entries`: every host with a tab, in the order to show. `done`: how many ended."""
        total = len(entries)
        self.caption.setText(_("PROGRESS"))
        if total:
            self.title.setText(
                ngettext("{n} host in tabs", "{n} hosts in tabs", total).format(n=total)
            )
            working = total - done
            self.summary.setText(
                ngettext("{n} working", "{n} working", working).format(n=working)
                + " · "
                + ngettext("{n} done", "{n} done", done).format(n=done)
            )
        else:
            self.title.setText(_("No host in tabs"))
            self.summary.setText(_("Double-click a host to open it, or pick hosts and click "
                                   "Scan to scan them here."))  # fmt: skip
        self.bar.setVisible(bool(total))
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.lines.show_entries(entries, lambda n: _("and {n} more…").format(n=n))
        self.setFixedHeight(self._height())

    def _height(self) -> int:
        """Room for the heading, one grey line, the bar and every line: about 190 px."""
        one_line = self.summary.fontMetrics().height()
        parts = (self.caption.sizeHint().height(), self.title.sizeHint().height(), one_line,
                 self.bar.height(), self.lines.full_height())  # fmt: skip
        return 12 + sum(parts) + 3 * (len(parts) + 1) + 4 + 6 + 12


def _as_card(frame: QFrame) -> None:
    template = card()
    frame.setObjectName(template.objectName())
    frame.setFrameShape(template.frameShape())
    frame.setBackgroundRole(template.backgroundRole())
    frame.setAutoFillBackground(True)
    template.deleteLater()


def _rule() -> QFrame:
    rule = QFrame()
    rule.setObjectName("detailsRule")
    return rule


class HostCard(QFrame):
    """The Hosts tab's card: the host picked, or the hosts on show as a whole; under it, the
    tabs that have profiles ticked and waiting. A click on a value copies it."""

    go_to = Signal(str)
    copied = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        _as_card(self)
        self.heading = caption()
        self.dot = QLabel()
        self.name = CopyValue("")
        self.name.setFont(big().font())
        # Its padding and the label's own edge would start the name further in than the lines
        # around it.
        self.name.setStyleSheet("QLabel#copyValue { padding-left: 0px; margin-left: -4px; }")
        self.name.copied.connect(self.copied)
        self.status = DetailsPanel.muted("")
        top = QHBoxLayout()
        top.setSpacing(10)  # the name's own edge takes 4 of them back
        top.addWidget(self.dot)
        top.addWidget(self.name, 1)
        self._labels = [QLabel() for _n in range(4)]
        self._values = [CopyValue("") for _n in range(4)]
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 92)
        for index, (label, value) in enumerate(zip(self._labels, self._values, strict=True)):
            label.setObjectName("hint")
            value.copied.connect(self.copied)
            grid.addWidget(label, index, 0)
            grid.addWidget(value, index, 1)
        self._ticked_title = QLabel()
        self._ticked_title.setObjectName("detailsSection")
        self.ticked = Lines(TAB_LINES, own_more=False)
        self.ticked.clicked.connect(self.go_to)
        self._ticked_hint = DetailsPanel.muted("")
        self._section = QWidget()
        section = QVBoxLayout(self._section)
        section.setContentsMargins(0, 10, 0, 0)
        section.setSpacing(3)
        section.addWidget(_rule())
        section.addSpacing(6)
        section.addWidget(self._ticked_title)
        section.addWidget(self.ticked)
        section.addSpacing(4)
        section.addWidget(self._ticked_hint)
        column = _column(self)
        column.addWidget(self.heading)
        column.addLayout(top)
        column.addWidget(self.status)
        column.addSpacing(4)
        column.addLayout(grid)
        column.addWidget(self._section)
        column.addStretch(1)
        self.show_ticked(())

    def show_group(self, facts: GroupFacts) -> None:
        """No single host picked: the hosts on show as a whole. With none on show (a search
        that found nothing), it says so and has no rows."""
        self.heading.setText(_("HOSTS SHOWN"))
        self.name.set_text(facts.name)
        self.dot.hide()
        self.status.setText(facts.status)
        if facts.empty:
            for widget in (*self._labels, *self._values):
                widget.hide()
            return
        self._show(
            (
                (_("Status"), facts.checked),
                (pgettext("hosts", "Not checked"), str(facts.unchecked)),
                (_("Scanned"), facts.scanned),
                (_("Can be deleted"), facts.deletable),
            )
        )

    def show_host(self, facts: HostFacts) -> None:
        self.heading.setText(_("SELECTED HOST"))
        self.name.set_text(facts.name)
        self.dot.setVisible(bool(facts.dot))
        if facts.dot:
            self.dot.setPixmap(dot_icon(facts.dot, 12).pixmap(12, 12))
        self.status.setText(facts.status)
        self._show(
            (
                (_("Address"), facts.address),
                (_("Group"), facts.group),
                (_("Scanned at"), facts.scanned),
                (_("As"), facts.account),
            )
        )

    def show_ticked(self, entries: Sequence[Entry]) -> None:
        """The tabs with profiles ticked, or deleting them; the section shows only with some."""
        self._ticked_title.setText(_("Ticked in tabs"))
        self._ticked_hint.setText(_("A click goes to the host's tab."))
        self.ticked.show_entries(entries, lambda n: _("and {n} more…").format(n=n))
        self._section.setVisible(bool(entries))

    def values(self) -> dict[str, str]:
        """The rows on show, label to value (for tests)."""
        pairs = zip(self._labels, self._values, strict=True)
        return {a.text(): b.copy_text() for a, b in pairs if not a.isHidden()}

    def _show(self, pairs: Sequence[tuple[str, str]]) -> None:
        for (label, value), name, shown in zip(pairs, self._labels, self._values, strict=True):
            name.setText(label)
            shown.set_text(value)
            name.show()
            shown.show()


class TickedCard(QFrame):
    """A host's card: the profiles ticked to delete, their count and size in amber, one line
    each. A click on a line shows that profile in the table."""

    picked = Signal(str)  # a profile's ident

    def __init__(self) -> None:
        super().__init__()
        _as_card(self)
        self.caption = caption()
        self.title = big()
        self.lines = Lines(TICKED_LINES, own_more=True)
        self.lines.clicked.connect(self.picked)
        self.hint = DetailsPanel.muted("")
        column = _column(self)
        column.addWidget(self.caption)
        column.addWidget(self.title)
        column.addSpacing(4)
        column.addWidget(self.lines)
        column.addSpacing(4)
        column.addWidget(self.hint)
        column.addStretch(1)
        self.show_ticked((), {}, scanned=False)

    def show_ticked(self, ticked: Sequence[Profile], sizes: dict[str, int], scanned: bool) -> None:
        """`sizes`: bytes of the rows counted. `scanned`: the host has a list to tick in."""
        self.caption.setText(_("TICKED TO DELETE"))
        entries = [
            Entry(p.ident, rows.user_text(p),
                  rows.size_text(sizes[p.ident]) if p.ident in sizes else "", "trash", AMBER)
            for p in ticked
        ]  # fmt: skip
        self.lines.show_entries(
            entries,
            lambda n: ngettext("and {n} more profile", "and {n} more profiles", n).format(n=n),
        )
        self.lines.setVisible(bool(entries))
        if not ticked:
            self.title.setText(_("No profile ticked"))
            self.title.setStyleSheet("")
            self.hint.setText(
                _("Tick in the table: the box, Space or a double-click on the row.")
                if scanned
                else _("The profiles show once the host is scanned.")
            )
            return
        n = len(ticked)
        words = ngettext("{n} profile", "{n} profiles", n).format(n=n)
        size = sum(sizes.get(p.ident, 0) for p in ticked)
        self.title.setText(f"{words} · {rows.size_text(size)}" if size else words)
        self.title.setStyleSheet(f"color: {AMBER};")
        self.hint.setText(_("A click on a line shows the profile in the table."))


class RunCard(QFrame):
    """A host's card while its profiles are deleted, and after: where the run is, the bar, a
    line per profile with how it stands. Once it's over: Open the history, and Close, which
    brings the ticked profiles' card back."""

    picked = Signal(str)  # a profile's ident
    log_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        _as_card(self)
        self._over = False
        self.caption = caption()
        self.title = big()
        self.title.setWordWrap(True)
        self.second = DetailsPanel.muted("")
        self.bar = _thin_bar()
        self.lines = Lines(TICKED_LINES, own_more=True)
        self.lines.clicked.connect(self.picked)
        self.note = DetailsPanel.muted("")
        self.log_button = QPushButton()
        self.close_button = QPushButton()
        for button in (self.log_button, self.close_button):
            button.setAutoDefault(False)
        self.log_button.clicked.connect(self.log_requested)
        self.close_button.clicked.connect(self.closed)
        buttons = QHBoxLayout()
        buttons.addWidget(self.log_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        column = _column(self)
        column.addWidget(self.caption)
        column.addWidget(self.title)
        column.addWidget(self.second)
        column.addSpacing(4)
        column.addWidget(self.bar)
        column.addSpacing(8)
        column.addWidget(self.lines)
        column.addSpacing(8)
        column.addWidget(self.note)
        column.addLayout(buttons)
        column.addStretch(1)

    def show_run(self, over: bool, title: str, second: str, ended: int, total: int,
                 entries: Sequence[Entry]) -> None:  # fmt: skip
        """`title`: "2 of 3 profiles", or how the run ended. `second`: the grey line under it."""
        self._over = over
        self.caption.setText(_("DELETION FINISHED") if over else _("DELETING PROFILES"))
        self.title.setText(title)
        self.second.setText(second)
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(max(total, 1) if over else ended)
        self.lines.show_entries(
            entries,
            lambda n: ngettext("and {n} more profile", "and {n} more profiles", n).format(n=n),
        )
        self.note.setText(
            _("The current profile finishes first; the queued ones don't start. Every delete "
              "goes in the history.")
        )  # fmt: skip
        self.log_button.setText(_("Open the history"))
        self.close_button.setText(_("Close"))
        self.note.setVisible(not over)
        self.log_button.setVisible(over)
        self.close_button.setVisible(over)

    def over(self) -> bool:
        return self._over


class Foot(QWidget):
    """The button at the foot of a host's panel, the panel's full width: the amber Delete, or,
    while the host deletes, a plain Cancel the rest in its place."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_button = risky_button("")
        self.cancel_button = QPushButton()
        self.cancel_button.setAutoDefault(False)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for button in (self.delete_button, self.cancel_button):
            button.setFixedHeight(FOOT)
            column.addWidget(button)
        self.cancel_button.hide()

    def show_delete(self, text: str, enabled: bool, tip: str) -> None:
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        self.delete_button.setText(" " + text)
        self.delete_button.setEnabled(enabled)
        self.delete_button.setToolTip(tip)
        self.delete_button.setIcon(tabler_icon("trash", QColor(AMBER) if enabled else muted))
        self.delete_button.show()
        self.cancel_button.hide()

    def show_cancel(self, enabled: bool) -> None:
        color = self.cancel_button.palette().color(QPalette.ColorRole.ButtonText)
        self.cancel_button.setText(" " + _("Cancel the rest"))
        self.cancel_button.setIcon(tabler_icon("x", color))
        self.cancel_button.setEnabled(enabled)
        self.cancel_button.show()
        self.delete_button.hide()


class ProfileWindow(QDialog):
    """A profile's details, in a window: what the right panel used to show, with a tick for
    deleting it and Close. It shows the profile it was opened for."""

    tick_toggled = Signal(bool)
    copied = Signal(str)

    def __init__(self, parent: QWidget | None, host: str, user: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Profile {user} on {host}").format(user=user, host=host))
        self.details = ProfileDetails()
        self.details.copied.connect(self.copied)
        self.tick = QCheckBox(_("Tick to delete"))
        self.tick.toggled.connect(self.tick_toggled)
        self.close_button = QPushButton(_("Close"))
        quiet_default(self.close_button)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.tick)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        column = QVBoxLayout(self)
        column.setContentsMargins(12, 12, 12, 12)
        column.setSpacing(10)
        column.addWidget(self.details, 1)
        column.addLayout(buttons)
        self.resize(460, 560)
        self.close_button.setFocus()

    def show_profile(self, shown: Shown, ticked: bool, can_tick: bool) -> None:
        """`can_tick`: the row has a tick box that may change now."""
        self.details.show_item(shown, 1)
        self.tick.blockSignals(True)
        self.tick.setChecked(ticked)
        self.tick.blockSignals(False)
        self.tick.setEnabled(can_tick)
        self.tick.setToolTip(
            "" if can_tick else _("Only a profile that can be deleted, outside a delete run")
        )
