"""The build label testers compare against: the version, and from a source checkout the build
number, which only grows, and the commit."""

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import capypanel


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
