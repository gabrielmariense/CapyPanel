"""Is a computer up? A ping and the ports CapyPanel connects to, all at the same time: many
Windows PCs block ping, and a port that answers, even with a refusal, proves the PC is on.
No account is used and nothing runs on the target."""

import ctypes
import selectors
import socket
import threading
import time
from collections.abc import Iterable
from ctypes import wintypes
from enum import StrEnum

TIMEOUT = 2.0  # seconds for the whole check; Windows retries a refused port for about 1 s
PING_TIMEOUT = 1.0
BASE_PORTS = (445, 22)  # Windows file sharing and SSH, besides each tool's own port
_REFUSED = (10061, 111)  # WSAECONNREFUSED, ECONNREFUSED: something answered
_SLICE = 0.1  # how often the ports wait checks whether the ping already answered


class Status(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"  # nothing answered in time
    UNKNOWN_NAME = "unknown-name"  # the name couldn't be resolved to an address


def check(host: str, ports: Iterable[int]) -> Status:
    try:
        family, ip = _resolve(host)
    except OSError:
        return Status.UNKNOWN_NAME
    pinged = threading.Event()
    if family == socket.AF_INET:
        threading.Thread(target=lambda: _ping(ip) and pinged.set(), daemon=True).start()
    up = _any_port_answers(family, ip, sorted(set(ports)), pinged)
    return Status.ONLINE if up else Status.OFFLINE


def _resolve(host: str) -> tuple[int, str]:
    """IPv4 first: the ping speaks only IPv4."""
    found = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    found.sort(key=lambda entry: entry[0] != socket.AF_INET)
    family, _type, _proto, _name, sockaddr = found[0]
    return family, str(sockaddr[0])


def _any_port_answers(family: int, ip: str, ports: list[int], pinged: threading.Event) -> bool:
    """True as soon as a port connects or refuses, or the ping answers; False after TIMEOUT."""
    deadline = time.monotonic() + TIMEOUT
    selector = selectors.DefaultSelector()
    sockets = []
    try:
        for port in ports:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setblocking(False)
            sockets.append(sock)
            code = sock.connect_ex((ip, port))
            if code == 0 or code in _REFUSED:
                return True
            selector.register(sock, selectors.EVENT_WRITE)
        while (left := deadline - time.monotonic()) > 0:
            if pinged.is_set():
                return True
            if not selector.get_map():  # every port gave up: only the ping can still answer
                pinged.wait(min(left, _SLICE))
                continue
            # A finished connect, accepted or refused, shows as writable (or as an error).
            for key, _events in selector.select(min(left, _SLICE)):
                sock = key.fileobj
                assert isinstance(sock, socket.socket)
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code == 0 or code in _REFUSED:
                    return True
                selector.unregister(sock)
        return pinged.is_set()
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
