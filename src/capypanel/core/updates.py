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
APP = "CapyPanel"
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
NO_SPLASH = "PYINSTALLER_SUPPRESS_SPLASH_SCREEN"
TESTED = "tested"
APPLYING = "applying"
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
    def __init__(self, text: str, status: int = 0) -> None:
        super().__init__(text)
        self.status = status


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page_url: str
    zip_url: str
    sha_url: str
    zip_name: str
    zip_size: int


def parse_version(text: str) -> tuple[int, int, int] | None:
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
    lines = notes.splitlines()
    start: int | None = None
    for i, line in enumerate(lines):
        if not line.startswith("## "):
            continue
        if start is not None:
            return "\n".join(lines[start:i]).strip()
        if line[3:].strip() == language:
            start = i + 1
    return "\n".join(lines[start:]).strip() if start is not None else notes


CHECK_FILE = "_updates.json"
AT_START, DAILY, WEEKLY, OFF = "start", "daily", "weekly", "off"
CHECKS = (AT_START, DAILY, WEEKLY, OFF)
WAIT = {AT_START: timedelta(days=1), DAILY: timedelta(days=1), WEEKLY: timedelta(days=7)}


def check_of(folder: Path) -> str:
    """At every start unless someone trusted chose otherwise: another user's file can't."""
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
    if how not in CHECKS:
        raise ValueError(how)
    path = folder / CHECK_FILE
    if how == AT_START:
        path.unlink(missing_ok=True)
        return
    if not folder.is_dir():
        files.make_shared_folder(folder)
    files.write_json(path, {"schema": 1, "check": how})


def _tls() -> "ssl.SSLContext":
    """Windows checks GitHub's certificate (truststore): Python's fails without the root stored."""
    # Imported here: truststore asks WMI at import, about 50 ms of every start.
    import ssl

    import truststore

    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _open(url: str, timeout: float) -> object:
    """A GET to `url`; refuses anything but https to GitHub, also after redirects."""
    import urllib.error
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
    landed = urllib.parse.urlsplit(response.geturl())
    host = landed.hostname or ""
    if landed.scheme != "https" or host not in TRUSTED_HOSTS:
        response.close()
        raise UpdateError(_("The download went to an unexpected address: {host}").format(host=host))
    return response


def latest(timeout: float = 15) -> Release | None:
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
    """Refuses a zip with anything outside one CapyPanel folder, or without CapyPanel.exe."""
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


@dataclass(frozen=True)
class Places:
    app: Path
    staging: Path
    previous: Path

    @property
    def new_app(self) -> Path:
        return self.staging / APP


def mark_tested(place: Places, version: str) -> None:
    (place.staging / TESTED).write_text(version, encoding="utf-8")


def was_tested(place: Places, version: str) -> bool:
    try:
        return (place.staging / TESTED).read_text(encoding="utf-8").strip() == version
    except OSError:
        return False


def applying(app_dir: Path) -> bool:
    """A CapyPanel started during a swap ends at once, so it holds no file the swap must move."""
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
    """One per folder it runs from: a portable copy and an installed one never share it."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    key = hashlib.sha256(str(app).lower().encode("utf-8")).hexdigest()[:12]
    return Path(base) / APP / "update" / key


def places(app_dir: Path, staging: Path | None = None) -> Places:
    """`staging`: where an older updater unpacked the helper (beside CapyPanel until 0.26.3)."""
    app = app_dir.resolve()
    root = work_root(app)
    return Places(app, staging or root / "new", root / "previous")


def _legacy(app: Path) -> tuple[Path, Path]:
    return app.with_name(f"{app.name}.update"), app.with_name(f"{app.name}.previous")


def cannot_install(app_dir: Path) -> str:
    try:
        with tempfile.TemporaryFile(dir=app_dir.resolve()):
            pass
    except OSError:
        return _("CapyPanel can't write to {folder}").format(folder=app_dir.resolve())
    return ""


def _drop_empty(root: Path) -> None:
    for folder in (root, root.parent):
        try:
            folder.rmdir()  # only an empty folder: anything else stays
        except OSError:
            return


CLEAN_TRIES = 15  # one a second


def clean_up(app_dir: Path, tries: int = CLEAN_TRIES, pause: float = 1.0) -> None:
    """Also where 0.26.0 to 0.26.3 put it; never during a swap."""
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
        pass


def remove(folder: Path) -> None:
    shutil.rmtree(folder, onexc=_writable)


def _empty_folder(folder: Path) -> Path:
    if folder.exists():
        remove(folder)
    fresh, n = folder, 1
    while fresh.exists():
        n += 1
        fresh = folder.with_name(f"{folder.name}-{n}")
    fresh.mkdir(parents=True)
    return fresh


def wait_for_exit(pid: int, timeout: float) -> bool:
    synchronize, wait_object_0 = 0x00100000, 0
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True
    try:
        return (
            kernel32.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout * 1000))
            == wait_object_0
        )
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(handle))


def self_test(exe: Path, timeout: float = 240) -> bool:
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
    """Windows can refuse a move for a moment (an antivirus scanning the folder): tried again."""
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


CHECKING = ".update-check"


def _not_moved(error: OSError) -> UpdateError:
    return UpdateError(_("Couldn't put the new version in place: {error}").format(error=error))


def _check(item: Path) -> None:
    """Renamed and straight back: fails while a file in it is held without delete sharing."""
    beside, n = item.with_name(item.name + CHECKING), 1
    while beside.exists():
        n += 1
        beside = item.with_name(f"{item.name}{CHECKING}-{n}")
    os.rename(item, beside)
    try:
        _retry(lambda: os.rename(beside, item), "")
    except OSError as e:
        log.error("Update: %s is still named %s", item, beside)
        raise _not_moved(e) from e


def _copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target)


def _discard(path: Path) -> None:
    if path.is_dir():
        remove(path)
    else:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _clear(item: Path) -> None:
    _discard(item)
    if item.exists() or item.is_symlink():
        raise OSError(errno.EBUSY, "Still in use", str(item))


def _strict(function: Callable[[str], object], path: str, error: BaseException) -> None:
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _delete(item: Path) -> None:
    if item.is_dir() and not item.is_symlink():
        shutil.rmtree(item, onexc=_strict)
        return
    try:
        item.unlink()
    except PermissionError:
        os.chmod(item, stat.S_IWRITE)
        item.unlink()


def _fill_in(copy: Path, original: Path) -> None:
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
    """Whole or not at all: a rename on one drive. Across drives a copy, and a delete that
    stops is filled back in."""
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
    """The exe goes out first and in last, so a half-swapped folder can't be started."""
    if not wait(pid, 120):
        raise UpdateError(_("CapyPanel didn't close"))
    try:
        place = replace(place, previous=_empty_folder(place.previous))
    except OSError as e:
        raise _not_moved(e) from e
    moved: list[str] = []
    copied: list[str] = []
    try:
        ours = _ours(place.app)
        for item in ours:
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
    owned = [item for item in app.iterdir() if item.name not in KEEP]
    return sorted(owned, key=lambda item: item.name != EXE)


def _roll_back(place: Places, moved: list[str], copied: list[str]) -> None:
    """The exe last; the old folder goes only once empty: what couldn't come back stays."""
    log.warning("Update: going back to the old version")
    for name in copied:
        try:
            _retry(lambda item=place.app / name: _clear(item), f"took out the new {name}")
        except OSError:
            log.exception("Update: couldn't take out the new %s", name)
    for name in reversed(moved):
        source, target = place.previous / name, place.app / name
        if target.exists():
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
    remove(previous)
    marker.unlink(missing_ok=True)
    start(place.app / EXE, UPDATED_FLAG, old_version)
    return 0


def helper_args(app_dir: Path, pid: int, old_version: str, new_version: str) -> list[str]:
    return [str(places(app_dir).new_app / EXE), APPLY_FLAG, str(app_dir.resolve()), str(pid),
            old_version, new_version]  # fmt: skip


def own_pid() -> int:
    return os.getpid()
