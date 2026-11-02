"""A small SNMP client that only reads, over v2c or v3. It sends Get, GetNext and GetBulk
requests and has no Set request at all, so it can't change anything on a printer. The community
string and the v3 passwords go only into the request packets (v3's as keys), never into a log.

Answers come over UDP from the network, so every length and count in them is checked before
it's used: a malformed or oversized answer raises SnmpError, never a crash or a huge loop."""

import secrets
import socket
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

from capypanel.core.printers import usm

PORT = 161
TIMEOUT = 1.5  # seconds to wait for each answer
RETRIES = 1  # one more try: UDP may drop a packet
LIMIT = 30.0  # seconds for everything one Session asks: a printer slow on purpose can't hold on
MAX_REPETITIONS = 20  # rows one GetBulk asks for
MAX_ROWS = 400  # a walk stops here: no printer table is anywhere near this long
_MAX_ANSWER = 65_535
_V2C, _V3 = 1, 3  # the version numbers SNMP v2c and v3 put in their messages
_USM = 3  # v3's user-based security model, the only one printers use
_AUTH, _PRIVACY, _REPORTABLE = 0x01, 0x02, 0x04  # v3's message flags
_MAX_SIZE = 65_507  # the biggest answer v3 says it takes: a UDP packet's payload

# Tags of the values SNMP sends (BER encoding).
_INTEGER, _OCTETS, _NULL, _OID, _SEQUENCE = 0x02, 0x04, 0x05, 0x06, 0x30
_IP_ADDRESS, _COUNTER32, _GAUGE32, _TIMETICKS, _OPAQUE, _COUNTER64 = (
    0x40, 0x41, 0x42, 0x43, 0x44, 0x46,
)  # fmt: skip
_UNSIGNED = {_COUNTER32, _GAUGE32, _TIMETICKS, _COUNTER64}
_NO_SUCH_OBJECT, _NO_SUCH_INSTANCE, _END_OF_MIB_VIEW = 0x80, 0x81, 0x82

# The requests this client can send, and the answers. There's deliberately no Set (0xA3).
GET, GET_NEXT, RESPONSE, GET_BULK, REPORT = 0xA0, 0xA1, 0xA2, 0xA5, 0xA8
_REQUESTS = {GET, GET_NEXT, GET_BULK}
_ANSWERS = {RESPONSE, REPORT}

Value = int | bytes | str | None  # INTEGER and counters, OCTET STRING, an OID, nothing
Secret = str | usm.Account  # a v2c community string, or a v3 account

# v3's Report answers: what the printer refused (RFC 3414's usmStats counters).
_USM_STATS = "1.3.6.1.6.3.15.1.1."
LEVEL, TIME_WINDOW, USER, ENGINE, AUTH, PRIVACY = (
    "level", "time window", "user", "engine", "auth", "privacy",
)  # fmt: skip
_REFUSALS = {"1": LEVEL, "2": TIME_WINDOW, "3": USER, "4": ENGINE, "5": AUTH, "6": PRIVACY}


class SnmpError(Exception):
    """The printer answered with an error, or something that isn't a valid SNMP answer."""


class NoAnswer(SnmpError):
    """Nothing answered in time: the printer is off, unreachable, or the community is wrong
    (a wrong community gets no answer at all in SNMP)."""


class Refused(SnmpError):
    """The printer answered, but refused the SNMP v3 account: `reason` is USER, AUTH, PRIVACY
    (a wrong password), LEVEL (it wants more or less security) or another Report."""

    def __init__(self, host: str, reason: str) -> None:
        super().__init__(f"{host}: refused ({reason})")
        self.reason = reason


class Kind(Enum):
    VALUE = "value"
    MISSING = "missing"  # the printer doesn't have this object
    END = "end"  # a walk ran past the printer's last object


@dataclass(frozen=True)
class Binding:
    oid: str
    value: Value
    kind: Kind = Kind.VALUE


@dataclass(frozen=True)
class _Engine:
    """A v3 printer's engine: its ID, the keys for it, and its clock, which every request
    repeats so an old message can't be replayed."""

    id: bytes
    boots: int
    time: int
    at: float  # time.monotonic() when `time` was read
    keys: usm.Keys

    def now(self) -> int:
        return self.time + int(time.monotonic() - self.at)


class Session:
    """Requests to one printer. Use it in a `with` block, so the socket closes."""

    def __init__(
        self,
        host: str,
        secret: Secret,
        *,
        port: int = PORT,
        timeout: float = TIMEOUT,
        retries: int = RETRIES,
        limit: float = LIMIT,
    ) -> None:
        self._secret = secret
        self._engine: _Engine | None = None  # v3: found with the first request
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
        request_id = _random_id()
        bindings = [(o, None) for o in oids]
        if isinstance(self._secret, usm.Account):
            return self._ask_v3(self._secret, pdu, request_id, bindings, a, b)
        packet = message(self._secret.encode(), pdu, request_id, bindings, a, b)

        def read(data: bytes) -> Answer | None:
            answer = parse(data)
            return answer if answer.request_id == request_id else None  # None: a late one

        answer = self._exchange(packet, read)
        if answer.error_status:
            raise SnmpError(f"{self._host}: error {answer.error_status}")
        return answer.bindings

    def _ask_v3(
        self,
        account: usm.Account,
        pdu: int,
        request_id: int,
        bindings: Sequence[tuple[str, Value]],
        a: int,
        b: int,
    ) -> list[Binding]:
        if self._engine is None:
            self._engine = self._discover(account)
        for attempt in range(2):  # once more when the printer sets our copy of its clock right
            engine, message_id = self._engine, _random_id()
            packet = message_v3(
                pdu, request_id, bindings, a, b, message_id=message_id,
                user=account.user.encode(), engine_id=engine.id, boots=engine.boots,
                engine_time=engine.now(), keys=engine.keys, privacy=account.privacy is not None,
            )  # fmt: skip
            answer = self._exchange(packet, lambda data, m=message_id: self._read_v3(data, m))
            if answer.pdu == REPORT:
                reason = _refusal(answer.bindings)
                if reason == TIME_WINDOW and attempt == 0:
                    continue
                raise Refused(self._host, reason)
            if answer.request_id != request_id:
                raise SnmpError(f"{self._host}: answer to another request")
            if answer.error_status:
                raise SnmpError(f"{self._host}: error {answer.error_status}")
            return answer.bindings
        raise Refused(self._host, TIME_WINDOW)

    def _discover(self, account: usm.Account) -> _Engine:
        """v3's first step: an empty request that the printer answers with a Report holding
        its engine ID and clock, which the keys and every later request need."""
        message_id = _random_id()
        packet = message_v3(
            GET, _random_id(), [], message_id=message_id, user=b"", engine_id=b"",
            boots=0, engine_time=0, keys=usm.Keys(), privacy=False,
        )  # fmt: skip

        def read(data: bytes) -> Header | None:
            header = parse_v3(data)
            return header if header.message_id == message_id else None

        header = self._exchange(packet, read)
        if not header.engine_id:
            raise SnmpError(f"{self._host}: no SNMP v3 engine ID")
        keys = usm.keys(account, header.engine_id)
        return _Engine(header.engine_id, header.boots, header.time, time.monotonic(), keys)

    def _read_v3(self, data: bytes, message_id: int) -> "Answer | None":
        """A v3 answer to our message, checked; None for one to ignore: a late answer, or one
        whose signature doesn't match (garbled, or not from the printer)."""
        engine = self._engine
        assert engine is not None
        header = parse_v3(data)
        if header.message_id != message_id:
            return None
        if header.flags & _AUTH:
            if engine.keys.auth is None or not usm.verified(engine.keys, data, header.auth_at):
                return None
            # A signed answer carries the printer's clock: keep ours in step with it.
            self._engine = _Engine(
                engine.id, header.boots, header.time, time.monotonic(), engine.keys
            )
        elif engine.keys.auth is not None and not _is_report(header):
            return None  # we sign, so its answer must be signed; only refusals can't be
        return open_v3(header, engine.keys)

    def _exchange[T](self, packet: bytes, read: Callable[[bytes], T | None]) -> T:
        """Sends `packet` until `read` accepts an answer, within the timeout, the retries and
        the session's limit."""
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
                found = read(data)
                if found is not None:
                    return found
        if time.monotonic() >= self._until:
            raise SnmpError(f"{self._host}: answers too slowly")
        raise NoAnswer(f"{self._host}: no answer")


def _random_id() -> int:
    return secrets.randbelow(2**31 - 1) + 1


def _refusal(bindings: list[Binding]) -> str:
    """What a v3 Report says was wrong."""
    for binding in bindings:
        if binding.oid.startswith(_USM_STATS):
            return _REFUSALS.get(binding.oid[len(_USM_STATS) :].split(".")[0], "report")
    return "report"


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
    body = _tlv(pdu, _pdu_body(request_id, bindings, a, b))
    return _tlv(_SEQUENCE, _integer(_V2C) + _tlv(_OCTETS, community) + body)


def message_v3(
    pdu: int,
    request_id: int,
    bindings: Iterable[tuple[str, Value | tuple[int, bytes]]],
    a: int = 0,
    b: int = 0,
    *,
    message_id: int,
    user: bytes,
    engine_id: bytes,
    boots: int,
    engine_time: int,
    keys: usm.Keys,
    privacy: bool,
) -> bytes:
    """A whole SNMP v3 message, signed when `keys` has an authentication key and encrypted
    when `privacy` is set. Only reads, plus the Response and Report a test agent sends."""
    if pdu not in _REQUESTS and pdu not in _ANSWERS:
        raise ValueError("this client only reads")
    pdu_part = _tlv(pdu, _pdu_body(request_id, bindings, a, b))
    scoped = _tlv(_SEQUENCE, _tlv(_OCTETS, engine_id) + _tlv(_OCTETS, b"") + pdu_part)
    signing = keys.auth is not None
    flags = (_REPORTABLE if pdu in _REQUESTS else 0) | (_AUTH if signing else 0)
    salt = b""
    if privacy:
        flags |= _PRIVACY
        encrypted, salt = usm.encrypt(keys, boots, engine_time, scoped)
        scoped = _tlv(_OCTETS, encrypted)
    zeros = bytes(keys.auth.length if keys.auth else 0)  # the signature's place, until signed
    before = (
        _tlv(_OCTETS, engine_id) + _integer(boots) + _integer(engine_time) + _tlv(_OCTETS, user)
    )
    fields = before + _tlv(_OCTETS, zeros) + _tlv(_OCTETS, salt)
    params = _tlv(_OCTETS, _tlv(_SEQUENCE, fields))
    header = _integer(message_id) + _integer(_MAX_SIZE) + _tlv(_OCTETS, bytes([flags]))
    head = _integer(_V3) + _tlv(_SEQUENCE, header + _integer(_USM))
    whole = _tlv(_SEQUENCE, head + params + scoped)
    if not signing:
        return whole
    # The signature sits past the outer header, the version and global data, the parameters'
    # two headers (octet string, sequence), the fields before it, and its own tag and length.
    outer = len(whole) - len(head) - len(params) - len(scoped)
    at = outer + len(head) + (len(params) - len(fields)) + len(before) + 2
    return usm.signed(keys, whole, at)


def _pdu_body(
    request_id: int, bindings: Iterable[tuple[str, Value | tuple[int, bytes]]], a: int, b: int
) -> bytes:
    varbinds = b"".join(_tlv(_SEQUENCE, _oid(oid) + _value(v)) for oid, v in bindings)
    return _integer(request_id) + _integer(a) + _integer(b) + _tlv(_SEQUENCE, varbinds)


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
    return _pdu(pdu, data, pos, pdu_end, community)


@dataclass(frozen=True)
class Header:
    """An SNMP v3 message up to its contents, which may still be encrypted."""

    message_id: int
    flags: int
    engine_id: bytes
    boots: int
    time: int
    user: bytes
    auth_at: int  # where the signature starts in the message
    salt: bytes
    payload: bytes  # the scoped PDU, or its encrypted bytes when flags has _PRIVACY


def parse_v3(data: bytes) -> Header:
    """An SNMP v3 message's header. Raises SnmpError when anything about it is wrong; the
    caller, which has the keys, checks its signature."""
    tag, start, end = _read(data, 0, len(data))
    if tag != _SEQUENCE or end != len(data):
        raise SnmpError("not an SNMP message")
    tag, s, pos = _read(data, start, end)
    if tag != _INTEGER or _signed(data[s:pos]) != _V3:
        raise SnmpError("not SNMP v3")
    tag, s, pos = _read(data, pos, end)
    if tag != _SEQUENCE:
        raise SnmpError("malformed header")
    message_id, s = _int_field(data, s, pos)
    _size, s = _int_field(data, s, pos)
    flags, s = _octets_field(data, s, pos)
    model, s = _int_field(data, s, pos)
    if len(flags) != 1 or model != _USM or s != pos:
        raise SnmpError("malformed header")
    tag, s, pos = _read(data, pos, end)
    if tag != _OCTETS:
        raise SnmpError("no security parameters")
    tag, p, params_end = _read(data, s, pos)
    if tag != _SEQUENCE or params_end != pos:
        raise SnmpError("malformed security parameters")
    engine_id, p = _octets_field(data, p, params_end)
    boots, p = _int_field(data, p, params_end)
    clock, p = _int_field(data, p, params_end)
    user, p = _octets_field(data, p, params_end)
    tag, auth_at, p = _read(data, p, params_end)
    if tag != _OCTETS:
        raise SnmpError("malformed security parameters")
    salt, p = _octets_field(data, p, params_end)
    if p != params_end or not 0 <= boots < 2**31 or not 0 <= clock < 2**31:
        raise SnmpError("malformed security parameters")
    if len(engine_id) > 32 or len(user) > 32:
        raise SnmpError("malformed security parameters")
    return Header(message_id, flags[0], engine_id, boots, clock, user, auth_at, salt, data[pos:end])


def open_v3(header: Header, keys: usm.Keys) -> Answer:
    """A v3 message's contents, decrypted if they were encrypted."""
    payload = header.payload
    if header.flags & _PRIVACY:
        tag, s, end = _read(payload, 0, len(payload))
        if tag != _OCTETS or end != len(payload) or not keys.privacy_key:
            raise SnmpError("can't decrypt the answer")
        try:
            payload = usm.decrypt(keys, header.boots, header.time, header.salt, payload[s:end])
        except ValueError as e:
            raise SnmpError("can't decrypt the answer") from e
    tag, start, end = _read(payload, 0, len(payload))
    if tag != _SEQUENCE:  # a wrong key decrypts to noise
        raise SnmpError("can't decrypt the answer")
    _engine, pos = _octets_field(payload, start, end)
    _context, pos = _octets_field(payload, pos, end)
    pdu, pos, pdu_end = _read(payload, pos, end)
    if pdu not in _REQUESTS and pdu not in _ANSWERS:
        raise SnmpError(f"unexpected message type {pdu:#x}")
    return _pdu(pdu, payload, pos, pdu_end)


def _is_report(header: Header) -> bool:
    """Whether an unsigned v3 answer is a Report, which can come unsigned: a printer can't
    sign with the key of a user it doesn't know."""
    if header.flags & _PRIVACY:
        return False
    try:
        return open_v3(header, usm.Keys()).pdu == REPORT
    except SnmpError:
        return False


def _int_field(data: bytes, pos: int, end: int) -> tuple[int, int]:
    tag, s, pos = _read(data, pos, end)
    if tag != _INTEGER:
        raise SnmpError("malformed header")
    return _signed(data[s:pos]), pos


def _octets_field(data: bytes, pos: int, end: int) -> tuple[bytes, int]:
    tag, s, pos = _read(data, pos, end)
    if tag != _OCTETS:
        raise SnmpError("malformed header")
    return bytes(data[s:pos]), pos


def _pdu(pdu: int, data: bytes, pos: int, end: int, community: bytes = b"") -> Answer:
    """A request's or answer's numbers and variable bindings."""
    numbers = []
    for _ in range(3):
        tag, s, pos = _read(data, pos, end)
        if tag != _INTEGER:
            raise SnmpError("malformed header")
        numbers.append(_signed(data[s:pos]))
    tag, pos, list_end = _read(data, pos, end)
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
