"""CapyPanel: manage the computers on your network from one window."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("capypanel")
except PackageNotFoundError:  # running from a copy that was never installed
    __version__ = "0.0.0+unknown"


def _commit() -> str:
    """The short commit of a source checkout, so testers can tell builds apart; "" if none."""
    git = Path(__file__).resolve().parents[2] / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7]  # a detached checkout names the commit itself
        ref = head.removeprefix("ref: ")
        if (git / ref).is_file():
            return (git / ref).read_text(encoding="utf-8").strip()[:7]
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {ref}"):
                return line[:7]
    except OSError:  # not a checkout (installed app), or a worktree's .git file
        pass
    return ""


# What the title bar and the log show: "0.8.1", plus "(3b4c3e0)" when run from source.
BUILD = f"{__version__} ({_commit()})" if _commit() else __version__
