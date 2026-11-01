"""The strip above the printer table while printers need attention: how many and why, with Show
to list just them, then Show all to go back. Like the tag strip, with an amber edge."""

from collections import Counter
from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from capypanel.core.i18n import _, ngettext
from capypanel.core.printers.reading import SupplyKind
from capypanel.ui.icons import tabler_icon
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.status import AMBER, Attention, Checked

MOST_LINES = 5  # printers named in one notification; the rest are counted

ICON = 16


def reasons_text(found: Iterable[Attention]) -> str:
    """Why they need it, "1 stopped, 1 offline, 1 low", in that order, leaving out the ones at 0."""
    counts = Counter(found)
    texts = {
        Attention.STOPPED: lambda n: ngettext("{n} stopped", "{n} stopped", n),
        Attention.OFFLINE: lambda n: ngettext("{n} offline", "{n} offline", n),
        Attention.LOW: lambda n: ngettext("{n} low", "{n} low", n),
    }
    return ", ".join(
        texts[kind](counts[kind]).format(n=counts[kind]) for kind in Attention if counts[kind]
    )


def attention_text(n: int) -> str:
    """What the rail's count means, "3 printers need attention": its tooltip, and the tray."""
    return ngettext("{n} printer needs attention", "{n} printers need attention", n).format(n=n)


def why_text(checked: Checked, why: Attention, low: int) -> str:
    """A notification's reason for one printer: "Paper jam", "Offline", "Black 7 %"."""
    reading = checked.reading
    if why is not Attention.LOW or reading is None:
        return status.status(checked, low).text
    lows = [s for s in reading.supplies if status.is_low(s, low)]
    lowest = min(lows, key=lambda s: s.percent or 0)
    if lowest.kind in (SupplyKind.TONER, SupplyKind.INK) and lowest.percent is not None:
        return _("{colour} {percent} %").format(
            colour=status.colour_name(lowest), percent=lowest.percent
        )
    return status.low_text(lowest)


def notice_text(lines: list[str]) -> str:
    """One line per printer, at most MOST_LINES, then how many more."""
    shown = lines[:MOST_LINES]
    if more := len(lines) - len(shown):
        shown.append(ngettext("and {n} more", "and {n} more", more).format(n=more))
    return "\n".join(shown)


class AttentionStrip(QFrame):
    show_clicked = Signal()  # Show, or Show all once only those are listed

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("attentionStrip")
        self._icon = QLabel()
        self._icon.setPixmap(tabler_icon("alert-triangle", QColor(AMBER), ICON).pixmap(ICON, ICON))
        self._text = QLabel()
        self._text.setTextFormat(Qt.TextFormat.RichText)
        self._text.setWordWrap(True)
        self.button = QPushButton()
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self.show_clicked)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 4, 4)
        row.addWidget(self._icon)
        row.addWidget(self._text, 1)
        row.addWidget(self.button)
        self.hide()

    def show_found(self, found: list[Attention], only_them: bool) -> None:
        """Hidden when nothing needs attention."""
        n = len(found)
        self.setVisible(bool(n))
        if not n:
            return
        if only_them:
            text = ngettext(
                "Showing the <b>{n} printer</b> that needs attention.",
                "Showing the <b>{n} printers</b> that need attention.",
                n,
            ).format(n=n)
            self.button.setText(_("Show all"))
            self.button.setToolTip(_("Show every printer again"))
        else:
            text = ngettext(
                "<b>{n} printer</b> needs attention: {reasons}.",
                "<b>{n} printers</b> need attention: {reasons}.",
                n,
            ).format(n=n, reasons=reasons_text(found))
            self.button.setText(_("Show"))
            self.button.setToolTip(_("List only the printers that need attention"))
        self._text.setText(text)
