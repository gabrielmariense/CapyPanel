"""Updates from GitHub Releases: is there a newer CapyPanel, get its zip, check it against its
SHA-256, and swap it in once CapyPanel has closed, keeping the old folder to go back to.

Nothing here runs on its own: the UI decides when to look and asks before installing. Only the
packaged CapyPanel.exe installs updates; a copy run from source is updated with git.

The download, the unpacked new version and the old version kept to go back to live in this
Windows user's own app data (the "CapyPanel/update" folder in %LOCALAPPDATA%, a folder per copy
of CapyPanel), never in or beside CapyPanel's folder, and they're deleted once the new version is
running. The swap is done by the new version's own exe, started from where the zip was
unpacked, with `--apply-update`. It waits for the running CapyPanel to end, moves the old
version's files out one by one (the folder itself stays: Windows won't rename a folder Explorer
has open), copies the new ones in,
leaves a portable copy's own data where it is, and runs the new exe's self-test unless the
running CapyPanel already ran it on the unpacked copy before closing. If any of
that fails, the old files are put back as they were. While it works, a marker beside it tells a
CapyPanel started meanwhile to end at once instead of holding files. Settings, lists and
saved logins live outside the app's folder (ProgramData and Credential Manager), so they're
never touched."""

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from capypanel.core import files, winsec
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
NO_SPLASH = "PYINSTALLER_SUPPRESS_SPLASH_SCREEN"  # the exe's jobs show no splash, CapyPanel does
TESTED = "tested"  # in the staging folder: the version whose unpacked copy passed its self-test
APPLYING = "applying"  # in the staging folder while the helper swaps: its process id
APPLYING_FOR = 300  # seconds: a marker older than this is a leftover, never obeyed


def _env(*, splash: bool) -> dict[str, str]:
    env = dict(os.environ)
    if splash:
        env.pop(NO_SPLASH, None)
    else:
        env[NO_SPLASH] = "1"
    return env


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


def notes_in(notes: str, language: str) -> str:
    """The part of a release's notes under "## <language>", the language named in itself as
    i18n.LANGUAGES has it ("## English", "## Português (Brasil)"), without that heading; all
    of the notes when they have no such part."""
    lines = notes.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        if start is not None:  # the next language's part ends this one
            return "\n".join(lines[start:i]).strip()
        if line[3:].strip() == language:
            start = i + 1
    return "\n".join(lines[start:]).strip() if start is not None else notes


# ---- how often CapyPanel looks: one choice for everyone on this PC ----

CHECK_FILE = "_updates.json"  # beside _reads.json, in the folder for everyone on this PC
AT_START, DAILY, WEEKLY, OFF = "start", "daily", "weekly", "off"
CHECKS = (AT_START, DAILY, WEEKLY, OFF)
WAIT = {AT_START: timedelta(days=1), DAILY: timedelta(days=1), WEEKLY: timedelta(days=7)}


def check_of(folder: Path) -> str:
    """How often CapyPanel looks for a new version on this PC: at every start unless someone
    trusted chose otherwise. An update replaces CapyPanel for everyone here, so it's one choice
    for all of them; another user's file must not turn it off."""
    path = folder / CHECK_FILE
    if not path.is_file() or not winsec.made_by_trusted(path):
        return AT_START
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return AT_START
    how = data.get("check") if isinstance(data, dict) else None
    return how if how in CHECKS else AT_START


def set_check(folder: Path, how: str) -> None:
    """Sets it for everyone on this PC; at every start, the default, removes the file. Raises
    OSError where this user can't write the folder."""
    if how not in CHECKS:
        raise ValueError(how)
    path = folder / CHECK_FILE
    if how == AT_START:
        path.unlink(missing_ok=True)
        return
    if not folder.is_dir():
        files.make_shared_folder(folder)
    files.write_json(path, {"schema": 1, "check": how})


# ---- asking GitHub ----


def _tls() -> ssl.SSLContext:
    """Python's checks of GitHub's certificate, against the certificates Windows trusts, with
    the host name. Python 3.13 also turned on X.509 strict mode, which refuses chains that
    browsers and Windows accept, e.g. a company's own authority missing a key identifier
    ("Missing Authority Key Identifier"): that mode alone is turned off."""
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _open(url: str, timeout: float) -> object:
    """A GET to `url`; refuses anything but https to GitHub, also after redirects."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise UpdateError(_("Not an https address: {url}").format(url=url))
    request = urllib.request.Request(  # noqa: S310 -- https only, checked above
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    )
    try:
        response = urllib.request.urlopen(  # noqa: S310 -- https only, checked above
            request, timeout=timeout, context=_tls()
        )
    except urllib.error.HTTPError as e:
        raise UpdateError(
            _("GitHub answered {code} {reason}").format(code=e.code, reason=e.reason), e.code
        ) from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(_("Couldn't reach GitHub: {reason}").format(reason=reason)) from e
    landed = urllib.parse.urlsplit(response.geturl())  # after any redirect
    host = landed.hostname or ""
    if landed.scheme != "https" or host not in TRUSTED_HOSTS:
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
    staging: Path  # in app data: the download and the unpacked new version
    previous: Path  # in app data: the old version while the new one is checked

    @property
    def new_app(self) -> Path:
        return self.staging / APP


def mark_tested(place: Places, version: str) -> None:
    """The unpacked `version` passed its self-test: the helper needn't run it again."""
    (place.staging / TESTED).write_text(version, encoding="utf-8")


def was_tested(place: Places, version: str) -> bool:
    try:
        return (place.staging / TESTED).read_text(encoding="utf-8").strip() == version
    except OSError:
        return False


def applying(app_dir: Path) -> bool:
    """Whether an update's helper is swapping this folder's files right now: a CapyPanel
    started meanwhile ends at once, so it holds no file the swap has to move."""
    app = app_dir.resolve()
    return any(_marked(folder / APPLYING) for folder in (places(app).staging, _legacy(app)[0]))


def _marked(marker: Path) -> bool:
    try:
        pid = int(marker.read_text(encoding="utf-8"))
        age = time.time() - marker.stat().st_mtime
    except (OSError, ValueError):
        return False
    # A swap takes seconds: an old marker is one a helper never got to remove, and its process
    # id may belong to something else by now. CapyPanel must never be kept from starting.
    return age < APPLYING_FOR and pid != os.getpid() and not wait_for_exit(pid, 0)


def work_root(app: Path) -> Path:
    """This copy of CapyPanel's update folder in the person's app data: one per folder it runs
    from, so a portable copy and an installed one never share it."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    key = hashlib.sha256(str(app).lower().encode("utf-8")).hexdigest()[:12]
    return Path(base) / APP / "update" / key


def places(app_dir: Path, staging: Path | None = None) -> Places:
    """Where an update works. `staging`: where the helper actually runs from, when an older
    version's updater unpacked it somewhere else (beside CapyPanel's folder until 0.26.3)."""
    app = app_dir.resolve()
    root = work_root(app)
    return Places(app, staging or root / "new", root / "previous")


def _legacy(app: Path) -> tuple[Path, Path]:
    """Where 0.26.0 to 0.26.3 put the same folders: beside CapyPanel's own."""
    return app.with_name(f"{app.name}.update"), app.with_name(f"{app.name}.previous")


def cannot_install(app_dir: Path) -> str:
    """Why an update can't be installed here, or "": CapyPanel's own folder must take new files
    (a copy under Program Files, say, can't without admin rights)."""
    try:
        with tempfile.TemporaryFile(dir=app_dir.resolve()):
            pass
    except OSError:
        return _("CapyPanel can't write to {folder}").format(folder=app_dir.resolve())
    return ""


def _drop_empty(root: Path) -> None:
    """This copy's update folder and "update" above it, when nothing is left in them."""
    for folder in (root, root.parent):
        try:
            folder.rmdir()  # only an empty folder: anything else stays
        except OSError:
            return


CLEAN_TRIES = 15  # one a second: the helper that started this copy ends within a few


def clean_up(app_dir: Path, tries: int = CLEAN_TRIES, pause: float = 1.0) -> None:
    """At every start, on a thread of its own: what an update left (the unpacked download, the
    old version), in app data and where 0.26.0 to 0.26.3 put it beside CapyPanel's folder.
    Never while a swap is under way. Right after an update the helper still runs from the
    download for a moment, so a folder that won't go yet is tried again."""
    if applying(app_dir):
        return
    place = places(app_dir)
    left = [f for f in (place.staging, place.previous, *_legacy(place.app)) if f.is_dir()]
    for attempt in range(tries):
        for folder in left:
            shutil.rmtree(folder, ignore_errors=True)
        gone = [f for f in left if not f.exists()]
        for folder in gone:
            log.info("Update: removed %s", folder)
        left = [f for f in left if f.exists()]
        if not left:
            _drop_empty(work_root(place.app))
            return
        if attempt < tries - 1:
            time.sleep(pause)
    for folder in left:
        log.info("Update: couldn't remove all of %s yet: at the next start", folder)


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
            env=_env(splash=False),
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
    test: Callable[[Path], bool] | None = self_test,
) -> None:
    """The new version (in place.new_app) where the old one was. Raises UpdateError with the old
    version's files back as they were when anything fails. `test`: None when the unpacked copy
    already passed it. The exe goes out first and comes in last, so for the moment the folder is
    half there, it can't be started."""
    if not wait(pid, 120):
        raise UpdateError(_("CapyPanel didn't close"))
    if place.previous.exists():
        shutil.rmtree(place.previous)
    place.previous.mkdir(parents=True)
    moved: list[str] = []  # the old version's, now in place.previous
    copied: list[str] = []  # the new version's, now in place.app
    try:
        for item in _ours(place.app):
            _retry(lambda item=item: shutil.move(item, place.previous / item.name),
                   f"moved {item.name}")  # fmt: skip
            moved.append(item.name)
        for item in sorted(place.new_app.iterdir(), key=lambda item: item.name == EXE):
            if item.name in KEEP:
                continue  # never shipped, but never let a zip replace a portable copy's data
            copied.append(item.name)
            if item.is_dir():
                shutil.copytree(item, place.app / item.name)
            else:
                shutil.copy2(item, place.app / item.name)
        if test is not None and not test(place.app / EXE):
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
    """What the version owns in its folder, the exe first: everything but a portable copy's
    own data."""
    owned = [item for item in app.iterdir() if item.name not in KEEP]
    return sorted(owned, key=lambda item: item.name != EXE)


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
        _retry(lambda source=source: shutil.move(source, place.app / source.name),
               f"put back {name}")  # fmt: skip
    shutil.rmtree(place.previous, ignore_errors=True)


def start(exe: Path, *args: str, splash: bool = True) -> None:
    """`exe`, on its own: it outlives the process that starts it. `splash`: whether its launcher
    shows the splash (CapyPanel starting again does; the helper doesn't)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    subprocess.Popen(  # noqa: S603 -- our own exe, by full path
        [str(exe), *args],
        cwd=exe.parent,
        creationflags=flags,
        close_fds=True,
        env=_env(splash=splash),
    )


def run_helper(
    app_dir: Path, pid: int, old_version: str, new_version: str, staging: Path | None = None
) -> int:
    """`CapyPanel.exe --apply-update <app folder> <pid> <old> <new>`, from the unpacked new
    version: the swap, then CapyPanel started again, new or old. Logs to the person's log.
    `staging`: the folder the helper runs from (its exe's folder's parent)."""
    place = places(app_dir, staging)
    marker = place.staging / APPLYING
    try:
        marker.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        log.warning("Update: couldn't write %s", marker)
    tested = was_tested(place, new_version)
    try:
        apply(place, pid, test=None if tested else self_test)
    except Exception as e:  # noqa: BLE001 -- whatever it was, CapyPanel starts again
        log.exception("Update to %s failed", new_version)
        why = str(e) if isinstance(e, UpdateError) else f"{type(e).__name__}: {e}"
        marker.unlink(missing_ok=True)
        if (place.app / EXE).exists():
            start(place.app / EXE, FAILED_FLAG, new_version, why)
        return 1
    log.info("Update: %s replaced %s in %s", new_version, old_version, place.app)
    shutil.rmtree(place.previous, ignore_errors=True)  # it passed its self-test: no way back needed
    marker.unlink(missing_ok=True)
    start(place.app / EXE, UPDATED_FLAG, old_version)
    return 0


def helper_args(app_dir: Path, pid: int, old_version: str, new_version: str) -> list[str]:
    """How the running CapyPanel starts the helper, from the unpacked new version."""
    return [str(places(app_dir).new_app / EXE), APPLY_FLAG, str(app_dir.resolve()), str(pid),
            old_version, new_version]  # fmt: skip


def own_pid() -> int:
    return os.getpid()
