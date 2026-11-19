import ctypes
from typing import cast

import pytest
from fake_credman import FakeCredentialManager

from capypanel.core import credstore

# Never the real Credential Manager, nor the real prefix: set here, not with monkeypatch, so a
# test that undoes its monkeypatches can't bring back either one.
credstore.PREFIX = "CapyPanelTest/"
credstore._advapi32 = cast(ctypes.WinDLL, FakeCredentialManager())


@pytest.fixture(autouse=True)
def own_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """An update's folders live in %LOCALAPPDATA%: every test gets its own, never the real one
    of whoever runs it."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata")))


@pytest.fixture(autouse=True)
def own_credentials() -> None:
    """Every test starts with an empty Credential Manager of its own, in memory
    (tests/helpers/fake_credman.py): the suite never reads or writes the passwords of whoever
    runs it, and tests side by side never see each other's."""
    credstore._advapi32 = cast(ctypes.WinDLL, FakeCredentialManager())
