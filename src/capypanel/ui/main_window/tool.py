"""What a tool can ask of the shell it's shown in."""

from typing import Any, Protocol

from capypanel.core import settings


class Shell(Protocol):
    paths: settings.Paths
    prefs: dict[str, Any]  # every saved setting; save_prefs() writes them

    def save_prefs(self) -> None: ...

    def open_settings(self, page: str | None = None) -> None: ...

    def show_message(self, text: str, timeout: int = 5000) -> None:
        """A short note in the status bar."""
        ...
