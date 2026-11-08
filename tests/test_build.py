"""The build label testers compare against: the version, and from a source checkout the build
number, which only grows, and the commit."""

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
def test_a_source_checkout_shows_its_build_number_and_commit() -> None:
    pattern = r"\S+ build [1-9]\d* \([0-9a-f]{7}\)"
    assert re.fullmatch(pattern, capypanel.BUILD), capypanel.BUILD
