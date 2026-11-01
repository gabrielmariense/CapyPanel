"""A tool the shell shows (Hosts, Printers…), and what a tool can ask of the shell."""

from typing import Any, ClassVar, Protocol

from PySide6.QtCore import QPoint, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QWidget

from capypanel.core import settings
from capypanel.ui.main_window.toolbar import ToolBar
from capypanel.ui.settings.group import SettingsGroup


class Shell(Protocol):
    paths: settings.Paths
    prefs: dict[str, Any]  # every saved setting; save_prefs() writes them

    def tool_prefs(self, tool_id: str, *, inherit: bool = False) -> dict[str, Any]:
        """A tool's own section of the settings."""
        ...

    def save_prefs(self) -> None: ...

    def open_settings(self, page: str | None = None) -> None: ...

    def show_message(self, text: str, timeout: int = 5000) -> None:
        """A short note in the status bar."""
        ...


class ToolKind(Protocol):
    """A tool class, as the tool catalog lists it: made from the shell, and able to prepare its
    files."""

    def __call__(self, shell: Shell) -> "Tool": ...

    def prepare(self, paths: settings.Paths) -> None: ...


class Tool(QWidget):
    """What a tool gives the shell: its central widget (itself), its toolbar, its rail icon and
    View entry, its View items, its status bar text and its window title. A tool keeps its
    settings in its own section of the settings file (self.prefs)."""

    TOOL_ID: ClassVar[str] = ""  # its settings section and Settings pages are named after it
    ICON: ClassVar[str] = ""  # a Tabler icon, for the rail
    INHERITS_TOP_LEVEL: ClassVar[bool] = False  # Hosts: 0.19 kept its settings at the top
    title_changed = Signal(str)  # the window title's first part, or "" for none
    badge_changed = Signal(int)  # how many items need attention: the rail's count; 0 hides it
    notify_requested = Signal(str, str)  # a Windows notification: its title and text

    def __init__(self, shell: Shell, toolbar: ToolBar):
        super().__init__()
        self._shell = shell
        self.prefs = shell.tool_prefs(self.TOOL_ID, inherit=self.INHERITS_TOP_LEVEL)
        self.toolbar = toolbar  # the shell shows it above the tool
        self.status_label = QLabel()  # the shell shows it in its status bar, on the left
        self.status_label.setContentsMargins(6, 0, 6, 0)

    @classmethod
    def prepare(cls, paths: settings.Paths) -> None:
        """At start, before any window: files the tool needs to exist (e.g. its starters)."""

    def tool_name(self) -> str:
        """Its name on the rail: "Hosts"."""
        raise NotImplementedError

    def menu_name(self) -> str:
        """Its name in View, with an access key: "&Hosts"."""
        raise NotImplementedError

    def title(self) -> str:
        """The window title's first part (the open list's name), or "" for none."""
        return ""

    def attention_text(self, n: int) -> str:
        """What its rail count means, "3 printers need attention", for tooltips and the tray."""
        return ""

    def show_attention(self) -> None:
        """Lists just the items that need attention (the tray's menu asks for it)."""

    def works_in_background(self) -> bool:
        """Whether it does something on its own (Refresh on its own), worth keeping CapyPanel
        running in the tray for when the window closes."""
        return False

    def status_widgets(self) -> list[QWidget]:
        """Shown on the right of the status bar while the tool is."""
        return []

    def view_actions(self) -> list[list[QAction]]:
        """The tool's part of the View menu, in groups split by lines."""
        return []

    def settings_group(self) -> SettingsGroup | None:
        """Its part of Settings, under its name in the page list."""
        return None

    def save_state(self) -> None:
        """When the window closes."""

    def retranslate(self) -> None:
        """Every text the tool shows, in the current language."""

    def restyle(self) -> None:
        """After a theme switch."""
        self.toolbar.restyle()
        self.align_toolbar_later()

    def align_toolbar_later(self) -> None:
        # Tied to this widget, so a call still pending when it closes is dropped, not run.
        QTimer.singleShot(0, self, self._align_toolbar)  # once the panels have their sizes

    def _align_toolbar(self) -> None:
        if self.toolbar.isVisible():
            left = self.toolbar_anchor().mapToGlobal(QPoint(0, 0)).x()
            start = self.toolbar.mapToGlobal(QPoint(0, 0)).x()
            self.toolbar.align(left - start)

    def toolbar_anchor(self) -> QWidget:
        """The widget the toolbar's first button lines up with."""
        return self
