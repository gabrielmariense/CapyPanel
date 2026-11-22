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
_SLICE = 0.1  # seconds


class Status(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    NOT_FOUND = "not-found"


class PortState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    NO_ANSWER = "no-answer"
    NOT_FOUND = "not-found"


Answer = tuple[str, int | None]


def probe(host: str, ports: Iterable[int]) -> tuple[Status, Answer | None]:
    try:
        addresses = _resolve(host)
    except OSError:
        return Status.NOT_FOUND, None
    pinged: list[str] = []
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
            if not selector.get_map():
                pinged.wait(min(left, _SLICE))
                continue
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


def port_state(host: str, port: int) -> tuple[PortState, str | None]:
    try:
        addresses = _resolve(host)
    except OSError:
        return PortState.NOT_FOUND, None
    state, ip = _port_answers(addresses, port)
    log.info("Port %d of %s: %s%s", port, host, state.value, f" ({ip})" if ip else "")
    return state, ip


def _port_answers(addresses: list[tuple[int, str]], port: int) -> tuple[PortState, str | None]:
    deadline = time.monotonic() + TIMEOUT
    selector = selectors.DefaultSelector()
    sockets: list[socket.socket] = []
    refused: str | None = None
    try:
        for family, ip in addresses:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setblocking(False)
            sockets.append(sock)
            code = sock.connect_ex((ip, port))
            if code == 0:
                return PortState.OPEN, ip
            if code in _REFUSED:
                refused = refused or ip
                continue
            selector.register(sock, selectors.EVENT_WRITE, ip)
        while selector.get_map() and (left := deadline - time.monotonic()) > 0:
            for key, _events in selector.select(min(left, _SLICE)):
                sock = key.fileobj
                assert isinstance(sock, socket.socket)
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code == 0:
                    return PortState.OPEN, key.data
                if code in _REFUSED:
                    refused = refused or key.data
                selector.unregister(sock)
        return (PortState.CLOSED, refused) if refused else (PortState.NO_ANSWER, None)
    finally:
        selector.close()
        for sock in sockets:
            sock.close()


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
        target = int.from_bytes(socket.inet_aton(ip), "little")
        count = _iphlpapi.IcmpSendEcho(
            handle, target, payload, len(payload), None, reply, len(reply),
            int(PING_TIMEOUT * 1000),
        )  # fmt: skip
        # The reply's Status (offset 4) is 0 only for an echo reply, not "destination unreachable".
        return bool(count) and int.from_bytes(reply.raw[4:8], "little") == 0
    finally:
        _iphlpapi.IcmpCloseHandle(handle)
