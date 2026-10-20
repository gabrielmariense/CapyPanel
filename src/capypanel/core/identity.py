"""Which app this is: CapyPanel with all its tools, or a build with one tool (CapyPrinters).
The name shows in titles and messages; a one-tool build has no rail of tools."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    name: str  # in the window title and in messages: "CapyPanel"
    rail: bool = True  # the rail of tools down the window's left edge


CAPYPANEL = Identity("CapyPanel")
_current = CAPYPANEL


def current() -> Identity:
    return _current


def use(identity: Identity) -> None:
    """Set once at start, before any window is made."""
    global _current
    _current = identity
