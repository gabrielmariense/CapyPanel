"""CapyPanel: manage the computers on your network from one window."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("capypanel")
except PackageNotFoundError:  # running from a copy that was never installed
    __version__ = "0.0.0+unknown"
