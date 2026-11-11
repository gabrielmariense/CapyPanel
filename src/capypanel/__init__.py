"""CapyPanel: manage the computers on your network from one window."""

from pathlib import Path


def _version() -> str:
    """A source checkout's own pyproject.toml says it: one small file, and right even when the
    environment wasn't synced after a pull (the installed package data then still names the
    version before). An installed copy asks that package data."""
    try:
        project = Path(__file__).resolve().parents[2] / "pyproject.toml"
        lines = project.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if 'name = "capypanel"' in lines:
        for line in lines:
            if line.startswith('version = "'):
                return line.split('"')[1]
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("capypanel")
    except PackageNotFoundError:  # running from a copy that was never installed
        return "0.0.0+unknown"


__version__ = _version()


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


def _build_number(root: Path, commit: str) -> str:
    """Every commit ever made toward this build, "1378", the squashed ones too: it only grows,
    so a bigger number is a newer build. "" without git. Counting asks git, which can take
    seconds on a cold start, so the answer is kept beside the checkout's own files (in .git,
    never committed) and git is asked once per commit."""
    import contextlib
    import subprocess

    kept = root / ".git" / "capypanel-build"
    try:
        was, _space, number = kept.read_text(encoding="utf-8").strip().partition(" ")
        if was == commit and number.isdigit():
            return number
    except OSError:  # nothing kept yet, or a worktree's .git file
        pass
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return ""
    counted = done.stdout.strip()
    if done.returncode != 0 or not counted.isdigit():
        return ""
    number = str(int(counted) + _SQUASHED)
    with contextlib.suppress(OSError):  # a checkout that can't be written: asked again
        kept.write_text(f"{commit} {number}", encoding="utf-8")
    return number


# What the title bar and the log show: "0.8.1", plus "build 1378 (3b4c3e0)" when run from
# source: the number to compare with the build a test asks for, and its commit.
_COMMIT = _commit()
_NUMBER = _build_number(Path(__file__).resolve().parents[2], _COMMIT) if _COMMIT else ""
BUILD = (
    f"{__version__} build {_NUMBER} ({_COMMIT})" if _NUMBER
    else f"{__version__} ({_COMMIT})" if _COMMIT
    else __version__
)  # fmt: skip
