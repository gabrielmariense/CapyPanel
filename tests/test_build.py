"""The build label testers compare against: the version, the build number, which only grows,
and the commit; from a source checkout and in the packaged exe. And what the packaged exe
needs besides: its settings outside its own folder, and its Windows version info."""

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import capypanel
from capypanel.core import settings


@pytest.mark.skipif(
    not (Path(capypanel.__file__).resolve().parents[2] / ".git").exists()
    or shutil.which("git") is None,
    reason="not a source checkout with git",
)
def test_a_source_checkout_shows_its_build_number_and_commit() -> None:
    pattern = r"\S+ build [1-9]\d* \([0-9a-f]{7}\)"
    assert re.fullmatch(pattern, capypanel.BUILD), capypanel.BUILD


def test_git_is_asked_for_the_build_number_once_per_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").mkdir()
    asked: list[list[str]] = []

    def git(command: list[str], **_more: Any) -> subprocess.CompletedProcess[str]:
        asked.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="100\n", stderr="")

    monkeypatch.setattr(subprocess, "run", git)
    number = str(100 + capypanel._SQUASHED)
    assert capypanel._build_number(tmp_path, "abc1234") == number and len(asked) == 1
    assert capypanel._build_number(tmp_path, "abc1234") == number and len(asked) == 1  # kept
    assert capypanel._build_number(tmp_path, "def5678") == number and len(asked) == 2  # new commit

    def no_git(command: list[str], **_more: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert capypanel._build_number(tmp_path, "0000000") == ""  # no git: no number, nothing kept
    assert capypanel._build_number(tmp_path, "def5678") == number


def test_a_packaged_build_carries_its_version_build_number_and_commit(tmp_path: Path) -> None:
    assert capypanel._stamped(tmp_path) is None  # from source: no such file
    (tmp_path / capypanel.STAMP).write_text("0.26.0 472 181cb7c\n", encoding="utf-8")
    assert capypanel._stamped(tmp_path) == ("0.26.0", "472", "181cb7c")
    (tmp_path / capypanel.STAMP).write_text("half written", encoding="utf-8")
    assert capypanel._stamped(tmp_path) is None


def test_the_packaged_exe_keeps_settings_out_of_its_own_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An update swaps the exe's folder: settings, lists and the log must not be in it. Only a
    copy made portable on purpose (the marker file) keeps them beside the exe."""
    app, data = tmp_path / "Apps" / "CapyPanel", tmp_path / "ProgramData"
    app.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "CapyPanel.exe"))
    assert settings.app_dir() == app
    paths = settings.resolve_paths(env={"PROGRAMDATA": str(data)}, account="ana@CORP")
    assert not paths.portable and paths.root == data / settings.APP_ID
    for kept in (paths.settings_file, paths.user_dir, paths.log_file, paths.lists("hosts").default):
        assert not kept.is_relative_to(app), kept
    (app / settings.PORTABLE_MARKER).touch()
    portable = settings.resolve_paths(env={"PROGRAMDATA": str(data)}, account="ana@CORP")
    assert portable.portable and portable.root == app / "userdata"


def test_the_exe_s_version_info_names_capypanel_and_its_build() -> None:
    script = Path(capypanel.__file__).resolve().parents[2] / "scripts" / "build_exe.py"
    spec = importlib.util.spec_from_file_location("build_exe", script)
    assert spec is not None and spec.loader is not None
    build_exe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_exe)
    text = build_exe.version_info("0.26.0", "472", "0.26.0 build 472 (181cb7c)")
    assert "filevers=(0, 26, 0, 472)" in text and "prodvers=(0, 26, 0, 472)" in text
    for line in (
        "StringStruct('ProductName', 'CapyPanel')",
        "StringStruct('FileVersion', '0.26.0.472')",
        "StringStruct('ProductVersion', '0.26.0 build 472 (181cb7c)')",
        "StringStruct('OriginalFilename', 'CapyPanel.exe')",
    ):
        assert line in text, line
    assert "StringStruct('CompanyName', " in text
    compile(text, "version_info", "eval")  # PyInstaller reads it as one Python expression


def test_the_splash_version_is_centred_on_real_letters() -> None:
    # Its own process, as in the build: a Qt app made earlier would keep its own fonts.
    scripts = Path(capypanel.__file__).resolve().parents[2] / "scripts"
    code = f"import sys; sys.path.insert(0, {str(scripts)!r}); import build_exe; "
    code += "print(build_exe.splash_x('0.26.0'))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    # Six empty 16 px boxes (no font found) would start at 192; Segoe UI's digits are narrower.
    assert 205 <= int(done.stdout) <= 230
