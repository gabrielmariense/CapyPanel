import uuid
from collections.abc import Iterator

import pytest

from capypanel.core import credstore


@pytest.fixture
def name() -> Iterator[str]:
    """A name no real setting uses, removed again after the test."""
    test_name = f"test/{uuid.uuid4()}"
    yield test_name
    credstore.forget(test_name)


def test_a_secret_is_kept_replaced_and_forgotten(name: str) -> None:
    assert credstore.load(name) is None
    credstore.save(name, "SAMPLE-community")
    assert credstore.load(name) == "SAMPLE-community"
    credstore.save(name, "çhanged")  # not just ASCII
    assert credstore.load(name) == "çhanged"
    credstore.forget(name)
    assert credstore.load(name) is None
    credstore.forget(name)  # forgetting twice is fine


def test_a_secret_too_long_for_windows_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        credstore.save(name, "x" * 2000)
