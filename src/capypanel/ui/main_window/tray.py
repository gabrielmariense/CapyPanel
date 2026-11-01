"""CapyPanel's icon in the Windows tray: there while the window is in the tray or a tool works on
its own (Refresh on its own), so its notifications can show. A click opens the window. Its menu:
Open CapyPanel (bold, what the click does), a line per tool with items needing attention ("3
printers need attention…"), Quit CapyPanel. The icon carries the rail's red count, added up."""

import html
from collections.abc import Mapping

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QCheckBox, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from capypanel.core import settings
from capypanel.core.i18n import _
from capypanel.ui import branding
from capypanel.ui.dialogs import run_modal
from capypanel.ui.icons import STATUS_COLORS

SIZE = 32  # px the icon is drawn at; Windows scales it to the tray


def counted_icon(count: int) -> QIcon:
    """The app icon, with `count` in a red circle on its top right corner when there's one."""
    if count <= 0:
        return branding.app_icon()
    pixmap = branding.app_icon().pixmap(SIZE, SIZE)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    badge = QRectF(SIZE * 0.42, 0, SIZE * 0.58, SIZE * 0.58)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(STATUS_COLORS["stopped"]))
    painter.drawEllipse(badge)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(round(SIZE * (0.42 if count < 10 else 0.32)))
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(count) if count < 100 else "99+")
    painter.end()
    return QIcon(pixmap)


class Tray(QObject):
    open_requested = Signal()
    quit_requested = Signal()
    attention_requested = Signal(str)  # a tool's id: list just its items needing attention
    message_clicked = Signal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(counted_icon(0), self)
        self.menu = QMenu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(self.message_clicked)
        self._counts: dict[str, tuple[int, str]] = {}  # tool id: (count, "3 printers need …")
        self.fill()

    @staticmethod
    def available() -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def set_shown(self, shown: bool) -> None:
        self.icon.setVisible(shown and self.available())

    def is_shown(self) -> bool:
        return self.icon.isVisible()

    def set_counts(self, counts: Mapping[str, tuple[int, str]]) -> None:
        """Each tool's count and what it means, in the rail's order."""
        self._counts = {t: c for t, c in counts.items() if c[0] > 0}
        self.fill()

    def fill(self) -> None:
        """The menu and tooltip, in the current language."""
        self.menu.clear()
        opener = QAction(_("&Open CapyPanel"), self.menu)
        opener.triggered.connect(self.open_requested)
        self.menu.addAction(opener)
        self.menu.setDefaultAction(opener)  # bold: what a click on the icon does
        for tool_id, (_count, meaning) in self._counts.items():
            if meaning:
                self.menu.addSeparator()
                action = QAction(f"{meaning}…", self.menu)
                action.setData(tool_id)
                action.triggered.connect(self._attention_picked)
                self.menu.addAction(action)
        self.menu.addSeparator()
        quitter = QAction(_("&Quit CapyPanel"), self.menu)
        quitter.triggered.connect(self.quit_requested)
        self.menu.addAction(quitter)
        total = sum(count for count, _m in self._counts.values())
        self.icon.setIcon(counted_icon(total))
        lines = ["CapyPanel", *(m for _c, m in self._counts.values() if m)]
        self.icon.setToolTip("\n".join(lines))

    def notify(self, title: str, text: str) -> None:
        """A Windows notification; a click on it emits message_clicked."""
        if self.available():
            self.icon.showMessage(title, text, counted_icon(0), 15_000)

    def _attention_picked(self) -> None:
        action = self.sender()
        if isinstance(action, QAction):
            self.attention_requested.emit(str(action.data()))

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.open_requested.emit()


def ask_closing(parent: QWidget) -> tuple[str | None, bool]:
    """The window's X, with "Ask each time": (settings.CLOSE_TRAY or CLOSE_QUIT, or None for
    Cancel; whether "Don't ask again" was ticked)."""
    box = QMessageBox(parent)
    box.setWindowTitle("CapyPanel")
    box.setIconPixmap(branding.app_icon().pixmap(48, 48))
    box.setText(f"<b>{html.escape(_('Keep CapyPanel running in the tray?'))}</b>")
    box.setInformativeText(
        _("Refresh on its own and warnings keep working while CapyPanel is in the tray. "
          "Quit stops them.")
    )  # fmt: skip
    box.setCheckBox(QCheckBox(_("Don't ask again (change it in Settings › CapyPanel › Startup)")))
    keep = box.addButton(_("Keep in &tray"), QMessageBox.ButtonRole.AcceptRole)
    quitter = box.addButton(_("&Quit"), QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(keep)
    box.setEscapeButton(cancel)
    run_modal(box)
    clicked = box.clickedButton()
    choice = None
    if clicked is keep:
        choice = settings.CLOSE_TRAY
    elif clicked is quitter:
        choice = settings.CLOSE_QUIT
    return choice, choice is not None and box.checkBox().isChecked()
