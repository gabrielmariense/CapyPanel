"""Which app this is: CapyPanel with all its tools, or a build with one tool (CapyPrinters).
The name shows in titles and messages; each app keeps its files in a folder named after it; a
one-tool build has no rail of tools."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    name: str  # in the window title and in messages: "CapyPanel"
    folder: str  # its data folder: ProgramData\<folder>; stays the same if the app is renamed
    portable_marker: str  # this file beside the app means portable mode
    windows_app_id: str  # groups its windows on the taskbar, with its own icon
    rail: bool = True  # the rail of tools down the window's left edge


CAPYPANEL = Identity(
    "CapyPanel",
    folder="CapyPanel",
    portable_marker="capypanel.portable",
    windows_app_id="CapyPanel.CapyPanel",
)
_current = CAPYPANEL


def current() -> Identity:
    return _current


def use(identity: Identity) -> None:
    """Set once at start, before any window is made."""
    global _current
    _current = identity
