"""`CapyPanel.exe --self-test`: the check the packaged exe runs on itself."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from capypanel import __main__ as entry
from capypanel.core import i18n
from capypanel.ui import language, selftest
from capypanel.ui.themes import engine as themes


@pytest.fixture
def as_before(qapp: QApplication) -> Iterator[None]:
    yield  # it goes through every theme and language
    themes.apply(themes.DEFAULT_THEME)
    language.apply(i18n.DEFAULT_LANGUAGE)


def test_it_passes_from_source_and_says_what_it_checked(
    as_before: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report, own = tmp_path / "report.txt", tmp_path / "own"
    own.mkdir()
    monkeypatch.setattr(selftest.tempfile, "mkdtemp", lambda prefix: str(own))
    monkeypatch.setattr("sys.argv", ["capypanel", "--self-test", str(report)])
    assert entry.main() == 0
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("CapyPanel ") and lines[-1] == "SELF-TEST PASSED"
    passed = [line for line in lines if line.startswith("ok ")]
    assert len(passed) == 4 and "themes 7" in passed[-1] and "languages 2" in passed[-1]
    assert not own.exists()  # the folder it worked in is gone


def test_a_missing_part_fails_it_and_the_report_says_which(
    as_before: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(themes, "THEMES_DIR", tmp_path)  # as a build that left the themes out
    monkeypatch.setattr(selftest, "_whole_window", lambda root: ["skipped here"])
    report = tmp_path / "report.txt"
    assert selftest.run(report) == 1
    text = report.read_text(encoding="utf-8")
    assert "FAILED bundled files" in text and "themes: 0 of at least 2" in text
    assert text.splitlines()[-1] == "SELF-TEST FAILED"
