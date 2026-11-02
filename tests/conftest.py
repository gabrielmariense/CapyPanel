import uuid
from collections.abc import Iterator

import pytest

from capypanel.core import credstore


@pytest.fixture(autouse=True)
def own_credentials(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test keeps its secrets under a name of its own, removed after it, so the suite
    never reads or deletes the passwords of whoever runs it."""
    folder = f"CapyPanelTest/{uuid.uuid4()}/"
    monkeypatch.setattr(credstore, "PREFIX", folder)
    yield
    for name in credstore.names(""):
        credstore.forget(name)
