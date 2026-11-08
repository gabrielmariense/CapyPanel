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


# Commits that PRs #1–#35 had before squash merges folded each into one: 336 in 35 PRs.
_SQUASHED = 336 - 35


def _build_number() -> str:
    """Every commit ever made toward this build, "1378", the squashed ones too: it only grows,
    so a bigger number is a newer build. "" without git."""
    import subprocess

    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return ""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return ""
    number = done.stdout.strip()
    return str(int(number) + _SQUASHED) if done.returncode == 0 and number.isdigit() else ""


# What the title bar and the log show: "0.8.1", plus "build 1378 (3b4c3e0)" when run from
# source: the number to compare with the build a test asks for, and its commit.
_COMMIT = _commit()
_NUMBER = _build_number() if _COMMIT else ""
BUILD = (
    f"{__version__} build {_NUMBER} ({_COMMIT})" if _NUMBER
    else f"{__version__} ({_COMMIT})" if _COMMIT
    else __version__
)  # fmt: skip
