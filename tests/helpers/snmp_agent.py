"""A pretend printer for tests: an SNMP v2c agent on 127.0.0.1 that answers Get, GetNext and
GetBulk from a table of invented objects. A wrong community gets no answer, like a real one."""

import socket
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from capypanel.core.printers import snmp

Objects = Mapping[str, snmp.Value | tuple[int, bytes]]


def _arcs(oid: str) -> tuple[int, ...]:
    return tuple(int(a) for a in oid.split("."))


class Agent:
    def __init__(self, objects: Objects, community: bytes = b"public") -> None:
        self.objects = dict(objects)
        self.community = community
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

    def _serve(self) -> None:
        while True:
            try:
                data, sender = self._sock.recvfrom(65535)
            except OSError:
                return
            asked = snmp.parse(data)
            self.requests.append(asked.pdu)
            if not self.answering or asked.community != self.community:
                continue
            oids = [b.oid for b in asked.bindings]
            if asked.pdu == snmp.GET:
                answer = [(o, self.objects.get(o, snmp.missing())) for o in oids]
            elif asked.pdu == snmp.GET_NEXT:
                answer = [self._next(o) for o in oids]
            else:  # GetBulk: no non-repeaters here, `error_index` rows after each OID
                answer = []
                for oid in oids:
                    for _ in range(asked.error_index):
                        oid, value = self._next(oid)
                        answer.append((oid, value))
                        if value == snmp.end_of_mib():
                            break
            reply = snmp.message(self.community, snmp.RESPONSE, asked.request_id, answer)
            self._sock.sendto(reply, sender)


@contextmanager
def running(objects: Objects, community: bytes = b"public") -> Iterator[Agent]:
    agent = Agent(objects, community)
    try:
        yield agent
    finally:
        agent.close()
