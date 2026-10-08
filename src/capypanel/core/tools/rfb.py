"""Asking a VNC server which login types it offers, without logging in: read its greeting,
answer with a protocol version, read the list, hang up. One short connection, nothing sent
that could count as a login attempt."""

import re
import socket
import struct

_VERSION = re.compile(rb"^RFB (\d{3})\.(\d{3})\n$")


class ProbeError(OSError):
    """The server couldn't be reached or didn't answer like a VNC server."""


def security_types(address: str, port: int, timeout: float = 3.0) -> tuple[int, ...]:
    """The login types the server offers, in its order. Raises ProbeError."""
    try:
        with socket.create_connection((address, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            greeting = _read(sock, 12)
            match = _VERSION.match(greeting)
            if not match:
                raise ProbeError("not a VNC server")
            major, minor = int(match[1]), int(match[2])
            if (major, minor) >= (3, 7):
                sock.sendall(b"RFB 003.008\n" if (major, minor) >= (3, 8) else b"RFB 003.007\n")
                count = _read(sock, 1)[0]
                if count == 0:  # turned away before offering anything (e.g. too many failures)
                    raise ProbeError(f"the server refused: {_reason(sock)}")
                return tuple(_read(sock, count))
            sock.sendall(b"RFB 003.003\n")  # 3.3: the server picks a single type itself
            (chosen,) = struct.unpack(">I", _read(sock, 4))
            if chosen == 0:
                raise ProbeError(f"the server refused: {_reason(sock)}")
            return (chosen,)
    except (OSError, IndexError) as e:
        if isinstance(e, ProbeError):
            raise
        raise ProbeError(str(e)) from e


def _reason(sock: socket.socket) -> str:
    """The server's explanation after a refusal, cut to a sane length; "" if it gave none."""
    try:
        (size,) = struct.unpack(">I", _read(sock, 4))
        return _read(sock, min(size, 1024)).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _read(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProbeError("the server closed the connection")
        data += chunk
    return data
