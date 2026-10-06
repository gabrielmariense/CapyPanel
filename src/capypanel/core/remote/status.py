"""Is a computer up? A ping and the ports CapyPanel connects to, all at the same time: many
Windows PCs block ping, and a port that answers, even with a refusal, proves the PC is on.
Every address the name has is tried (a PC on cable and Wi-Fi has two). No account is used and
nothing runs on the target."""

import ctypes
import logging
import selectors
import socket
import threading
import time
from collections.abc import Iterable
from ctypes import wintypes
from enum import StrEnum

log = logging.getLogger(__name__)
TIMEOUT = 2.0  # seconds for the whole check; Windows retries a refused port for about 1 s
PING_TIMEOUT = 1.0
BASE_PORTS = (445, 22)  # Windows file sharing and SSH, besides each tool's own port
_REFUSED = (10061, 111)  # WSAECONNREFUSED, ECONNREFUSED: something answered
_SLICE = 0.1  # how often the ports wait checks whether a ping already answered


class Status(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"  # nothing answered in time
    NOT_FOUND = "not-found"  # the name or address couldn't be resolved


Answer = tuple[str, int | None]  # the address that answered, and its port (None: a ping)


def check(host: str, ports: Iterable[int]) -> Status:
    return probe(host, ports)[0]


def probe(host: str, ports: Iterable[int]) -> tuple[Status, Answer | None]:
    """The status, and what answered: shows a PC reached only over its Wi-Fi, say."""
    try:
        addresses = _resolve(host)
    except OSError:
        return Status.NOT_FOUND, None
    pinged: list[str] = []  # the address that answered a ping, once one does
    answered = threading.Event()

    def ping(ip: str) -> None:
        if _ping(ip):
            pinged.append(ip)
            answered.set()

    for family, ip in addresses:
        if family == socket.AF_INET:
            threading.Thread(target=ping, args=(ip,), daemon=True).start()
    via = _any_port_answers(addresses, sorted(set(ports)), answered)
    if via is None and answered.is_set():
        via = (pinged[0], None)
    seen = f"online ({via[0]}, {via[1] or 'ping'})" if via else "offline"
    log.info("Status of %s: %s", host, seen)
    return (Status.ONLINE, via) if via else (Status.OFFLINE, None)


def _resolve(host: str) -> list[tuple[int, str]]:
    found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    unique: dict[tuple[int, str], None] = {}
    for family, _type, _proto, _name, sockaddr in found:
        unique[(family, str(sockaddr[0]))] = None
    return list(unique)


def _any_port_answers(
    addresses: list[tuple[int, str]], ports: list[int], pinged: threading.Event
) -> Answer | None:
    """What answered first, or None after TIMEOUT. A ping answering ends the wait too (the
    caller names it)."""
    deadline = time.monotonic() + TIMEOUT
    selector = selectors.DefaultSelector()
    sockets: list[socket.socket] = []
    try:
        for family, ip in addresses:
            for port in ports:
                sock = socket.socket(family, socket.SOCK_STREAM)
                sock.setblocking(False)
                sockets.append(sock)
                code = sock.connect_ex((ip, port))
                if code == 0 or code in _REFUSED:
                    return ip, port
                selector.register(sock, selectors.EVENT_WRITE, (ip, port))
        while (left := deadline - time.monotonic()) > 0:
            if pinged.is_set():
                return None
            if not selector.get_map():  # every port gave up: only a ping can still answer
                pinged.wait(min(left, _SLICE))
                continue
            # A finished connect, accepted or refused, shows as writable (or as an error).
            for key, _events in selector.select(min(left, _SLICE)):
                sock = key.fileobj
                assert isinstance(sock, socket.socket)
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code == 0 or code in _REFUSED:
                    return key.data
                selector.unregister(sock)
        return None
    finally:
        selector.close()
        for sock in sockets:
            sock.close()


# ---- ping (IcmpSendEcho: no administrator rights needed, unlike raw sockets) ----

_iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)
_iphlpapi.IcmpCreateFile.restype = wintypes.HANDLE
_iphlpapi.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
_iphlpapi.IcmpSendEcho.restype = wintypes.DWORD
_iphlpapi.IcmpSendEcho.argtypes = [
    wintypes.HANDLE, ctypes.c_uint32, ctypes.c_void_p, wintypes.WORD,
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
]  # fmt: skip
_INVALID_HANDLE = wintypes.HANDLE(-1).value


def _ping(ip: str) -> bool:
    handle = _iphlpapi.IcmpCreateFile()
    if not handle or handle == _INVALID_HANDLE:
        return False
    try:
        payload = b"CapyPanel"
        reply = ctypes.create_string_buffer(256)  # an ICMP_ECHO_REPLY plus the echoed data
        target = int.from_bytes(socket.inet_aton(ip), "little")  # network order in memory
        count = _iphlpapi.IcmpSendEcho(
            handle, target, payload, len(payload), None, reply, len(reply),
            int(PING_TIMEOUT * 1000),
        )  # fmt: skip
        # The reply's Status (offset 4) is 0 only for an echo reply, not "destination unreachable".
        return bool(count) and int.from_bytes(reply.raw[4:8], "little") == 0
    finally:
        _iphlpapi.IcmpCloseHandle(handle)
