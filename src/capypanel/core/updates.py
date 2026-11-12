"""Updates from GitHub Releases: is there a newer CapyPanel, get its zip, check it against its
SHA-256, and swap it in once CapyPanel has closed, keeping the old folder to go back to.

Nothing here runs on its own: the UI decides when to look and asks before installing. Only the
packaged CapyPanel.exe installs updates; a copy run from source is updated with git.

The swap is done by the new version's own exe, started from where the zip was unpacked
(`<folder>.update` beside CapyPanel's folder) with `--apply-update`. It waits for the running
CapyPanel to end, moves the old version's files aside into `<folder>.previous` one by one (the
folder itself stays: Windows won't rename a folder Explorer has open), copies the new ones in,
leaves a portable copy's own data where it is, and runs the new exe's self-test. If any of
that fails, the old files are put back as they were. Settings, lists and
saved logins live outside the app's folder (ProgramData and Credential Manager), so they're
never touched."""

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from capypanel.core.i18n import _
from capypanel.core.settings import PORTABLE_MARKER

log = logging.getLogger(__name__)

REPO = "gabrielmariense/CapyPanel"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
APP = "CapyPanel"  # the folder inside the zip, and the exe's name
EXE = f"{APP}.exe"
# Where GitHub serves a release and its files from; a download that ends anywhere else stops.
TRUSTED_HOSTS = frozenset({
    "api.github.com", "github.com", "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})  # fmt: skip
MAX_ZIP = 300 * 1024 * 1024  # today's zip is under 40 MB
CHUNK = 256 * 1024
USER_AGENT = "CapyPanel-updater"  # GitHub asks for one; it names the program, nobody's details
KEEP = (PORTABLE_MARKER, "userdata")  # a portable copy's own data: carried over, never replaced
APPLY_FLAG, UPDATED_FLAG, FAILED_FLAG = "--apply-update", "--updated-from", "--update-failed"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


class UpdateError(Exception):
    """Why an update couldn't be checked, fetched or installed, in words for people; `status`,
    GitHub's HTTP answer when it gave one."""

    def __init__(self, text: str, status: int = 0) -> None:
        super().__init__(text)
        self.status = status


@dataclass(frozen=True)
class Release:
    version: str  # "0.26.1"
    notes: str  # the release's text, Markdown
    page_url: str  # the release's page on GitHub
    zip_url: str
    sha_url: str
    zip_name: str
    zip_size: int


def parse_version(text: str) -> tuple[int, int, int] | None:
    """(0, 26, 1) from "0.26.1" or "v0.26.1"; None for anything else, a pre-release too."""
    found = _VERSION.fullmatch(text.strip())
    if found is None:
        return None
    major, minor, patch = (int(n) for n in found.groups())
    return major, minor, patch


def is_newer(release: Release, current: str) -> bool:
    theirs, ours = parse_version(release.version), parse_version(current)
    return theirs is not None and ours is not None and theirs > ours


def zip_name(version: str) -> str:
    return f"{APP}-{version}-windows-x64.zip"


# ---- asking GitHub ----


def _open(url: str, timeout: float) -> object:
    """A GET to `url`; refuses anything but https to GitHub, also after redirects."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError(_("Not an https address: {url}").format(url=url))
    request = urllib.request.Request(  # noqa: S310 -- https only, checked above
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
    except urllib.error.HTTPError as e:
        raise UpdateError(
            _("GitHub answered {code} {reason}").format(code=e.code, reason=e.reason), e.code
        ) from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(_("Couldn't reach GitHub: {reason}").format(reason=reason)) from e
    host = urllib.parse.urlsplit(response.geturl()).hostname or ""
    if host not in TRUSTED_HOSTS:
        response.close()
        raise UpdateError(_("The download went to an unexpected address: {host}").format(host=host))
    return response


def latest(timeout: float = 15) -> Release | None:
    """The newest published release, or None when it carries no zip for Windows (being
    uploaded, say). Drafts and pre-releases are never offered. Raises UpdateError."""
    try:
        response = _open(LATEST_URL, timeout)
    except UpdateError as e:
        if e.status == 404:  # no release published yet
            return None
        raise
    try:
        data = json.loads(response.read(2 * 1024 * 1024))  # type: ignore[attr-defined]
    except ValueError as e:
        raise UpdateError(_("GitHub's answer wasn't readable")) from e
    finally:
        response.close()  # type: ignore[attr-defined]
    return release_from(data)


def release_from(data: object) -> Release | None:
    """A Release from GitHub's JSON for one release."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        return None
    version = tag.lstrip("v")
    name = zip_name(version)
    assets = {
        str(a.get("name")): a for a in data.get("assets") or [] if isinstance(a, dict)
    }  # fmt: skip
    archive, digest = assets.get(name), assets.get(f"{name}.sha256")
    if archive is None or digest is None:
        return None
    return Release(
        version=version,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or RELEASES_URL),
        zip_url=str(archive.get("browser_download_url") or ""),
        sha_url=str(digest.get("browser_download_url") or ""),
        zip_name=name,
        zip_size=int(archive.get("size") or 0),
    )


def download(
    url: str,
    to: Path,
    *,
    progress: Callable[[int, int], None] = lambda _done, _total: None,
    cancelled: Callable[[], bool] = lambda: False,
    limit: int = MAX_ZIP,
    timeout: float = 30,
) -> None:
    """`url` into the file `to`, reporting (bytes so far, total or 0). Raises UpdateError,
    also when cancelled; a part-written file is removed."""
    response = _open(url, timeout)
    total = int(response.headers.get("Content-Length") or 0)  # type: ignore[attr-defined]
    if total > limit:
        response.close()  # type: ignore[attr-defined]
        raise UpdateError(_("The download is far bigger than CapyPanel ever is"))
    done = 0
    try:
        with response, to.open("wb") as file:  # type: ignore[attr-defined]
            while block := response.read(CHUNK):  # type: ignore[attr-defined]
                if cancelled():
                    raise UpdateError(_("Cancelled."))
                done += len(block)
                if done > limit:
                    raise UpdateError(_("The download is far bigger than CapyPanel ever is"))
                file.write(block)
                progress(done, total)
    except (OSError, UpdateError) as e:
        to.unlink(missing_ok=True)
        if isinstance(e, UpdateError):
            raise
        raise UpdateError(_("The download stopped: {error}").format(error=e)) from e


def expected_sha256(text: str, name: str) -> str:
    """The SHA-256 a .sha256 file gives for `name` ("<64 hex>  <name>", as sha256sum writes)."""
    for line in text.splitlines():
        parts = line.split()
        if (
            len(parts) == 2
            and parts[1].lstrip("*") == name
            and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0])
        ):
            return parts[0].lower()
    raise UpdateError(_("The release's SHA-256 file doesn't name its zip"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def unpack(archive: Path, into: Path) -> Path:
    """The zip's CapyPanel folder, unpacked into `into`; returns its path. Refuses a zip with
    anything outside one CapyPanel folder, or without CapyPanel.exe in it."""
    target = into.resolve()
    try:
        with zipfile.ZipFile(archive) as packed:
            names = packed.namelist()
            for name in names:
                parts = Path(name).parts
                inside = (target / name).resolve()
                if not parts or parts[0] != APP or ".." in parts or Path(name).is_absolute():
                    raise UpdateError(
                        _("The zip holds something unexpected: {name}").format(name=name)
                    )
                if not inside.is_relative_to(target):
                    raise UpdateError(
                        _("The zip holds something unexpected: {name}").format(name=name)
                    )
            if f"{APP}/{EXE}" not in names:
                raise UpdateError(_("The zip has no {exe}").format(exe=EXE))
            packed.extractall(target)
    except zipfile.BadZipFile as e:
        raise UpdateError(_("The download isn't a readable zip")) from e
    return target / APP


# ---- where things go ----


@dataclass(frozen=True)
class Places:
    app: Path  # the folder CapyPanel.exe runs from
    staging: Path  # beside it: the download and the unpacked new version
    previous: Path  # beside it: the old version while the new one is checked

    @property
    def new_app(self) -> Path:
        return self.staging / APP


def places(app_dir: Path) -> Places:
    app = app_dir.resolve()
    return Places(app, app.with_name(f"{app.name}.update"), app.with_name(f"{app.name}.previous"))


def cannot_install(app_dir: Path) -> str:
    """Why an update can't be installed here, or "": the folder beside CapyPanel's must take
    new files (a copy under Program Files, say, can't without admin rights)."""
    try:
        with tempfile.TemporaryFile(dir=app_dir.resolve().parent):
            pass
    except OSError:
        return _("CapyPanel can't write to {folder}").format(folder=app_dir.resolve().parent)
    return ""


def clean_up(app_dir: Path) -> None:
    """After a new version has started: the unpacked download and the old folder go. Whatever
    can't go yet (a helper still ending) is tried again at the next start."""
    place = places(app_dir)
    for folder in (place.staging, place.previous):
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
            log.info("Update: removed %s%s", folder, " (not all of it)" if folder.exists() else "")


# ---- the swap, run by the new version's exe ----


def wait_for_exit(pid: int, timeout: float) -> bool:
    """Whether the process `pid` has ended within `timeout` seconds (or was gone already)."""
    synchronize, wait_object_0 = 0x00100000, 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True  # no such process: it has ended
    try:
        return (
            kernel32.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout * 1000))
            == wait_object_0
        )
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def self_test(exe: Path, timeout: float = 240) -> bool:
    """Whether `exe --self-test` passes (see ui/selftest.py)."""
    report = exe.parent.with_name(f"{exe.parent.name}-self-test.txt")
    try:
        done = subprocess.run(  # noqa: S603 -- our own exe, by full path
            [str(exe), "--self-test", str(report)],
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        text = report.read_text(encoding="utf-8") if report.exists() else ""
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        report.unlink(missing_ok=True)
    if done.returncode != 0:
        log.error("Update: the new version's self-test failed:\n%s", text)
    return done.returncode == 0 and text.rstrip().endswith("SELF-TEST PASSED")


def _retry(action: Callable[[], object], what: str, attempts: int = 20) -> None:
    """A move Windows can refuse for a moment (an antivirus scanning the folder): tried again."""
    for attempt in range(attempts):
        try:
            action()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)
        else:
            log.info("Update: %s", what)
            return


def apply(
    place: Places,
    pid: int,
    *,
    wait: Callable[[int, float], bool] = wait_for_exit,
    test: Callable[[Path], bool] = self_test,
) -> None:
    """The new version (in place.new_app) where the old one was. Raises UpdateError with the old
    version's files back as they were when anything fails."""
    if not wait(pid, 120):
        raise UpdateError(_("CapyPanel didn't close"))
    if place.previous.exists():
        shutil.rmtree(place.previous)
    place.previous.mkdir()
    moved: list[str] = []  # the old version's, now in place.previous
    copied: list[str] = []  # the new version's, now in place.app
    try:
        for item in _ours(place.app):
            _retry(lambda item=item: item.rename(place.previous / item.name), f"moved {item.name}")
            moved.append(item.name)
        for item in place.new_app.iterdir():
            if item.name in KEEP:
                continue  # never shipped, but never let a zip replace a portable copy's data
            copied.append(item.name)
            if item.is_dir():
                shutil.copytree(item, place.app / item.name)
            else:
                shutil.copy2(item, place.app / item.name)
        if not test(place.app / EXE):
            raise UpdateError(_("The new version didn't pass its self-test"))
    except (OSError, UpdateError) as e:
        _roll_back(place, moved, copied)
        if isinstance(e, UpdateError):
            raise
        raise UpdateError(
            _("Couldn't put the new version in place: {error}").format(error=e)
        ) from e
    log.info("Update: the new version is in place and passed its self-test")


def _ours(app: Path) -> list[Path]:
    """What the version owns in its folder: everything but a portable copy's own data."""
    return [item for item in app.iterdir() if item.name not in KEEP]


def _roll_back(place: Places, moved: list[str], copied: list[str]) -> None:
    """Exactly what the swap did, undone: the new files out, the old ones back."""
    log.warning("Update: going back to the old version")
    for name in copied:
        item = place.app / name
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    for name in moved:
        source = place.previous / name
        _retry(lambda source=source: source.rename(place.app / source.name), f"put back {name}")
    shutil.rmtree(place.previous, ignore_errors=True)


def start(exe: Path, *args: str) -> None:
    """`exe`, on its own: it outlives the process that starts it."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(  # noqa: S603 -- our own exe, by full path
        [str(exe), *args], cwd=exe.parent, creationflags=flags, close_fds=True
    )


def run_helper(app_dir: Path, pid: int, old_version: str, new_version: str) -> int:
    """`CapyPanel.exe --apply-update <app folder> <pid> <old> <new>`, from the unpacked new
    version: the swap, then CapyPanel started again, new or old. Logs to the person's log."""
    place = places(app_dir)
    try:
        apply(place, pid)
    except Exception as e:  # noqa: BLE001 -- whatever it was, CapyPanel starts again
        log.exception("Update to %s failed", new_version)
        why = str(e) if isinstance(e, UpdateError) else f"{type(e).__name__}: {e}"
        if (place.app / EXE).exists():
            start(place.app / EXE, FAILED_FLAG, new_version, why)
        return 1
    log.info("Update: %s replaced %s in %s", new_version, old_version, place.app)
    start(place.app / EXE, UPDATED_FLAG, old_version)
    return 0


def helper_args(app_dir: Path, pid: int, old_version: str, new_version: str) -> list[str]:
    """How the running CapyPanel starts the helper, from the unpacked new version."""
    return [str(places(app_dir).new_app / EXE), APPLY_FLAG, str(app_dir.resolve()), str(pid),
            old_version, new_version]  # fmt: skip


def own_pid() -> int:
    return os.getpid()
