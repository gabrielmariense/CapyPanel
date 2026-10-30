"""A small SNMP v2c client that only reads. It sends Get, GetNext and GetBulk requests and has
no Set request at all, so it can't change anything on a printer. The community string goes only
into the request packets, never into a log.

Answers come over UDP from the network, so every length and count in them is checked before
it's used: a malformed or oversized answer raises SnmpError, never a crash or a huge loop."""

import secrets
import socket
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

PORT = 161
TIMEOUT = 1.5  # seconds to wait for each answer
RETRIES = 1  # one more try: UDP may drop a packet
LIMIT = 30.0  # seconds for everything one Session asks: a printer slow on purpose can't hold on
MAX_REPETITIONS = 20  # rows one GetBulk asks for
MAX_ROWS = 400  # a walk stops here: no printer table is anywhere near this long
_MAX_ANSWER = 65_535
_V2C = 1  # the version number SNMP v2c puts in its messages

# Tags of the values SNMP sends (BER encoding).
_INTEGER, _OCTETS, _NULL, _OID, _SEQUENCE = 0x02, 0x04, 0x05, 0x06, 0x30
_IP_ADDRESS, _COUNTER32, _GAUGE32, _TIMETICKS, _OPAQUE, _COUNTER64 = (
    0x40, 0x41, 0x42, 0x43, 0x44, 0x46,
)  # fmt: skip
_UNSIGNED = {_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64}
_NO_SUCH_OBJECT, _NO_SUCH_INSTANCE, _END_OF_MIB_VIEW = 0x80, 0x81, 0x82

# The requests this client can send, and the answer. There's deliberately no Set (0xA3).
GET, GET_NEXT, RESPONSE, GET_BULK = 0xA0, 0xA1, 0xA2, 0xA5
_REQUESTS = {GET, GET_NEXT, GET_BULK}

Value = int | bytes | str | None  # INTEGER and counters, OCTET STRING, an OID, nothing


class SnmpError(Exception):
    """The printer answered with an error, or something that isn't a valid SNMP answer."""


class NoAnswer(SnmpError):
    """Nothing answered in time: the printer is off, unreachable, or the community is wrong
    (a wrong community gets no answer at all in SNMP)."""


class Kind(Enum):
    VALUE = "value"
    MISSING = "missing"  # the printer doesn't have this object
    END = "end"  # a walk ran past the printer's last object


@dataclass(frozen=True)
class Binding:
    oid: str
    value: Value
    kind: Kind = Kind.VALUE


class Session:
    """Requests to one printer. Use it in a `with` block, so the socket closes."""

    def __init__(
        self,
        host: str,
        community: str,
        *,
        port: int = PORT,
        timeout: float = TIMEOUT,
        retries: int = RETRIES,
        limit: float = LIMIT,
    ) -> None:
        self._community = community.encode()
        self._timeout, self._retries = timeout, retries
        self._until = time.monotonic() + limit
        try:
            family, _type, _proto, _name, address = socket.getaddrinfo(
                host, port, type=socket.SOCK_DGRAM
            )[0]
        except (OSError, IndexError) as e:
            raise NoAnswer(f"can't find {host}") from e
        self._host = host
        self._sock = socket.socket(family, socket.SOCK_DGRAM)
        self._sock.connect(address)  # only that address's answers reach this socket

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._sock.close()

    def get(self, oids: Sequence[str]) -> dict[str, Value]:
        """Each object's value; None for one the printer doesn't have."""
        found: dict[str, Value] = dict.fromkeys(oids)
        for binding in self._ask(GET, oids):
            if binding.kind is Kind.VALUE and binding.oid in found:
                found[binding.oid] = binding.value
        return found

    def walk(self, base: str) -> list[tuple[str, Value]]:
        """Every object under `base`, in order, read with GetBulk."""
        prefix, rows = _arcs(base), []
        after = base
        while len(rows) < MAX_ROWS:
            bindings = self._ask(GET_BULK, [after], 0, MAX_REPETITIONS)
            if not bindings:
                break
            for binding in bindings:
                arcs = _arcs(binding.oid)
                if binding.kind is Kind.END or arcs[: len(prefix)] != prefix:
                    return rows
                if arcs <= _arcs(after):  # going backwards: a broken agent, stop rather than loop
                    return rows
                if binding.kind is Kind.VALUE:
                    rows.append((binding.oid, binding.value))
                after = binding.oid
        return rows[:MAX_ROWS]

    def _ask(self, pdu: int, oids: Sequence[str], a: int = 0, b: int = 0) -> list[Binding]:
        """One request and its answer. `a` and `b` are the error fields of Get and GetNext,
        and non-repeaters and max-repetitions for GetBulk."""
        request_id = secrets.randbelow(2**31 - 1) + 1
        packet = message(self._community, pdu, request_id, [(o, None) for o in oids], a, b)
        for _attempt in range(self._retries + 1):
            if time.monotonic() >= self._until:
                raise SnmpError(f"{self._host}: answers too slowly")
            try:
                self._sock.send(packet)
            except OSError as e:
                raise NoAnswer(f"{self._host}: {e}") from e
            deadline = min(time.monotonic() + self._timeout, self._until)
            while (left := deadline - time.monotonic()) > 0:
                self._sock.settimeout(left)
                try:
                    data = self._sock.recv(_MAX_ANSWER)
                except TimeoutError:
                    break
                except ConnectionResetError:  # Windows: the port said "unreachable"
                    raise NoAnswer(f"{self._host}: port {PORT} unreachable") from None
                except OSError as e:
                    raise NoAnswer(f"{self._host}: {e}") from e
                answer = parse(data)
                if answer.request_id != request_id:
                    continue  # a late answer to an earlier request
                if answer.error_status:
                    raise SnmpError(f"{self._host}: error {answer.error_status}")
                return answer.bindings
        if time.monotonic() >= self._until:
            raise SnmpError(f"{self._host}: answers too slowly")
        raise NoAnswer(f"{self._host}: no answer")


# ---- encoding ----


def message(
    community: bytes,
    pdu: int,
    request_id: int,
    bindings: Iterable[tuple[str, Value | tuple[int, bytes]]],
    a: int = 0,
    b: int = 0,
) -> bytes:
    """A whole SNMP v2c message. Only reads, plus the Response a test agent sends back."""
    if pdu not in _REQUESTS and pdu != RESPONSE:
        raise ValueError("this client only reads")
    varbinds = b"".join(_tlv(_SEQUENCE, _oid(oid) + _value(v)) for oid, v in bindings)
    body = _integer(request_id) + _integer(a) + _integer(b) + _tlv(_SEQUENCE, varbinds)
    return _tlv(_SEQUENCE, _integer(_V2C) + _tlv(_OCTETS, community) + _tlv(pdu, body))


def missing() -> tuple[int, bytes]:
    """For a test agent: "no such object"."""
    return (_NO_SUCH_OBJECT, b"")


def end_of_mib() -> tuple[int, bytes]:
    return (_END_OF_MIB_VIEW, b"")


def counter(n: int) -> tuple[int, bytes]:
    """For a test agent: a Counter32."""
    return (_COUNTER32, _integer(n)[2:])


def _value(value: Value | tuple[int, bytes]) -> bytes:
    if value is None:
        return _tlv(_NULL, b"")
    if isinstance(value, tuple):  # a tag and its body, already encoded
        return _tlv(*value)
    if isinstance(value, int):
        return _integer(value)
    if isinstance(value, bytes):
        return _tlv(_OCTETS, value)
    return _oid(value)


def _tlv(tag: int, body: bytes) -> bytes:
    size = len(body)
    if size < 0x80:
        return bytes([tag, size]) + body
    length = size.to_bytes((size.bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(length)]) + length + body


def _integer(n: int) -> bytes:
    return _tlv(_INTEGER, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    arcs = _arcs(oid)
    if len(arcs) < 2 or arcs[0] > 2 or (arcs[0] < 2 and arcs[1] >= 40):
        raise ValueError(f"not an OID: {oid}")
    return _tlv(_OID, b"".join(_base128(n) for n in (40 * arcs[0] + arcs[1], *arcs[2:])))


def _base128(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _arcs(oid: str) -> tuple[int, ...]:
    try:
        return tuple(int(a) for a in oid.strip(".").split("."))
    except ValueError:
        raise ValueError(f"not an OID: {oid}") from None


# ---- decoding ----


@dataclass(frozen=True)
class Answer:
    pdu: int
    request_id: int
    error_status: int
    error_index: int
    bindings: list[Binding]
    community: bytes = b""


def parse(data: bytes) -> Answer:
    """A whole SNMP v2c message. Raises SnmpError when anything about it is wrong."""
    tag, start, end = _read(data, 0, len(data))
    if tag != _SEQUENCE or end != len(data):
        raise SnmpError("not an SNMP message")
    tag, s, pos = _read(data, start, end)
    if tag != _INTEGER or _signed(data[s:pos]) != _V2C:
        raise SnmpError("not SNMP v2c")
    tag, s, pos = _read(data, pos, end)
    if tag != _OCTETS:
        raise SnmpError("no community")
    community = data[s:pos]
    pdu, pos, pdu_end = _read(data, pos, end)
    if pdu not in _REQUESTS and pdu != RESPONSE:
        raise SnmpError(f"unexpected message type {pdu:#x}")
    numbers = []
    for _ in range(3):
        tag, s, pos = _read(data, pos, pdu_end)
        if tag != _INTEGER:
            raise SnmpError("malformed header")
        numbers.append(_signed(data[s:pos]))
    tag, pos, list_end = _read(data, pos, pdu_end)
    if tag != _SEQUENCE:
        raise SnmpError("no variable bindings")
    bindings = []
    while pos < list_end:
        tag, s, pos = _read(data, pos, list_end)
        if tag != _SEQUENCE:
            raise SnmpError("malformed variable binding")
        tag, o, oid_end = _read(data, s, pos)
        if tag != _OID:
            raise SnmpError("malformed variable binding")
        oid = _decode_oid(data[o:oid_end])
        tag, v, value_end = _read(data, oid_end, pos)
        bindings.append(_binding(oid, tag, data[v:value_end]))
        if len(bindings) > MAX_ROWS:
            raise SnmpError("too many variable bindings")
    return Answer(pdu, numbers[0], numbers[1], numbers[2], bindings, community)


def _read(data: bytes, pos: int, end: int) -> tuple[int, int, int]:
    """One tag, and where its body starts and ends, checked against `end`."""
    if pos + 2 > end:
        raise SnmpError("truncated answer")
    tag, first = data[pos], data[pos + 1]
    pos += 2
    if first < 0x80:
        size = first
    else:
        count = first & 0x7F
        if not 1 <= count <= 3 or pos + count > end:
            raise SnmpError("bad length")
        size = int.from_bytes(data[pos : pos + count], "big")
        pos += count
    if pos + size > end:
        raise SnmpError("truncated answer")
    return tag, pos, pos + size


def _binding(oid: str, tag: int, body: bytes) -> Binding:
    if tag in (_NO_SUCH_OBJECT, _NO_SUCH_INSTANCE):
        return Binding(oid, None, Kind.MISSING)
    if tag == _END_OF_MIB_VIEW:
        return Binding(oid, None, Kind.END)
    if tag == _INTEGER:
        return Binding(oid, _signed(body))
    if tag in _UNSIGNED:
        if len(body) > 9:  # Counter64 is 8 bytes, plus a leading zero
            raise SnmpError("bad counter")
        return Binding(oid, int.from_bytes(body, "big") if body else 0)
    if tag == _OID:
        return Binding(oid, _decode_oid(body))
    if tag == _NULL:
        return Binding(oid, None, Kind.MISSING)
    return Binding(oid, bytes(body))  # OCTET STRING, IpAddress, Opaque: as bytes


def _signed(body: bytes) -> int:
    if not body or len(body) > 9:
        raise SnmpError("bad integer")
    return int.from_bytes(body, "big", signed=True)


def _decode_oid(body: bytes) -> str:
    if not body or len(body) > 128:
        raise SnmpError("bad OID")
    arcs, n = [], 0
    for byte in body:
        n = (n << 7) | (byte & 0x7F)
        if not byte & 0x80:
            arcs.append(n)
            n = 0
    if body[-1] & 0x80:
        raise SnmpError("bad OID")
    first = arcs[0]
    head = [0, first] if first < 40 else [1, first - 40] if first < 80 else [2, first - 80]
    return ".".join(str(a) for a in head + arcs[1:])
