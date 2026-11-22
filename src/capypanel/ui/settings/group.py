from typing import ClassVar

from capypanel.ui.settings.pages import Page


class SettingsGroup:
    LABEL: ClassVar[str] = ""
    TITLES: ClassVar[tuple[str, ...]] = ()

    def build(self) -> list[tuple[str, Page]]:
        raise NotImplementedError

    def before_rebuild(self) -> None:
        pass

    def after_rebuild(self) -> None:
        pass

    def credentials_changed(self) -> None:
        pass
