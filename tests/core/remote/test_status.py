import socket
import time

import pytest

from capypanel.core.remote import status
from capypanel.core.remote.status import Status


def test_this_pc_is_online() -> None:
    assert status.check("127.0.0.1", [9]) is Status.ONLINE  # answers ping


def test_a_port_that_answers_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)  # as if ping were blocked
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert status.check("127.0.0.1", [port]) is Status.ONLINE


def test_a_refused_port_still_proves_the_pc_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status, "_ping", lambda _ip: False)
    # Windows retries a refused connection: about 1 s over the network, 2 s to itself.
    monkeypatch.setattr(status, "TIMEOUT", 4.0)
    with socket.socket() as probe:  # a port nothing listens on: the PC answers "refused"
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    assert status.check("127.0.0.1", [closed]) is Status.ONLINE


def test_silence_is_offline_within_the_timeouts() -> None:
    began = time.monotonic()
    assert status.check("192.0.2.1", [445, 3389]) is Status.OFFLINE  # never a real host
    assert time.monotonic() - began < status.TIMEOUT + 1


def test_a_name_that_doesnt_resolve_says_so() -> None:
    assert status.check("no-such-host.invalid", [445]) is Status.UNKNOWN_NAME
