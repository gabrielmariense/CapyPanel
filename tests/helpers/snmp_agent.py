"""A pretend printer for tests: an SNMP agent on 127.0.0.1 that answers Get, GetNext and GetBulk
from a table of invented objects. Over v2c a wrong community gets no answer, like a real one;
given a v3 account, it speaks v3 instead and refuses a wrong user, password or level with the
Report a real printer sends."""

import socket
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from capypanel.core.printers import snmp, usm

Objects = Mapping[str, snmp.Value | tuple[int, bytes]]
ENGINE_ID = b"\x80\x00\x1f\x88\x80SAMPLE01"  # an invented engine ID
# usmStats, the Report counters: 1 level, 2 time window, 3 user, 4 engine, 5 auth, 6 privacy
_STATS = "1.3.6.1.6.3.15.1.1."
_WINDOW = 150  # seconds a v3 message's clock may differ from the agent's (RFC 3414)


def _arcs(oid: str) -> tuple[int, ...]:
    return tuple(int(a) for a in oid.split("."))


class Agent:
    def __init__(
        self,
        objects: Objects,
        community: bytes = b"public",
        account: usm.Account | None = None,
        *,
        tells_time: bool = True,  # v3: whether its first Report gives its clock (some don't)
    ) -> None:
        self.objects = dict(objects)
        self.community = community
        self.account = account
        self.tells_time = tells_time
        self.boots, self._clock_start = 7, time.monotonic() - 5000
        self._keys = usm.keys(account, ENGINE_ID) if account else usm.Keys()
        self.requests: list[int] = []  # the message types it received, in order
        self.answering = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self.port: int = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._sock.close()

    def _ordered(self) -> list[str]:
        return sorted(self.objects, key=_arcs)

    def _next(self, oid: str) -> tuple[str, snmp.Value | tuple[int, bytes]]:
        for name in self._ordered():
            if _arcs(name) > _arcs(oid):
                return name, self.objects[name]
        return oid, snmp.end_of_mib()

    def _answer(self, asked: snmp.Answer) -> list[tuple[str, snmp.Value | tuple[int, bytes]]]:
        oids = [b.oid for b in asked.bindings]
        if asked.pdu == snmp.GET:
            return [(o, self.objects.get(o, snmp.missing())) for o in oids]
        if asked.pdu == snmp.GET_NEXT:
            return [self._next(o) for o in oids]
        answer = []  # GetBulk: no non-repeaters here, `error_index` rows after each OID
        for oid in oids:
            for _ in range(asked.error_index):
                oid, value = self._next(oid)
                answer.append((oid, value))
                if value == snmp.end_of_mib():
                    break
        return answer

    def _serve(self) -> None:
        while True:
            try:
                data, sender = self._sock.recvfrom(65535)
            except OSError:
                return
            if self.account is not None:
                self._serve_v3(data, sender)
                continue
            asked = snmp.parse(data)
            self.requests.append(asked.pdu)
            if not self.answering or asked.community != self.community:
                continue
            answer = self._answer(asked)
            reply = snmp.message(self.community, snmp.RESPONSE, asked.request_id, answer)
            self._sock.sendto(reply, sender)

    def _serve_v3(self, data: bytes, sender: tuple[str, int]) -> None:
        account = self.account
        assert account is not None
        header = snmp.parse_v3(data)
        now = int(time.monotonic() - self._clock_start)

        def reply(
            pdu: int, request_id: int, bindings: list, *, sign: bool, clock: bool = True
        ) -> None:
            packet = snmp.message_v3(
                pdu, request_id, bindings, message_id=header.message_id, user=header.user,
                engine_id=ENGINE_ID, boots=self.boots if clock else 0,
                engine_time=now if clock else 0, keys=self._keys if sign else usm.Keys(),
                privacy=sign and account.privacy is not None and pdu == snmp.RESPONSE,
            )  # fmt: skip
            self._sock.sendto(packet, sender)

        def refuse(counter: int, *, sign: bool = False) -> None:
            self.requests.append(snmp.REPORT)
            reply(snmp.REPORT, 0, [(f"{_STATS}{counter}.0", snmp.counter(1))], sign=sign)

        if not self.answering:
            return
        if not header.engine_id:  # discovery: tell the engine ID, and maybe the clock
            self.requests.append(snmp.open_v3(header, usm.Keys()).pdu)
            self.requests.append(snmp.REPORT)
            reply(snmp.REPORT, 0, [(f"{_STATS}4.0", snmp.counter(1))], sign=False,
                  clock=self.tells_time)  # fmt: skip
            return
        if header.user != account.user.encode():
            return refuse(3)
        signed, encrypted = bool(header.flags & 0x01), bool(header.flags & 0x02)
        if signed != (account.auth is not None) or encrypted != (account.privacy is not None):
            return refuse(1)
        if signed and not usm.verified(self._keys, data, header.auth_at):
            return refuse(5)
        if signed and (header.boots != self.boots or abs(header.time - now) > _WINDOW):
            return refuse(2, sign=True)  # signed, so the client can trust the clock in it
        try:
            asked = snmp.open_v3(header, self._keys)
        except snmp.SnmpError:
            return refuse(6)
        self.requests.append(asked.pdu)
        reply(snmp.RESPONSE, asked.request_id, self._answer(asked), sign=signed)


@contextmanager
def running(
    objects: Objects,
    community: bytes = b"public",
    account: usm.Account | None = None,
    *,
    tells_time: bool = True,
) -> Iterator[Agent]:
    agent = Agent(objects, community, account, tells_time=tells_time)
    try:
        yield agent
    finally:
        agent.close()
