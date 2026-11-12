"""Updates: what counts as a newer release, the download's checks, and the swap with its way
back. Nothing reaches GitHub: the network is a fake, the folders are temporary."""

import hashlib
import io
import os
import ssl
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pytest

from capypanel.core import updates
from capypanel.core.settings import PORTABLE_MARKER
from capypanel.core.updates import Release, UpdateError

ZIP = updates.zip_name("0.26.1")


def _release_json(**more: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tag_name": "v0.26.1",
        "draft": False,
        "prerelease": False,
        "body": "## What's new\n- Updates.",
        "html_url": "https://github.com/gabrielmariense/CapyPanel/releases/tag/v0.26.1",
        "assets": [
            {"name": ZIP, "size": 38_000_000,
             "browser_download_url": f"https://github.com/x/releases/download/v0.26.1/{ZIP}"},
            {"name": f"{ZIP}.sha256", "size": 100,
             "browser_download_url": f"https://github.com/x/releases/download/v0.26.1/{ZIP}.sha256"},
        ],
    }  # fmt: skip
    data.update(more)
    return data


def test_a_release_is_offered_only_when_newer_and_complete() -> None:
    release = updates.release_from(_release_json())
    assert release is not None and release.version == "0.26.1" and release.zip_name == ZIP
    assert updates.is_newer(release, "0.26.0") and updates.is_newer(release, "0.25.9")
    assert not updates.is_newer(release, "0.26.1") and not updates.is_newer(release, "0.27.0")
    assert updates.parse_version("0.100.2") == (0, 100, 2)  # numbers, not text: 100 > 26
    assert updates.parse_version("0.27.0-rc1") is None and updates.parse_version("latest") is None
    assert updates.release_from(_release_json(draft=True)) is None
    assert updates.release_from(_release_json(prerelease=True)) is None
    assert updates.release_from(_release_json(assets=[])) is None  # files still uploading
    assert updates.release_from(_release_json(tag_name="nightly")) is None


def test_the_sha256_file_names_its_zip() -> None:
    digest = "a" * 64
    assert updates.expected_sha256(f"{digest}  {ZIP}\n", ZIP) == digest
    assert updates.expected_sha256(f"{digest.upper()} *{ZIP}", ZIP) == digest
    with pytest.raises(UpdateError):
        updates.expected_sha256(f"{digest}  other.zip", ZIP)
    with pytest.raises(UpdateError):
        updates.expected_sha256(f"not-a-hash  {ZIP}", ZIP)


def _zip(path: Path, names: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as packed:
        for name, data in names.items():
            packed.writestr(name, data)
    return path


def test_unpacking_takes_one_capypanel_folder_and_nothing_else(tmp_path: Path) -> None:
    good = _zip(tmp_path / "good.zip", {"CapyPanel/CapyPanel.exe": b"exe",
                                        "CapyPanel/_internal/x.dll": b"dll"})  # fmt: skip
    app = updates.unpack(good, tmp_path / "out")
    assert (app / "CapyPanel.exe").read_bytes() == b"exe" and (app / "_internal" / "x.dll").exists()
    for bad in (
        {"CapyPanel/CapyPanel.exe": b"", "../evil.exe": b""},  # out of the folder
        {"CapyPanel/CapyPanel.exe": b"", "CapyPanel/../../evil.exe": b""},
        {"CapyPanel/CapyPanel.exe": b"", "Other/thing.txt": b""},  # a second folder
        {"CapyPanel/readme.txt": b""},  # no exe
    ):
        with pytest.raises(UpdateError):
            updates.unpack(_zip(tmp_path / "bad.zip", bad), tmp_path / "bad")
    (tmp_path / "notzip.zip").write_bytes(b"html, not a zip")
    with pytest.raises(UpdateError):
        updates.unpack(tmp_path / "notzip.zip", tmp_path / "x")


class _Response(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self._url = url
        self.headers = {"Content-Length": str(len(data))}

    def geturl(self) -> str:
        return self._url


def test_downloads_come_only_from_github_and_stop_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = {"url": "https://objects.githubusercontent.com/file"}
    payload = b"x" * (updates.CHUNK * 3)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout, context: _Response(payload, landed["url"]),
    )
    seen: list[tuple[int, int]] = []
    updates.download(
        "https://github.com/a", tmp_path / "a.zip", progress=lambda d, t: seen.append((d, t))
    )
    assert (tmp_path / "a.zip").read_bytes() == payload and seen[-1] == (len(payload), len(payload))
    with pytest.raises(UpdateError, match="Cancelled"):
        updates.download("https://github.com/a", tmp_path / "b.zip", cancelled=lambda: True)
    assert not (tmp_path / "b.zip").exists()  # nothing half-written is left
    with pytest.raises(UpdateError, match="bigger"):
        updates.download("https://github.com/a", tmp_path / "c.zip", limit=100)
    landed["url"] = "https://example.invalid/file"  # a redirect off GitHub
    with pytest.raises(UpdateError, match="unexpected address"):
        updates.download("https://github.com/a", tmp_path / "d.zip")
    landed["url"] = "http://objects.githubusercontent.com/file"  # a redirect off https
    with pytest.raises(UpdateError, match="unexpected address"):
        updates.download("https://github.com/a", tmp_path / "e.zip")
    with pytest.raises(UpdateError, match="https"):
        updates.download("http://github.com/a", tmp_path / "e.zip")


def _app(folder: Path, version: str) -> Path:
    (folder / "_internal").mkdir(parents=True)
    (folder / "CapyPanel.exe").write_text(version, encoding="utf-8")
    (folder / "_internal" / "lib.dll").write_text(version, encoding="utf-8")
    return folder


def _portable(app: Path) -> None:
    (app / PORTABLE_MARKER).touch()
    (app / "userdata" / "users").mkdir(parents=True)
    (app / "userdata" / "users" / "settings.json").write_text("mine", encoding="utf-8")


def test_the_swap_puts_the_new_version_in_and_keeps_a_portable_copy_s_data(
    tmp_path: Path,
) -> None:
    place = updates.places(_app(tmp_path / "CapyPanel", "0.26.0"))
    _portable(place.app)
    _app(place.new_app, "0.26.1")
    waited: list[int] = []
    updates.apply(place, 4242, wait=lambda pid, _t: waited.append(pid) or True,
                  test=lambda exe: exe.read_text(encoding="utf-8") == "0.26.1")  # fmt: skip
    assert waited == [4242]
    assert (place.app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.1"
    assert (place.app / "userdata" / "users" / "settings.json").read_text(
        encoding="utf-8"
    ) == "mine"
    assert (place.app / PORTABLE_MARKER).exists()
    assert (place.previous / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.0"
    updates.clean_up(place.app)  # the new version, once started
    assert not place.previous.exists() and not place.staging.exists() and place.app.exists()


def test_a_new_version_that_fails_its_self_test_leaves_the_old_one_as_it_was(
    tmp_path: Path,
) -> None:
    place = updates.places(_app(tmp_path / "CapyPanel", "0.26.0"))
    _portable(place.app)
    _app(place.new_app, "0.26.1")
    with pytest.raises(UpdateError, match="self-test"):
        updates.apply(place, 1, wait=lambda _p, _t: True, test=lambda _exe: False)
    assert (place.app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.0"
    assert (place.app / "userdata" / "users" / "settings.json").read_text(
        encoding="utf-8"
    ) == "mine"
    assert (place.app / PORTABLE_MARKER).exists() and not place.previous.exists()


def test_nothing_moves_while_the_old_copy_is_still_running(tmp_path: Path) -> None:
    place = updates.places(_app(tmp_path / "CapyPanel", "0.26.0"))
    _app(place.new_app, "0.26.1")
    with pytest.raises(UpdateError, match="didn't close"):
        updates.apply(place, 1, wait=lambda _p, _t: False, test=lambda _exe: True)
    assert (place.app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.0"
    assert not place.previous.exists()


def test_waiting_for_a_process_that_isn_t_there_returns_at_once() -> None:
    assert updates.wait_for_exit(0x7FFFFFF0, 5)  # no such process


def test_a_folder_that_can_t_take_files_is_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "CapyPanel").mkdir()
    assert updates.cannot_install(tmp_path / "CapyPanel") == ""

    def refused(**_kwargs: Any) -> Any:
        raise PermissionError("denied")

    monkeypatch.setattr(updates.tempfile, "TemporaryFile", refused)
    assert updates.cannot_install(tmp_path / "CapyPanel").startswith("CapyPanel can't write to")


def test_the_helper_is_the_new_version_s_own_exe(tmp_path: Path) -> None:
    app = tmp_path / "CapyPanel"
    args = updates.helper_args(app, 77, "0.26.0", "0.26.1")
    root = updates.work_root(app.resolve())
    assert args[0] == str(root / "new" / "CapyPanel" / "CapyPanel.exe")
    assert not root.is_relative_to(tmp_path)  # in app data, never beside CapyPanel's folder
    assert args[1:] == ["--apply-update", str(app.resolve()), "77", "0.26.0", "0.26.1"]


def test_the_downloaded_zip_is_checked_against_its_sha256(tmp_path: Path) -> None:
    archive = _zip(tmp_path / ZIP, {"CapyPanel/CapyPanel.exe": b"exe"})
    assert updates.sha256_of(archive) == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_a_release_object_names_what_it_downloads() -> None:
    release = updates.release_from(_release_json())
    assert isinstance(release, Release)
    assert release.zip_url.endswith(ZIP) and release.sha_url.endswith(f"{ZIP}.sha256")


def test_a_file_that_won_t_move_halfway_puts_everything_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An antivirus holding one file: the files already moved aside come back, nothing is lost.
    place = updates.places(_app(tmp_path / "CapyPanel", "0.26.0"))
    _portable(place.app)
    _app(place.new_app, "0.26.1")
    real_move = updates.shutil.move

    def stubborn(source: Path, target: Path) -> object:
        if Path(source) == place.app / "_internal":  # the exe went first: it comes back too
            raise PermissionError("in use")
        return real_move(source, target)

    monkeypatch.setattr(updates.shutil, "move", stubborn)
    monkeypatch.setattr(updates.time, "sleep", lambda _s: None)
    with pytest.raises(UpdateError, match="in use"):
        updates.apply(place, 1, wait=lambda _p, _t: True, test=lambda _exe: True)
    monkeypatch.setattr(updates.shutil, "move", real_move)
    assert (place.app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.0"
    assert (place.app / "_internal" / "lib.dll").read_text(encoding="utf-8") == "0.26.0"
    assert (place.app / PORTABLE_MARKER).exists() and not place.previous.exists()


def test_the_helper_never_lets_an_error_through_and_starts_the_old_copy_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path / "CapyPanel", "0.26.0")
    started: list[list[str]] = []

    def broken(_place: Any, _pid: int, **_kwargs: Any) -> None:
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(updates, "apply", broken)
    monkeypatch.setattr(updates, "start", lambda exe, *args: started.append([str(exe), *args]))
    assert updates.run_helper(app, 1, "0.26.0", "0.26.1") == 1
    assert started == [[str(app.resolve() / "CapyPanel.exe"), "--update-failed", "0.26.1",
                        "RuntimeError: something nobody planned for"]]  # fmt: skip
    monkeypatch.setattr(updates, "apply", lambda _place, _pid, **_kwargs: None)
    started.clear()
    assert updates.run_helper(app, 1, "0.26.0", "0.26.1") == 0
    assert started == [[str(app.resolve() / "CapyPanel.exe"), "--updated-from", "0.26.0"]]


def test_no_release_published_yet_means_nothing_new(monkeypatch: pytest.MonkeyPatch) -> None:

    def answer(code: int):  # noqa: ANN202
        def urlopen(request: Any, timeout: float, context: Any) -> Any:
            raise urllib.error.HTTPError(updates.LATEST_URL, code, "Not Found", {}, None)  # type: ignore[arg-type]

        return urlopen

    monkeypatch.setattr(urllib.request, "urlopen", answer(404))
    assert updates.latest() is None
    monkeypatch.setattr(urllib.request, "urlopen", answer(403))  # rate limited, say
    with pytest.raises(UpdateError, match="403"):
        updates.latest()


def test_the_exe_s_own_jobs_start_without_the_splash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(updates.NO_SPLASH, "1")  # as in the helper, which shows none
    assert updates._env(splash=False)[updates.NO_SPLASH] == "1"
    assert updates.NO_SPLASH not in updates._env(splash=True)  # CapyPanel itself shows it


def test_github_s_certificate_is_checked_without_python_s_strict_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Strict mode refused a chain Windows trusts ("Missing Authority Key Identifier").
    contexts: list[ssl.SSLContext] = []

    def urlopen(request: Any, timeout: float, context: ssl.SSLContext) -> Any:
        contexts.append(context)
        raise urllib.error.HTTPError(updates.LATEST_URL, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert updates.latest() is None
    (context,) = contexts
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert not context.verify_flags & ssl.VERIFY_X509_STRICT


def test_how_often_is_one_choice_for_the_whole_pc(tmp_path: Path) -> None:
    folder = tmp_path / "tools"
    assert updates.check_of(folder) == updates.AT_START  # nothing chosen yet
    updates.set_check(folder, updates.WEEKLY)
    assert updates.check_of(folder) == updates.WEEKLY
    (folder / updates.CHECK_FILE).write_text('{"check": "hourly"}', encoding="utf-8")
    assert updates.check_of(folder) == updates.AT_START  # nothing it knows: the default
    updates.set_check(folder, updates.AT_START)
    assert not (folder / updates.CHECK_FILE).exists()
    with pytest.raises(ValueError):
        updates.set_check(folder, "hourly")


def test_another_user_s_file_doesn_t_turn_checks_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates.set_check(tmp_path, updates.OFF)
    monkeypatch.setattr(updates.winsec, "made_by_trusted", lambda path: False)
    assert updates.check_of(tmp_path) == updates.AT_START


def test_the_notes_in_the_app_s_language() -> None:
    notes = (
        "## Português (Brasil)\n\n- O título mostra só a versão.\n\n### Como usar\n\n1. Baixe.\n\n"
        "## English\n\n- The title shows only the version.\n\n[Docs](https://example.org/)"
    )
    assert updates.notes_in(notes, "English") == (
        "- The title shows only the version.\n\n[Docs](https://example.org/)"
    )
    portuguese = updates.notes_in(notes, "Português (Brasil)")
    assert portuguese.startswith("- O título") and portuguese.endswith("1. Baixe.")  # with ###
    assert "English" not in portuguese
    assert updates.notes_in(notes, "Deutsch") == notes  # no such part: all of them
    assert updates.notes_in("- One line, no parts.", "English") == "- One line, no parts."


def test_the_exe_goes_out_first_and_comes_in_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A start clicked mid-swap finds no exe rather than one with half its files.
    place = updates.places(_app(tmp_path / "CapyPanel", "0.26.0"))
    _app(place.new_app, "0.26.1")
    moved: list[str] = []
    copied: list[str] = []
    real_move = updates.shutil.move
    real_copy2, real_copytree = updates.shutil.copy2, updates.shutil.copytree

    def move(source: Path, target: Path) -> object:
        moved.append(Path(source).name)
        return real_move(source, target)

    monkeypatch.setattr(updates.shutil, "move", move)
    monkeypatch.setattr(
        updates.shutil, "copy2", lambda s, d: copied.append(Path(s).name) or real_copy2(s, d)
    )
    monkeypatch.setattr(
        updates.shutil, "copytree", lambda s, d: copied.append(Path(s).name) or real_copytree(s, d)
    )
    updates.apply(place, 1, wait=lambda _p, _t: True, test=None)  # tested before the restart
    assert moved[0] == "CapyPanel.exe" and copied[-1] == "CapyPanel.exe"
    assert (place.app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.1"


def test_the_helper_skips_a_self_test_already_passed_and_marks_its_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path / "CapyPanel", "0.26.0")
    place = updates.places(app)
    _app(place.new_app, "0.26.1")
    seen: dict[str, Any] = {}

    def apply(_place: Any, _pid: int, *, test: Any) -> None:
        seen["test"] = test
        seen["applying"] = updates.applying(app)  # its own marker, its own process
        seen["marker"] = (place.staging / updates.APPLYING).exists()

    monkeypatch.setattr(updates, "apply", apply)
    monkeypatch.setattr(updates, "start", lambda exe, *args: None)
    assert updates.run_helper(app, 1, "0.26.0", "0.26.1") == 0
    assert seen == {"test": updates.self_test, "applying": False, "marker": True}
    assert not (place.staging / updates.APPLYING).exists()  # gone before the new start
    updates.mark_tested(place, "0.26.1")
    assert updates.was_tested(place, "0.26.1") and not updates.was_tested(place, "0.26.2")
    assert updates.run_helper(app, 1, "0.26.0", "0.26.1") == 0
    assert seen["test"] is None


def test_a_start_during_the_swap_sees_it_and_a_leftover_marker_never_counts(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "CapyPanel", "0.26.0")
    marker = updates.places(app).staging / updates.APPLYING
    assert not updates.applying(app)  # no marker
    marker.parent.mkdir(parents=True)
    marker.write_text(str(os.getppid()), encoding="utf-8")  # a process that's running
    assert updates.applying(app)
    old = time.time() - updates.APPLYING_FOR - 1
    os.utime(marker, (old, old))
    assert not updates.applying(app)  # a helper that never cleaned up: never obeyed
    marker.write_text(str(0x7FFFFFF0), encoding="utf-8")
    assert not updates.applying(app)  # no such process
    marker.write_text("not a number", encoding="utf-8")
    assert not updates.applying(app)


def test_after_a_good_update_nothing_is_left_in_or_beside_capypanel_s_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path / "CapyPanel", "0.26.3")
    place = updates.places(app)
    _app(place.new_app, "0.26.4")
    monkeypatch.setattr(updates, "wait_for_exit", lambda _pid, _t: True)
    monkeypatch.setattr(updates, "self_test", lambda _exe: True)
    monkeypatch.setattr(updates, "start", lambda exe, *args: None)
    assert updates.run_helper(app, 1, "0.26.3", "0.26.4") == 0
    assert (app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.4"
    assert not place.previous.exists()  # the old version goes as soon as the new one passed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CapyPanel"]  # nothing beside it
    assert sorted(p.name for p in app.iterdir()) == ["CapyPanel.exe", "_internal"]  # nor in it
    updates.clean_up(app)  # the new version's start: the unpacked download, which ran the helper
    assert not place.staging.exists()
    assert not updates.work_root(app.resolve()).parent.exists()  # no empty folders left either


def test_every_start_clears_what_an_update_left_here_and_beside_the_folder(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path / "CapyPanel", "0.26.3")
    place = updates.places(app)
    old_update, old_previous = tmp_path / "CapyPanel.update", tmp_path / "CapyPanel.previous"
    for folder in (place.staging, place.previous, old_update, old_previous):
        _app(folder / "CapyPanel", "x")
    (tmp_path / "Other.update").mkdir()  # not ours: stays
    marker = old_update / updates.APPLYING
    marker.write_text(str(os.getppid()), encoding="utf-8")  # a swap under way: nothing goes
    updates.clean_up(app)
    assert old_update.exists() and place.previous.exists()
    marker.unlink()
    updates.clean_up(app)
    assert not any(f.exists() for f in (place.staging, place.previous, old_update, old_previous))
    assert (tmp_path / "Other.update").exists() and (app / "CapyPanel.exe").exists()


def test_the_helper_works_from_where_an_older_updater_unpacked_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 0.26.3's window unpacks beside CapyPanel's folder; 0.26.4's helper swaps from there.
    app = _app(tmp_path / "CapyPanel", "0.26.3")
    staging = tmp_path / "CapyPanel.update"
    _app(staging / "CapyPanel", "0.26.4")
    monkeypatch.setattr(updates, "wait_for_exit", lambda _pid, _t: True)
    monkeypatch.setattr(updates, "self_test", lambda _exe: True)
    monkeypatch.setattr(updates, "start", lambda exe, *args: None)
    assert updates.run_helper(app, 1, "0.26.3", "0.26.4", staging) == 0
    assert (app / "CapyPanel.exe").read_text(encoding="utf-8") == "0.26.4"
    updates.clean_up(app)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CapyPanel"]


def test_a_folder_still_in_use_is_tried_again_until_it_goes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The helper runs from the download for a moment after starting the new version.
    app = _app(tmp_path / "CapyPanel", "0.26.4")
    staging = updates.places(app).staging
    _app(staging / "CapyPanel", "0.26.4")
    real_rmtree = updates.shutil.rmtree
    calls: list[int] = []

    def busy_twice(path: Path, ignore_errors: bool = False) -> None:
        calls.append(1)
        if len(calls) > 2:
            real_rmtree(path, ignore_errors=ignore_errors)

    monkeypatch.setattr(updates.shutil, "rmtree", busy_twice)
    updates.clean_up(app, pause=0)
    assert not staging.exists() and len(calls) == 3
