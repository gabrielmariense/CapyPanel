import socket
import time

import pytest

from capypanel.core.remote import status
from capypanel.core.remote.status import Status


def test_this_pc_is_online() -> None:
    assert status.probe("127.0.0.1", [9])[0] is Status.ONLINE  # answers ping


def test_a_port_that_answers_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)  # as if ping were blocked
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert status.probe("127.0.0.1", [port]) == (Status.ONLINE, ("127.0.0.1", port))


def test_a_refused_port_still_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    # Windows retries a refused connection: about 1 s over the network, 2 s to itself.
    monkeypatch.setattr(status, "TIMEOUT", 4.0)
    with socket.socket() as probe:  # a port nothing listens on: the PC answers "refused"
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert status.probe("127.0.0.1", [closed])[0] is Status.ONLINE


def test_silence_is_offline_within_the_timeouts() -> None:
    began = time.monotonic()
    assert status.probe("192.0.2.1", [445, 3389])[0] is Status.OFFLINE  # never a real host
    assert time.monotonic() - began < status.TIMEOUT + 1


def test_a_name_that_doesnt_resolve_says_so() -> None:
    assert status.probe("no-such-host.invalid", [445])[0] is Status.NOT_FOUND


def test_every_address_of_a_name_is_tried(monkeypatch: pytest.MonkeyPatch) -> None:
    # A PC on cable and Wi-Fi: the first address is dead, the second one answers.
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        both = [(socket.AF_INET, "192.0.2.1"), (socket.AF_INET, "127.0.0.1")]
        monkeypatch.setattr(status, "_resolve", lambda _host: both)
        assert status.probe("desk-pc", [port])[0] is Status.ONLINE
