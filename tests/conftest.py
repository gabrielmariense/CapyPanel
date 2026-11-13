import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from capypanel.core import credstore

# Never the real prefix, even where a test undoes its monkeypatches: an undo goes back to this,
# so nothing can reach the passwords of whoever runs the tests.
credstore.PREFIX = "CapyPanelTest/unpatched/"


@pytest.hookimpl(tryfirst=True)  # before xdist reads the groups
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """With the tests spread over several workers (CI's -n auto --dist loadgroup), the files
    that use Windows Credential Manager all run on one worker. Run side by side, a few of them
    failed now and then (a save or delete not seen yet), though each test has its own names."""
    uses: dict[Path, bool] = {}
    for item in items:
        if item.path not in uses:
            uses[item.path] = "credstore" in item.path.read_text(encoding="utf-8", errors="ignore")
        if uses[item.path]:
            item.add_marker(pytest.mark.xdist_group("credential-manager"))


@pytest.fixture(autouse=True)
def own_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """An update's folders live in %LOCALAPPDATA%: every test gets its own, never the real one
    of whoever runs it."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata")))


@pytest.fixture(autouse=True)
def own_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test keeps its secrets under a name of its own, removed after it, so the suite
    never reads or deletes the passwords of whoever runs it."""
    folder = f"CapyPanelTest/{uuid.uuid4()}/"
    monkeypatch.setattr(credstore, "PREFIX", folder)
    yield
    # Its own folder, whatever PREFIX says now (a test may have undone its monkeypatches).
    kept, credstore.PREFIX = credstore.PREFIX, folder
    try:
        for name in credstore.names(""):
            credstore.forget(name)
    finally:
        credstore.PREFIX = kept
