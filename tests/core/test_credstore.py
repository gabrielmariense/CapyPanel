import uuid
from collections.abc import Iterator

import pytest
from fake_credman import FakeCredentialManager

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


def test_a_secret_keeps_its_user_and_a_folder_lists_its_names() -> None:
    credstore.save("profile/realvnc", "x1", user="CORP\\ana")
    credstore.save("profile/ultravnc", "x2")
    credstore.save("profiles-other", "x3")  # starts like the folder, isn't in it
    assert credstore.read("profile/realvnc") == ("CORP\\ana", "x1")
    assert credstore.read("profile/ultravnc") == ("CapyPanel", "x2")
    assert credstore.names("profile/") == ["profile/realvnc", "profile/ultravnc"]
    assert credstore.names("nothing/") == []


def test_tests_never_touch_the_real_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_and_test_prefix() -> bool:  # tests/conftest.py
        fake = isinstance(credstore._advapi32, FakeCredentialManager)
        return fake and credstore.PREFIX.startswith("CapyPanelTest/")

    assert fake_and_test_prefix()
    # Undoing a test's monkeypatches must keep the test prefix: with the real one back, the
    # cleanup after it would delete the saved passwords of whoever runs the tests.
    monkeypatch.undo()
    assert fake_and_test_prefix()


def test_every_result_windows_hands_back_is_freed() -> None:
    fake = credstore._advapi32
    assert isinstance(fake, FakeCredentialManager)
    credstore.save("a", "x")
    credstore.read("a")
    credstore.names("")
    credstore.read("missing")
    assert fake.unfreed() == 0


def test_a_secret_too_long_for_windows_is_refused(name: str) -> None:
    with pytest.raises(ValueError):
        credstore.save(name, "x" * 2000)
