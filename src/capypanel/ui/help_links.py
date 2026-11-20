"""Help from where you are (0.30). F1, or the ? at a window's bottom left (the main window's is
in the rail, above the gear), opens the docs at that window's own part. Every warning and error
says "What does this mean?": a link to its own line under its page's "Messages you may see",
and a message box stays open while it's read.

Every place help opens is in PLACES or TOPS, never a bare address anywhere else: the docs check
(tests/docs/test_help_places.py, a CI job of its own) reads them and both languages' pages, and
fails when one isn't there. The ids are the docs': an <a id> in the page source, the same in
English and Portuguese, never changed or reused once a published CapyPanel links it."""

from collections.abc import Callable
from html import escape

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QLabel, QMessageBox, QToolButton, QWidget

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes.engine import contrast_ratio

KEY = "F1"  # kept for help: no command can take it (shortcuts.RESERVED)
READABLE = 4.5  # a link's least contrast with the window, as for any text
LINK_KEYS = (
    Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
)

# Each id with its page, after the docs' address. Pages open at their top when the window has no
# part of its own: those are in TOPS.
PLACES: dict[str, str] = {
    # Home's part of Getting started
    "start-run-capypanel": "getting-started/",
    "start-add-your-first-hosts": "getting-started/",
    "start-hide-parts-of-the-details-panel": "getting-started/",
    "start-get-help-or-report-a-problem": "getting-started/",
    # Settings: the page shown
    "settings-capypanel-general": "settings-and-files/",
    "settings-capypanel-keyboard-shortcuts": "settings-and-files/",
    "settings-hosts-general": "settings-and-files/",
    "settings-hosts-connecting": "settings-and-files/",
    "settings-hosts-credentials": "settings-and-files/",
    "settings-printers": "settings-and-files/",
    "settings-ssh-general": "settings-and-files/",
    "settings-about": "settings-and-files/",
    # Updates
    "download-update-capypanel": "download/",
    # Hosts
    "host-lists-arrange-hosts-in-groups": "hosts/host-lists/",
    "host-lists-add-hosts-from-a-spreadsheet": "hosts/host-lists/",
    "host-lists-export-hosts-to-a-spreadsheet": "hosts/host-lists/",
    "host-lists-switch-make-and-share-lists": "hosts/host-lists/",
    "connecting-connect-to-a-host": "hosts/connecting/",
    "connecting-set-up-connection-profiles": "hosts/connecting/",
    "connecting-use-another-account-on-some-pcs": "hosts/connecting/",
    "connecting-forget-a-saved-password": "hosts/connecting/",
    "hosts-checking-check-your-hosts": "hosts/checking/",
    "hosts-checking-see-who-is-logged-on": "hosts/checking/",
    "hosts-checking-when-a-host-refuses-your-account": "hosts/checking/",
    "hosts-checking-read-a-pcs-facts": "hosts/checking/",
    "commands-choose-your-quick-commands": "hosts/commands/",
    "commands-open-a-pcs-folders-and-admin-tools": "hosts/commands/",
    "commands-message-log-off-or-disconnect-someone": "hosts/commands/",
    "commands-restart-or-shut-down-a-pc": "hosts/commands/",
    "commands-fix-a-pcs-printing": "hosts/commands/",
    "commands-see-whats-installed-and-mapped": "hosts/commands/",
    "commands-the-commands-window": "hosts/commands/",
    # Profile cleanup
    "profiles-see-which-profiles-can-be-deleted": "profiles/user-profiles/",
    # Printers: its windows
    "printers-add-a-printer": "printers/printers/",
    "printers-import-many-printers-at-once": "printers/printers/",
    "printers-export-printers-to-a-spreadsheet": "printers/printers/",
    "printers-checking-see-how-much-toner-is-left": "printers/checking/",
    "printers-checking-see-which-printers-need-attention": "printers/checking/",
    "printers-checking-choose-which-problems-warn": "printers/checking/",
    "printers-checking-set-the-snmp-account": "printers/checking/",
    "printers-checking-get-page-counts-from-doc360-mps": "printers/checking/",
    # Printers: its messages
    "printer-offline": "printers/checking/",
    "printer-refused": "printers/checking/",
    "printer-unreadable": "printers/checking/",
    "printers-credential-not-saved": "printers/checking/",
    "doc360-no-account": "printers/checking/",
    "doc360-login-refused": "printers/checking/",
    "doc360-no-answer": "printers/checking/",
    "doc360-error-answer": "printers/checking/",
    "doc360-no-total": "printers/checking/",
    "doc360-pages-changed": "printers/checking/",
    "doc360-serial-not-listed": "printers/checking/",
    "doc360-serial-missing": "printers/checking/",
    "doc360-month-not-counted": "printers/checking/",
    # SSH
    "ssh-add-a-host": "ssh/ssh/",
    "ssh-choose-the-name-to-log-in-as": "ssh/ssh/",
}
TOPS = (
    "hosts/host-lists/",
    "printers/printers/",
    "profiles/user-profiles/",
    "ssh/ssh/",
    "settings-and-files/",
)


def url(place: str) -> str:
    """`place`'s address in the docs, in CapyPanel's language: an id from PLACES, or a page from
    TOPS opened at its top."""
    from capypanel.ui import about  # About's code loads when first needed, not at every start

    if place in PLACES:
        return f"{about.docs_url()}{PLACES[place]}#{place}"
    if place in TOPS:
        return about.docs_url() + place
    raise KeyError(f"no such help place: {place}")


def open_place(place: str) -> None:
    from capypanel.ui import about

    about.open_url(url(place))


def link_color(palette: QPalette) -> QColor:
    """The theme's link colour where it reads on the window, else the text colour: a link is
    underlined either way. Windows' own dark theme takes the PC's accent for links, which can be
    a dark purple that hardly shows."""
    link = palette.color(QPalette.ColorRole.Link)
    if contrast_ratio(link.name(), palette.color(QPalette.ColorRole.Window).name()) >= READABLE:
        return link
    return palette.color(QPalette.ColorRole.WindowText)


def _anchor(place: str, palette: QPalette) -> str:
    style = f"color: {link_color(palette).name()}; text-decoration: underline;"
    words = escape(_("What does this mean?"))
    return f'<a href="{escape(url(place))}" style="{style}">{words}</a>'


def anchor(place: str, palette: QPalette) -> str:
    """ "What does this mean?" as rich text, for a label that holds its message too (Printers'
    warnings strip), so the link wraps with the message rather than sitting apart from it. The
    label opens it with open_place on linkActivated."""
    return _anchor(place, palette)


def add_link(box: QMessageBox, place: str) -> None:
    """A warning's or error's "What does this mean?" under its text, and F1 for the same line.
    The box stays open when it's clicked. Call it last: informative text set after it would
    replace the link."""
    before = box.informativeText()
    link = _anchor(place, box.palette())
    if before:
        link = escape(before).replace("\n", "<br>") + "<br><br>" + link
    box.setInformativeText(link)
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    if label is not None:
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(False)
        label.setTextInteractionFlags(LINK_KEYS)
        label.linkActivated.connect(lambda _href: open_place(place))
        label.setToolTip(url(place))  # read off it to open on another device, with no internet
    key(box, lambda: place)


def warning(parent: QWidget | None, title: str, text: str, *, place: str) -> None:
    """A warning box with its line's link (QMessageBox.warning plus help)."""
    _show(QMessageBox.Icon.Warning, parent, title, text, place)


def critical(parent: QWidget | None, title: str, text: str, *, place: str) -> None:
    _show(QMessageBox.Icon.Critical, parent, title, text, place)


def _show(
    icon: QMessageBox.Icon, parent: QWidget | None, title: str, text: str, place: str
) -> None:
    from capypanel.ui.dialogs import run_modal

    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, parent)
    box.setTextFormat(Qt.TextFormat.PlainText)  # Windows' reasons can hold a "<"
    add_link(box, place)
    run_modal(box)


def key(window: QWidget, place: Callable[[], str]) -> QShortcut:
    """F1 in `window`, for a window with no ? of its own: a message box (its line) or a
    question (the part of the window that asked)."""
    shortcut = QShortcut(QKeySequence(KEY), window)
    shortcut.activated.connect(lambda: open_place(place()))
    return shortcut


class HelpButton(QToolButton):
    """The ? at a window's bottom left, first in its button row: help for this window at
    `place()`'s part, and F1 while the window is in front. Flat and icon only, so it's the same
    size in both languages; it never hides or greys (a window with no part of its own opens its
    page)."""

    def __init__(self, place: Callable[[], str] | str, *, icon_size: int = 18) -> None:
        super().__init__()
        self._place = place if callable(place) else (lambda: place)
        self.setObjectName("helpButton")
        self.setAutoRaise(True)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setShortcut(QKeySequence(KEY))
        self.clicked.connect(lambda: open_place(self._place()))
        self._retranslate()
        self._restyle()

    def place(self) -> str:
        return self._place()

    def _retranslate(self) -> None:
        self.setToolTip(_("Help for this screen (F1)"))
        self.setAccessibleName(_("Help for this screen"))

    def _restyle(self) -> None:
        color = self.palette().color(QPalette.ColorRole.ButtonText)
        self.setIcon(tabler_icon("help", color, self.iconSize().width()))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._restyle()
        elif event.type() == QEvent.Type.LanguageChange:
            self._retranslate()


class HelpLink(QLabel):
    """ "What does this mean?" as a link to a message's line, for a strip: after the message,
    before the strip's buttons. Tab reaches it and Enter opens it. With no place (a message that
    worked, which has no line) it's hidden."""

    def __init__(self) -> None:
        super().__init__()
        self._place = ""
        self.setObjectName("helpLink")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(LINK_KEYS)
        self.linkActivated.connect(lambda _href: open_place(self._place))
        self.hide()

    def set_place(self, place: str) -> None:
        self._place = place
        self.setVisible(bool(place))
        self._show()

    def _show(self) -> None:
        if self._place:
            self.setText(_anchor(self._place, self.palette()))
            self.setToolTip(url(self._place))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LanguageChange):
            self._show()
