import functools
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

from capypanel.core import settings
from capypanel.ui import spacing
from capypanel.ui.main_window.toolbar import ToolBar
from capypanel.ui.settings.group import SettingsGroup

if TYPE_CHECKING:
    from capypanel.ui.guides import Guide
    from capypanel.ui.saved_credentials import KeptLogin
    from capypanel.ui.shortcuts import KeyCommand


class Shell(Protocol):
    paths: settings.Paths
    prefs: dict[str, Any]

    def tool_prefs(self, tool_id: str, *, inherit: bool = False) -> dict[str, Any]: ...

    def save_prefs(self) -> None: ...

    def open_settings(self, page: str | None = None) -> None: ...

    def show_message(self, text: str, timeout: int = 5000) -> None: ...

    def kept_logins(self) -> list["KeptLogin"]: ...

    def open_saved_credentials(self, parent: QWidget | None = None) -> None: ...

    def quit_app(self) -> None: ...

    def tool(self, tool_id: str) -> "Tool | None": ...

    def show_tool(self, tool_id: str) -> bool: ...

    def fills_now(self, tool_id: str) -> bool: ...


class ToolKind(Protocol):
    def __call__(self, shell: Shell) -> "Tool": ...

    def prepare(self, paths: settings.Paths) -> None: ...


class StatusLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _take_along(toolbar: ToolBar) -> None:
    """Its toolbar goes with it: left behind, the next theme switch read a deleted command's key."""
    if shiboken6.isValid(toolbar):
        shiboken6.delete(toolbar)


class Tool(QWidget):
    TOOL_ID: ClassVar[str] = ""
    ICON: ClassVar[str] = ""
    HELP_PLACE: ClassVar[str] = ""
    INHERITS_TOP_LEVEL: ClassVar[bool] = False
    title_changed = Signal(str)
    badge_changed = Signal(int)  # how many items need attention: the rail's count; 0 hides it
    notify_requested = Signal(str, str)  # a Windows notification: its title and text
    front_requested = Signal()

    def __init__(self, shell: Shell, toolbar: ToolBar):
        super().__init__()
        self._shell = shell
        self.prefs = shell.tool_prefs(self.TOOL_ID, inherit=self.INHERITS_TOP_LEVEL)
        self.toolbar = toolbar
        self.destroyed.connect(functools.partial(_take_along, toolbar))
        self.status_label = StatusLabel()
        self.status_label.setContentsMargins(spacing.CONTROLS, 0, spacing.CONTROLS, 0)

    @classmethod
    def prepare(cls, paths: settings.Paths) -> None:
        pass

    def tool_name(self) -> str:
        raise NotImplementedError

    def help_place(self) -> str:
        return self.HELP_PLACE

    def menu_name(self) -> str:
        raise NotImplementedError

    def title(self) -> str:
        return ""

    def attention_text(self, n: int) -> str:
        return ""

    def show_attention(self) -> None:
        pass

    def guide(self) -> "Guide | None":
        return None

    def first_use_pending(self) -> bool:
        return False

    def first_use_warning(self, parent: QWidget) -> bool:
        return True

    def came_to_front(self) -> None:
        pass

    def working(self) -> bool:
        return False

    def works_in_background(self) -> bool:
        return False

    def kept_logins(self) -> list["KeptLogin"]:
        return []

    def status_widgets(self) -> list[QWidget]:
        return []

    def view_actions(self) -> list[list[QAction]]:
        return []

    def settings_group(self) -> SettingsGroup | None:
        return None

    def key_commands(self) -> list["KeyCommand"]:
        return []

    def save_state(self) -> None:
        pass

    def quit_question(self, parent: QWidget) -> bool:
        return True

    def retranslate(self) -> None:
        pass

    def restyle(self) -> None:
        self.toolbar.restyle()
        self.align_toolbar_later()

    def align_toolbar_later(self) -> None:
        # Tied to this widget, so a call still pending when it closes is dropped, not run.
        QTimer.singleShot(0, self, self._align_toolbar)

    def _align_toolbar(self) -> None:
        if self.toolbar.isVisible():
            left = self.toolbar_anchor().mapToGlobal(QPoint(0, 0)).x()
            start = self.toolbar.mapToGlobal(QPoint(0, 0)).x()
            self.toolbar.align(left - start)

    def toolbar_anchor(self) -> QWidget:
        return self
