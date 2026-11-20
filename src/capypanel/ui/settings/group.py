"""A tool's part of Settings: its label in the page list and its pages."""

from typing import ClassVar

from capypanel.ui.settings.pages import Page


class SettingsGroup:
    """build() runs each time Settings is built (a language switch too): it reads the settings
    then. Its pages apply each choice at once. Page ids are unique across tools, opened by id."""

    LABEL: ClassVar[str] = ""  # an N_() text, shown translated: "Hosts"
    TITLES: ClassVar[tuple[str, ...]] = ()  # its pages' titles, N_() texts: the list's width

    def build(self) -> list[tuple[str, Page]]:
        raise NotImplementedError

    def before_rebuild(self) -> None:
        """The language changed: keep whatever the new pages should show again."""

    def after_rebuild(self) -> None:
        """The pages were built again, in the new language."""

    def credentials_changed(self) -> None:
        """Saved credentials were forgotten: show what's kept now."""
