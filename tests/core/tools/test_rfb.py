import contextlib
import socket
import threading

import pytest

from capypanel.core.tools import rfb


def _fake(*chunks: bytes) -> tuple[int, list[bytes], threading.Thread]:
    """A fake VNC server for one connection on localhost; returns its port and what it got."""
    received: list[bytes] = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    def serve() -> None:
        conn, _addr = listener.accept()
        with conn:
            conn.settimeout(2)
            for index, chunk in enumerate(chunks):
                conn.sendall(chunk)
                if index == 0 and len(chunks) > 1:
                    received.append(conn.recv(12))  # the client's version
            with contextlib.suppress(OSError):
                received.append(conn.recv(64))  # anything more: b"" when the client hangs up
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return listener.getsockname()[1], received, thread


def test_reads_the_login_types_of_a_3_8_server_and_picks_none() -> None:
    port, received, server = _fake(b"RFB 003.008\n", bytes([3, 17, 117, 2]))
    assert rfb.security_types("127.0.0.1", port, timeout=2) == (17, 117, 2)
    server.join(5)
    assert received == [b"RFB 003.008\n", b""]  # its version, then nothing: no login attempt


def test_an_old_3_3_server_names_its_one_type() -> None:
    port, _received, _server = _fake(b"RFB 003.003\n", (2).to_bytes(4, "big"))
    assert rfb.security_types("127.0.0.1", port, timeout=2) == (2,)


def test_a_server_that_refuses_says_why() -> None:
    reason = b"Too many authentication failures"
    port, _received, _server = _fake(
        b"RFB 003.008\n", bytes([0]) + len(reason).to_bytes(4, "big") + reason
    )
    with pytest.raises(rfb.ProbeError, match="refused: Too many authentication failures"):
        rfb.security_types("127.0.0.1", port, timeout=2)


@pytest.mark.parametrize("greeting", [b"SSH-2.0-OpenS", b"RFB 3.8\n"])
def test_something_that_is_not_vnc_is_an_error(greeting: bytes) -> None:
    port, _received, _server = _fake(greeting.ljust(12, b"x"))
    with pytest.raises(rfb.ProbeError):
        rfb.security_types("127.0.0.1", port, timeout=2)


def test_nobody_listening_is_an_error() -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    with pytest.raises(rfb.ProbeError):
        rfb.security_types("127.0.0.1", port, timeout=1)
