import ctypes
from typing import Any

import pytest

from capypanel.core.remote import services
from capypanel.core.remote.access import Reason, RemoteError


class FakeAdvapi:
    """The service manager: `states` is what each status query finds after the stop."""

    def __init__(self, states: list[int], stop_error: int = 0) -> None:
        self.calls: list[str] = []
        self.states = states
        self.stop_error = stop_error

    def OpenSCManagerW(self, host: str, database: None, access: int) -> int:  # noqa: N802
        self.calls.append(f"manager {host}")
        return 1

    def OpenServiceW(self, manager: int, name: str, access: int) -> int:  # noqa: N802
        self.calls.append(f"open {name}")
        return 2

    def ControlService(self, service: int, control: int, status: Any) -> bool:  # noqa: N802
        self.calls.append("stop")
        ctypes.set_last_error(self.stop_error)
        if self.stop_error:
            return False
        ctypes.cast(status, ctypes.POINTER(services._Status)).contents.state = 3  # stop pending
        return True

    def QueryServiceStatus(self, service: int, status: Any) -> bool:  # noqa: N802
        self.calls.append("query")
        state = self.states.pop(0) if self.states else 3
        ctypes.cast(status, ctypes.POINTER(services._Status)).contents.state = state
        return True

    def StartServiceW(self, service: int, count: int, args: None) -> bool:  # noqa: N802
        self.calls.append("start")
        return True

    def CloseServiceHandle(self, handle: int) -> bool:  # noqa: N802
        self.calls.append(f"close {handle}")
        return True


@pytest.fixture
def reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "check_reachable", lambda host: None)


def test_a_restart_waits_for_the_stop_then_starts(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    fake = FakeAdvapi(states=[3, 3, 1])  # stop pending twice, then stopped
    monkeypatch.setattr(services, "_advapi32", fake)
    services.restart_service("192.0.2.10", services.SPOOLER, sleep=lambda s: None)
    assert fake.calls == [
        "manager 192.0.2.10", "open Spooler", "stop", "query", "query", "query", "start",
        "close 2", "close 1",
    ]  # fmt: skip


def test_a_stopped_service_is_just_started(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    fake = FakeAdvapi(states=[], stop_error=1062)  # ERROR_SERVICE_NOT_ACTIVE
    monkeypatch.setattr(services, "_advapi32", fake)
    services.restart_service("192.0.2.10", services.SPOOLER, sleep=lambda s: None)
    assert "start" in fake.calls and "query" not in fake.calls


def test_a_service_that_wont_stop_gives_up_and_closes_its_handles(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    fake = FakeAdvapi(states=[])  # stays "stop pending"
    monkeypatch.setattr(services, "_advapi32", fake)
    with pytest.raises(TimeoutError):
        services.restart_service("192.0.2.10", services.SPOOLER, sleep=lambda s: None)
    assert "start" not in fake.calls and fake.calls[-2:] == ["close 2", "close 1"]


def test_a_refused_stop_says_why(monkeypatch: pytest.MonkeyPatch, reachable: None) -> None:
    monkeypatch.setattr(services, "_advapi32", FakeAdvapi(states=[], stop_error=5))
    with pytest.raises(RemoteError) as caught:
        services.restart_service("192.0.2.10", services.SPOOLER, sleep=lambda s: None)
    assert caught.value.reason is Reason.REJECTED


def test_an_unreachable_host_is_never_asked() -> None:
    with pytest.raises(RemoteError) as caught:
        services.restart_service("192.0.2.1", services.SPOOLER)  # a documentation address
    assert caught.value.reason is Reason.UNREACHABLE
