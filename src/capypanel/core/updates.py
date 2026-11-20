"""Updates from GitHub Releases: find a newer CapyPanel, fetch and check its zip, and swap it in
once CapyPanel has closed, never losing the old files. Only the packaged exe installs updates."""

import contextlib
import ctypes
import errno
import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from capypanel.core import files, winsec
from capypanel.core.i18n import _
from capypanel.core.settings import PORTABLE_MARKER

if TYPE_CHECKING:
    import ssl

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
    page_url: str
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
    """The part of a release's notes under "## <language>", named as i18n.LANGUAGES has it
    ("## Português (Brasil)"), without that heading; all of the notes when there's no such part."""
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
    """How often CapyPanel looks for updates, one choice for this whole PC: at every start unless
    someone trusted chose otherwise, so another user's file can't turn it off."""
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


def _tls() -> "ssl.SSLContext":
    """GitHub's certificate checked by Windows itself (truststore), as Edge checks it: Python's own
    check fails on PCs whose store lacks the root and refuses chains browsers accept."""
    # Loaded here, not with the module: importing truststore asks Windows (WMI) which system
    # it runs on, about 50 ms of every start otherwise.
    import ssl

    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _open(url: str, timeout: float) -> object:
    """A GET to `url`; refuses anything but https to GitHub, also after redirects."""
    import urllib.error  # with urllib.request: only when CapyPanel asks GitHub something
    import urllib.parse
    import urllib.request

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
    """What an update left, in app data and where 0.26.0 to 0.26.3 put it: removed at every start,
    never during a swap. A folder the helper that just ended still holds is tried again."""
    if applying(app_dir):
        return
    place = places(app_dir)
    olds = sorted(place.previous.parent.glob(f"{place.previous.name}*"))
    left = [f for f in (place.staging, *olds, *_legacy(place.app)) if f.is_dir()]
    for attempt in range(tries):
        for folder in left:
            remove(folder)
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


def _writable(function: Callable[[str], object], path: str, _error: BaseException) -> None:
    """rmtree's second try on a read-only file: Windows won't delete one until it's writable."""
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        pass  # held by another program: it stays, and the next start tries again


def remove(folder: Path) -> None:
    """`folder` and what's in it, as far as Windows lets: never raises."""
    shutil.rmtree(folder, onexc=_writable)


def _empty_folder(folder: Path) -> Path:
    """`folder`, empty, for the old version; a new folder beside it when a file left in it won't go
    (held by another program): a leftover never stops an update. The next start clears both."""
    if folder.exists():
        remove(folder)
    fresh, n = folder, 1
    while fresh.exists():
        n += 1
        fresh = folder.with_name(f"{folder.name}-{n}")
    fresh.mkdir(parents=True)
    return fresh


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
    """A move Windows can refuse for a moment (an antivirus scanning the folder): tried again.
    `what` goes to the log once it worked ("" for nothing)."""
    for attempt in range(attempts):
        try:
            action()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)
        else:
            if what:
                log.info("Update: %s", what)
            return


CHECKING = ".update-check"  # what an item of the old version is renamed to, for a moment


def _not_moved(error: OSError) -> UpdateError:
    return UpdateError(_("Couldn't put the new version in place: {error}").format(error=error))


def _check(item: Path) -> None:
    """Raises OSError when Windows won't let `item` move whole (a file in it held open without
    delete sharing). Renamed beside itself and straight back: nothing has changed when it raises."""
    beside, n = item.with_name(item.name + CHECKING), 1
    while beside.exists():  # a leftover never stops an update
        n += 1
        beside = item.with_name(f"{item.name}{CHECKING}-{n}")
    os.rename(item, beside)
    try:
        _retry(lambda: os.rename(beside, item), "")
    except OSError as e:  # all but impossible: it can't be renamed back
        log.error("Update: %s is still named %s", item, beside)
        raise _not_moved(e) from e


def _copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def _discard(path: Path) -> None:
    """A copy nothing needs any more, as far as Windows lets: never raises."""
    if path.is_dir():
        remove(path)
    else:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _clear(item: Path) -> None:
    """`item` gone, or OSError while any of it is still there (an antivirus scanning a file just
    copied in, say), for _retry to try again."""
    _discard(item)
    if item.exists() or item.is_symlink():
        raise OSError(errno.EBUSY, "Still in use", str(item))


def _strict(function: Callable[[str], object], path: str, error: BaseException) -> None:
    """rmtree's second try on a read-only file; anything else stops the delete there."""
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE)
    function(path)  # raises again when another program holds it


def _delete(item: Path) -> None:
    """`item`, deleted up to the first file Windows won't let go."""
    if item.is_dir() and not item.is_symlink():
        shutil.rmtree(item, onexc=_strict)
        return
    try:
        item.unlink()
    except PermissionError:
        os.chmod(item, stat.S_IWRITE)
        item.unlink()


def _fill_in(copy: Path, original: Path) -> None:
    """What a stopped delete took from `original` back from `copy`; what it left stays."""
    if not copy.is_dir():
        if not original.exists():
            shutil.copy2(copy, original)
        return
    for folder, _folders, names in os.walk(copy):
        here = original / Path(folder).relative_to(copy)
        here.mkdir(parents=True, exist_ok=True)
        for name in names:
            if not (here / name).exists():
                shutil.copy2(Path(folder) / name, here / name)


def _move_out(item: Path, target: Path) -> None:
    """One item of the old version to `target`, whole or not at all: a rename on the same drive (a
    refusal is for _retry); on another drive a copy, then a stopped delete is filled back in."""
    try:
        os.rename(item, target)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    try:
        _copy(item, target)
    except OSError as e:
        _discard(target)  # only our part copy: the original hasn't been touched
        raise _not_moved(e) from e
    try:
        _delete(item)
    except OSError as e:
        try:
            _fill_in(target, item)
        except OSError:
            log.exception("Update: %s is missing files; all of them are in %s", item, target)
            raise _not_moved(e) from e  # the copy stays: it's the only whole one
        _discard(target)
        raise _not_moved(e) from e


def _put_back(source: Path, target: Path) -> None:
    """An item of the old version back where it was: a rename on the same drive; on another
    drive a copy, and then the one in the old version's folder goes, as far as Windows lets."""
    try:
        os.rename(source, target)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    _copy(source, target)
    _discard(source)


def apply(
    place: Places,
    pid: int,
    *,
    wait: Callable[[int, float], bool] = wait_for_exit,
    test: Callable[[Path], bool] | None = self_test,
) -> Path:
    """Swaps in the new version; returns where the old one went. Raises UpdateError with the old
    files back. The exe goes out first and in last, so a half-swapped folder can't be started."""
    if not wait(pid, 120):
        raise UpdateError(_("CapyPanel didn't close"))
    try:
        place = replace(place, previous=_empty_folder(place.previous))
    except OSError as e:
        raise _not_moved(e) from e
    moved: list[str] = []  # the old version's, now in place.previous
    copied: list[str] = []  # the new version's, now in place.app
    try:
        ours = _ours(place.app)
        for item in ours:  # a file held open stops the update here, with nothing changed
            _retry(lambda item=item: _check(item), f"{item.name} can move")
        for item in ours:
            _retry(lambda item=item: _move_out(item, place.previous / item.name),
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
        raise _not_moved(e) from e
    log.info("Update: the new version is in place and passed its self-test")
    return place.previous


def _ours(app: Path) -> list[Path]:
    """What the version owns in its folder, the exe first: all but a portable copy's own data."""
    owned = [item for item in app.iterdir() if item.name not in KEEP]
    return sorted(owned, key=lambda item: item.name != EXE)


def _roll_back(place: Places, moved: list[str], copied: list[str]) -> None:
    """Exactly what the swap did, undone, the exe last. The old version's folder goes only once
    it's empty: what couldn't come back stays in it, never deleted, and the log says where."""
    log.warning("Update: going back to the old version")
    for name in copied:  # tried again, as the moves are: a held new file keeps the old one out
        try:
            _retry(lambda item=place.app / name: _clear(item), f"took out the new {name}")
        except OSError:
            log.exception("Update: couldn't take out the new %s", name)
    for name in reversed(moved):
        source, target = place.previous / name, place.app / name
        if target.exists():  # a new file that wouldn't go: the old one can't come back over it
            log.error("Update: %s couldn't be cleared; the old one stays in %s", target, source)
            continue
        try:
            _retry(lambda source=source, target=target: _put_back(source, target),
                   f"put back {name}")  # fmt: skip
        except OSError:
            log.exception("Update: couldn't put back %s; it stays in %s", name, source)
    try:
        place.previous.rmdir()  # only an empty folder
    except OSError:
        log.error("Update: %s isn't empty, so it stays", place.previous)


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
    """`CapyPanel.exe --apply-update <app> <pid> <old> <new>`, run from the unpacked new version:
    the swap, then CapyPanel started again, new or old. `staging`: the folder it runs from."""
    place = places(app_dir, staging)
    marker = place.staging / APPLYING
    try:
        marker.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        log.warning("Update: couldn't write %s", marker)
    tested = was_tested(place, new_version)
    try:
        previous = apply(place, pid, test=None if tested else self_test)
    except Exception as e:  # noqa: BLE001 -- whatever it was, CapyPanel starts again
        log.exception("Update to %s failed", new_version)
        why = str(e) if isinstance(e, UpdateError) else f"{type(e).__name__}: {e}"
        marker.unlink(missing_ok=True)
        if (place.app / EXE).exists():
            start(place.app / EXE, FAILED_FLAG, new_version, why)
        return 1
    log.info("Update: %s replaced %s in %s", new_version, old_version, place.app)
    remove(previous)  # it passed its self-test: no way back needed
    marker.unlink(missing_ok=True)
    start(place.app / EXE, UPDATED_FLAG, old_version)
    return 0


def helper_args(app_dir: Path, pid: int, old_version: str, new_version: str) -> list[str]:
    """How the running CapyPanel starts the helper, from the unpacked new version."""
    return [str(places(app_dir).new_app / EXE), APPLY_FLAG, str(app_dir.resolve()), str(pid),
            old_version, new_version]  # fmt: skip


def own_pid() -> int:
    return os.getpid()
