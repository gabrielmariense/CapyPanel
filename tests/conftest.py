import ctypes
from typing import cast

import pytest
from fake_credman import FakeCredentialManager

from capypanel.core import credstore

# Set here, not with monkeypatch: a test undoing its patches can't bring back the real prefix.
credstore.PREFIX = "CapyPanelTest/"
credstore._advapi32 = cast(ctypes.WinDLL, FakeCredentialManager())


@pytest.fixture(autouse=True)
def own_app_data(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Every test gets its own %LOCALAPPDATA%, never the real one of whoever runs it."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("localappdata")))


@pytest.fixture(autouse=True)
def own_credentials() -> None:
    """An in-memory Credential Manager per test: the suite never touches anyone's real passwords."""
    credstore._advapi32 = cast(ctypes.WinDLL, FakeCredentialManager())
