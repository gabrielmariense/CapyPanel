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


def _commit_time() -> str:
    """When that commit was made, "2026-11-08 22:15" (this PC's time): unlike the commit's
    code it tells a newer build from an older one at a glance. "" without git."""
    import subprocess

    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return ""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cd",
             "--date=format-local:%Y-%m-%d %H:%M"],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


# What the title bar and the log show: "0.8.1", plus "(3b4c3e0, 2026-11-08 22:15)" when run
# from source: the commit, and when it was made, to compare with the build a test asks for.
_COMMIT = _commit()
_WHEN = _commit_time() if _COMMIT else ""
BUILD = (
    f"{__version__} ({_COMMIT}, {_WHEN})" if _WHEN
    else f"{__version__} ({_COMMIT})" if _COMMIT
    else __version__
)  # fmt: skip
