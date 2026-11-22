from pathlib import Path

STAMP = "build.txt"


def _stamped(package: Path) -> tuple[str, str, str] | None:
    try:
        words = (package / STAMP).read_text(encoding="utf-8").split()
    except OSError:
        return None
    return (words[0], words[1], words[2]) if len(words) == 3 else None


def _version() -> str:
    """pyproject.toml first: an installed copy's metadata lags a pull until the venv is synced."""
    if _STAMPED is not None:
        return _STAMPED[0]
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
    except PackageNotFoundError:
        return "0.0.0+unknown"


_STAMPED = _stamped(Path(__file__).resolve().parent)
__version__ = _version()


def _commit() -> str:
    git = Path(__file__).resolve().parents[2] / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:7]
        ref = head.removeprefix("ref: ")
        if (git / ref).is_file():
            return (git / ref).read_text(encoding="utf-8").strip()[:7]
        for line in (git / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(f" {ref}"):
                return line[:7]
    except OSError:
        pass
    return ""


# PRs #1–#35 had 336 commits before squash merges made each one.
_SQUASHED = 336 - 35


def _build_number(root: Path, commit: str) -> str:
    """Cached in .git per commit: git can take seconds on a cold start."""
    import contextlib
    import subprocess

    kept = root / ".git" / "capypanel-build"
    try:
        was, _space, number = kept.read_text(encoding="utf-8").strip().partition(" ")
        if was == commit and number.isdigit():
            return number
    except OSError:
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
    with contextlib.suppress(OSError):
        kept.write_text(f"{commit} {number}", encoding="utf-8")
    return number


if _STAMPED is not None:
    _NUMBER, _COMMIT = _STAMPED[1], _STAMPED[2]
else:
    _COMMIT = _commit()
    _NUMBER = _build_number(Path(__file__).resolve().parents[2], _COMMIT) if _COMMIT else ""
BUILD = (
    f"{__version__} build {_NUMBER} ({_COMMIT})" if _NUMBER
    else f"{__version__} ({_COMMIT})" if _COMMIT
    else __version__
)  # fmt: skip
