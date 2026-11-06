import ctypes

import pytest

from capypanel.core.remote import power
from capypanel.core.remote.access import Reason, RemoteError


class FakeAdvapi:
    """Windows' shutdown calls, recorded; `error` is what a failing call leaves behind."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error = 0

    def _answer(self) -> bool:
        ctypes.set_last_error(self.error)
        return not self.error

    def InitiateSystemShutdownExW(self, *args: object) -> bool:  # noqa: N802 (Windows' name)
        self.calls.append(("shutdown", *args))
        return self._answer()

    def AbortSystemShutdownW(self, machine: str) -> bool:  # noqa: N802
        self.calls.append(("abort", machine))
        return self._answer()


@pytest.fixture
def advapi(monkeypatch: pytest.MonkeyPatch) -> FakeAdvapi:
    fake = FakeAdvapi()
    monkeypatch.setattr(power, "_advapi32", fake)
    monkeypatch.setattr(power, "check_reachable", lambda host: None)
    return fake


def test_restart_and_shut_down_ask_windows_with_the_delay_and_message(advapi: FakeAdvapi) -> None:
    power.restart("192.0.2.10")
    power.shut_down("192.0.2.10", 300, "IT: shutting down for maintenance")
    planned = 0x80000000
    assert advapi.calls == [
        ("shutdown", "\\\\192.0.2.10", None, 0, True, True, planned),
        ("shutdown", "\\\\192.0.2.10", "IT: shutting down for maintenance", 300, True, False,
         planned),
    ]  # fmt: skip


def test_a_delay_out_of_range_is_refused_before_anything_is_sent(advapi: FakeAdvapi) -> None:
    for delay in (-1, power.MAX_DELAY + 1):
        with pytest.raises(ValueError):
            power.restart("192.0.2.10", delay)
    assert advapi.calls == []


def test_cancel_says_whether_a_restart_was_waiting(advapi: FakeAdvapi) -> None:
    assert power.cancel("192.0.2.10") is True
    advapi.error = 1116  # ERROR_NO_SHUTDOWN_IN_PROGRESS
    assert power.cancel("192.0.2.10") is False
    advapi.error = 5
    with pytest.raises(RemoteError) as caught:
        power.cancel("192.0.2.10")
    assert caught.value.reason is Reason.REJECTED


def test_a_restart_already_on_its_way_is_told_apart(advapi: FakeAdvapi) -> None:
    advapi.error = 1115  # ERROR_SHUTDOWN_IN_PROGRESS
    with pytest.raises(RemoteError) as caught:
        power.restart("192.0.2.10")
    assert power.already_pending(caught.value)


def test_an_unreachable_host_is_never_asked() -> None:
    with pytest.raises(RemoteError) as caught:
        power.restart("192.0.2.1")  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE
