import socket
import time

import pytest

from capypanel.core.remote import status
from capypanel.core.remote.status import PortState, Status


def test_this_pc_is_online() -> None:
    assert status.probe("127.0.0.1", [9])[0] is Status.ONLINE


def test_a_port_that_answers_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert status.probe("127.0.0.1", [port]) == (Status.ONLINE, ("127.0.0.1", port))


def test_a_refused_port_still_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    # Windows retries a refused connection: about 1 s over the network, 2 s to itself.
    monkeypatch.setattr(status, "TIMEOUT", 4.0)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert status.probe("127.0.0.1", [closed])[0] is Status.ONLINE


def test_silence_is_offline_within_the_timeouts() -> None:
    began = time.monotonic()
    assert status.probe("192.0.2.1", [445, 3389])[0] is Status.OFFLINE
    assert time.monotonic() - began < status.TIMEOUT + 1


def test_a_name_that_doesnt_resolve_says_so() -> None:
    assert status.probe("no-such-host.invalid", [445])[0] is Status.NOT_FOUND


def test_a_port_that_takes_the_connection_is_open() -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert status.port_state("127.0.0.1", port) == (PortState.OPEN, "127.0.0.1")


def test_a_refused_port_is_closed_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "TIMEOUT", 4.0)  # Windows retries a refusal to itself for ~2 s
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert status.port_state("127.0.0.1", closed) == (PortState.CLOSED, "127.0.0.1")


def test_a_port_that_stays_silent_has_no_answer_within_the_timeout() -> None:
    began = time.monotonic()
    assert status.port_state("192.0.2.1", 22) == (PortState.NO_ANSWER, None)
    assert time.monotonic() - began < status.TIMEOUT + 1


def test_a_port_on_a_name_that_doesnt_resolve_says_so() -> None:
    assert status.port_state("no-such-host.invalid", 22) == (PortState.NOT_FOUND, None)


def test_the_port_is_open_when_any_address_takes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        both = [(socket.AF_INET, "192.0.2.1"), (socket.AF_INET, "127.0.0.1")]
        monkeypatch.setattr(status, "_resolve", lambda _host: both)
        assert status.port_state("srv-01", port) == (PortState.OPEN, "127.0.0.1")


def test_every_address_of_a_name_is_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        both = [(socket.AF_INET, "192.0.2.1"), (socket.AF_INET, "127.0.0.1")]
        monkeypatch.setattr(status, "_resolve", lambda _host: both)
        assert status.probe("desk-pc", [port])[0] is Status.ONLINE
