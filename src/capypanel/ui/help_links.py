"""Help from where you are: F1 or a window's ?, at its own part of the docs, and "What does this
mean?" on every warning and error. Every place is in PLACES or TOPS, which the docs check reads."""

from collections.abc import Callable
from html import escape

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QToolButton,
    QWidget,
    QWidgetItem,
)

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon
from capypanel.ui.themes.engine import contrast_ratio

KEY = "F1"  # kept for help: no command can take it (shortcuts.RESERVED)
READABLE = 4.5  # a link's least contrast with what's behind it, as for any text
CARD = QPalette.ColorRole.Base  # behind a link on a card or in a message box
LINK_KEYS = (
    Qt.TextInteractionFlag.LinksAccessibleByMouse | Qt.TextInteractionFlag.LinksAccessibleByKeyboard
)

# Each id (an <a id> in both languages' page source, never changed or reused once released) with
# its page, after the docs' address. A window with no part of its own opens its page's top: TOPS.
PLACES: dict[str, str] = {
    # Home's part of Getting started
    "start-run-capypanel": "getting-started/",
    "start-add-your-first-hosts": "getting-started/",
    "start-hide-parts-of-the-details-panel": "getting-started/",
    "start-get-help-or-report-a-problem": "getting-started/",
    "start-folder-other-user": "getting-started/",
    # Settings: the page shown
    "settings-find-a-setting": "settings-and-files/",
    "settings-capypanel-general": "settings-and-files/",
    "settings-capypanel-keyboard-shortcuts": "settings-and-files/",
    "settings-hosts-general": "settings-and-files/",
    "settings-hosts-connecting": "settings-and-files/",
    "settings-hosts-credentials": "settings-and-files/",
    "settings-printers": "settings-and-files/",
    "settings-ssh-general": "settings-and-files/",
    "settings-about": "settings-and-files/",
    "settings-updates-not-saved": "settings-and-files/",
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
    # Hosts: its messages
    "hosts-not-a-list": "hosts/host-lists/",
    "hosts-list-gone": "hosts/host-lists/",
    "hosts-list-file-error": "hosts/host-lists/",
    "hosts-list-cant-open": "hosts/host-lists/",
    "hosts-default-list-other-user": "hosts/host-lists/",
    "hosts-list-changed": "hosts/host-lists/",
    "hosts-list-not-recycled": "hosts/host-lists/",
    "hosts-list-rule": "hosts/host-lists/",
    "hosts-file-not-saved": "hosts/host-lists/",
    "hosts-preset-name-taken": "hosts/host-lists/",
    "connect-name-not-address": "hosts/connecting/",
    "connect-login-check-skipped": "hosts/connecting/",
    "connect-profile-not-available": "hosts/connecting/",
    "connect-viewer-not-found": "hosts/connecting/",
    "connect-password-not-saved": "hosts/connecting/",
    "connect-password-not-deleted": "hosts/connecting/",
    "connect-couldnt-start": "hosts/connecting/",
    "connect-settings-file-unusable": "hosts/connecting/",
    "connect-settings-not-saved": "hosts/connecting/",
    # Hosts: why a command failed (its strip, the Commands window's answer)
    "command-access-denied": "hosts/commands/",
    "command-no-folder": "hosts/commands/",
    "command-timed-out": "hosts/commands/",
    "command-windows-error": "hosts/commands/",
    "pc-unreachable": "hosts/checking/",
    "pc-account-rejected": "hosts/checking/",
    "pc-powershell-blocked": "hosts/checking/",
    # Profile cleanup
    "profiles-see-which-profiles-can-be-deleted": "profiles/user-profiles/",
    "profiles-delete-profiles": "profiles/user-profiles/",
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
    "printers-not-a-list": "printers/printers/",
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
    "ssh-work-in-the-terminal": "ssh/ssh/",
    "ssh-when-a-connection-ends": "ssh/ssh/",
    "ssh-not-installed": "ssh/ssh/",
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


def link_color(palette: QPalette, on: QPalette.ColorRole = QPalette.ColorRole.Window) -> QColor:
    """The theme's link colour where it reads on what's behind it (`on`: the window or CARD; a
    strip's palette has its tint as its window), else the text colour: links are underlined."""
    link = palette.color(QPalette.ColorRole.Link)
    if contrast_ratio(link.name(), palette.color(on).name()) >= READABLE:
        return link
    return palette.color(QPalette.ColorRole.WindowText)


def anchor(
    place: str, palette: QPalette, on: QPalette.ColorRole = QPalette.ColorRole.Window
) -> str:
    """ "What does this mean?" as rich text, coloured to read on `on` (link_color). A strip puts
    it in its message's label, to read right after it and wrap with it; open_place opens it."""
    style = f"color: {link_color(palette, on).name()}; text-decoration: underline;"
    words = escape(_("What does this mean?"))
    return f'<a href="{escape(url(place))}" style="{style}">{words}</a>'


def strip_anchor(place: str, strip: QWidget) -> str:
    """anchor() for a strip's message, judged on the tint the theme draws behind it: once polished,
    the strip's palette has that tint as its window, while its label keeps the window's colour."""
    strip.ensurePolished()
    return anchor(place, strip.palette())


def add_link(box: QMessageBox, place: str) -> None:
    """A warning's or error's "What does this mean?" under its text, and F1 for the same line. The
    box stays open when it's clicked. Call it last: informative text set later replaces it."""
    before = box.informativeText()
    link = anchor(place, box.palette(), CARD)  # a box is drawn on the card colour
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
    """The ? at a window's bottom left, first in its button row: help at `place()`'s part, and F1
    while the window is in front: flat, icon only, never hidden or greyed. _InkOnEdge places it."""

    def __init__(self, place: Callable[[], str] | str, *, icon_size: int = 18) -> None:
        super().__init__()
        self._place = place if callable(place) else (lambda: place)
        self._seated = False
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

    def ink_inset(self) -> int:
        """Where the ?'s ink starts, from its left edge: the icon sits in the middle (rounded
        down, as Qt places it), and the circle's ink starts 2 of the icon's 24 units in."""
        icon = self.iconSize().width()
        return (self.width() - icon) // 2 + icon // 12

    def showEvent(self, event: QShowEvent) -> None:
        if not self._seated:
            self._seated = True
            _seat(self)
        super().showEvent(event)

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


class _InkOnEdge(QWidgetItem):
    """The ?'s place in its row, moved left by its ink's inset: the ink starts where the row does,
    the hover box reaching into the margin, never past its parent's edge, which would cut it."""

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        button = self.widget()
        if isinstance(button, HelpButton) and not button.isRightToLeft():
            at = button.pos()
            button.move(at.x() - min(button.ink_inset(), at.x()), at.y())


def _seat(button: HelpButton) -> None:
    """Its row's item swapped for _InkOnEdge, in the same place, with the same alignment and
    stretch. In a layout other than a row or a column it stays as it is."""
    parent = button.parentWidget()
    layout = _holding(parent.layout() if parent is not None else None, button)
    if not isinstance(layout, QBoxLayout):
        return
    index = layout.indexOf(button)
    old = layout.itemAt(index)
    if old is None:
        return
    stretch = layout.stretch(index)
    item = _InkOnEdge(button)
    item.setAlignment(old.alignment())
    layout.takeAt(index)
    layout.insertItem(index, item)
    layout.setStretch(index, stretch)
    if old.geometry().isValid():
        item.setGeometry(old.geometry())  # moved now, before it's first drawn


def _holding(layout: QLayout | None, widget: QWidget) -> QLayout | None:
    """`layout`, or the one inside it, that has `widget` as one of its items."""
    if layout is None or layout.indexOf(widget) >= 0:
        return layout
    for index in range(layout.count()):
        item = layout.itemAt(index)
        found = _holding(item.layout() if item is not None else None, widget)
        if found is not None:
            return found
    return None


def row(help_button: HelpButton, buttons: QWidget) -> QHBoxLayout:
    """A window's button row: its ? first, on the left, then its buttons at the right."""
    line = QHBoxLayout()
    line.addWidget(help_button)
    line.addWidget(buttons, 1)
    return line


class HelpLink(QLabel):
    """ "What does this mean?" linking a message's line, for a strip: after the message, before its
    buttons; Tab reaches it, Enter opens it; hidden with no place. `on`: what's behind it."""

    def __init__(self, on: QPalette.ColorRole = QPalette.ColorRole.Window) -> None:
        super().__init__()
        self._place, self._on = "", on
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
            self.setText(anchor(self._place, self.palette(), self._on))
            self.setToolTip(url(self._place))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.LanguageChange):
            self._show()
