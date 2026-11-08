"""The build label testers compare against: the version, and from a source checkout the commit
and when it was made, which tells a newer build from an older one."""

import re
import shutil
from pathlib import Path

import pytest

import capypanel


@pytest.mark.skipif(
    not (Path(capypanel.__file__).resolve().parents[2] / ".git").exists()
    or shutil.which("git") is None,
    reason="not a source checkout with git",
)
def test_a_source_checkout_shows_its_commit_and_when_it_was_made() -> None:
    pattern = r"\S+ \([0-9a-f]{7}, \d{4}-\d{2}-\d{2} \d{2}:\d{2}\)"
    assert re.fullmatch(pattern, capypanel.BUILD), capypanel.BUILD
