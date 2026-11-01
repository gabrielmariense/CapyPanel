import pytest
import snmp_agent
from snmp_agent import running

from capypanel.core.printers import snmp, usm

SYS_DESCR = "1.3.6.1.2.1.1.1.0"
LEVELS = "1.3.6.1.2.1.43.11.1.1.9"


def test_get_reads_values_and_none_for_what_is_missing() -> None:
    with (
        running(
            {SYS_DESCR: b"SAMPLE printer", "1.3.6.1.2.1.1.3.0": snmp.counter(4_000_000_000)}
        ) as agent,
        snmp.Session("127.0.0.1", "public", port=agent.port) as session,
    ):
        found = session.get([SYS_DESCR, "1.3.6.1.2.1.1.3.0", "1.3.6.1.2.1.1.5.0"])
    assert found == {
        SYS_DESCR: b"SAMPLE printer",
        "1.3.6.1.2.1.1.3.0": 4_000_000_000,  # a counter is unsigned, past the INTEGER range
        "1.3.6.1.2.1.1.5.0": None,
    }


def test_walk_reads_a_whole_table_in_order_and_stops_at_its_end() -> None:
    # More rows than one GetBulk brings, then the next table, where the walk must stop.
    rows: dict[str, snmp.Value] = {f"{LEVELS}.1.{i}": i * 10 for i in range(1, 46)}
    rows["1.3.6.1.2.1.43.12.1.1.4.1.1"] = b"next table"
    with (
        running(rows) as agent,
        snmp.Session("127.0.0.1", "public", port=agent.port) as session,
    ):
        walked = session.walk(LEVELS)
    assert [value for _oid, value in walked] == [i * 10 for i in range(1, 46)]
    assert walked[1][0] == f"{LEVELS}.1.2"  # numeric order, not text order (2 before 10)
    assert set(agent.requests) == {snmp.GET_BULK}


def test_walk_of_the_last_table_stops_at_the_end_of_everything() -> None:
    with (
        running({f"{LEVELS}.1.1": 5}) as agent,
        snmp.Session("127.0.0.1", "public", port=agent.port) as session,
    ):
        assert session.walk(LEVELS) == [(f"{LEVELS}.1.1", 5)]


def test_a_wrong_community_gets_no_answer() -> None:
    with (
        running({SYS_DESCR: b"x"}, community=b"secret") as agent,
        snmp.Session("127.0.0.1", "public", port=agent.port, timeout=0.2) as session,
        pytest.raises(snmp.NoAnswer),
    ):
        session.get([SYS_DESCR])
    assert agent.requests == [snmp.GET, snmp.GET]  # asked, then asked once more


def test_an_unknown_name_is_no_answer() -> None:
    with pytest.raises(snmp.NoAnswer):
        snmp.Session("printer.invalid", "public")


def test_the_client_can_only_build_read_requests() -> None:
    with pytest.raises(ValueError, match="only reads"):
        snmp.message(b"public", 0xA3, 1, [(SYS_DESCR, b"x")])  # 0xA3 is SetRequest


def test_encoding_round_trips() -> None:
    bindings = [
        (SYS_DESCR, b"text"),
        ("1.3.6.1.2.1.43.11.1.1.8.1.1", -3),
        ("1.3.6.1", "1.3.6.1.4.1.11"),
    ]
    data = snmp.message(b"public", snmp.RESPONSE, 77, bindings)
    answer = snmp.parse(data)
    assert answer.request_id == 77 and answer.community == b"public"
    assert [(b.oid, b.value) for b in answer.bindings] == bindings


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x30",
        b"\x30\x05\x02\x01\x01",  # claims more than it has
        b"\x30\x84\xff\xff\xff\xff",  # a length past any real answer
        b"\x04\x00",  # not a sequence
        snmp.message(b"c", snmp.RESPONSE, 1, [(SYS_DESCR, b"x")])[:-3],  # cut short
        b"\x30\x0e\x02\x01\x00\x04\x01c\xa2\x06\x02\x01\x01\x02\x01\x00",  # SNMP v1, no bindings
        # A counter far longer than any real one (it would be a number too big to show).
        snmp.message(b"c", snmp.RESPONSE, 1, [(SYS_DESCR, (0x41, b"\x01" * 40))]),
    ],
)
def test_malformed_answers_raise_snmp_error(data: bytes) -> None:
    with pytest.raises(snmp.SnmpError):
        snmp.parse(data)


def test_a_session_stops_asking_after_its_time_limit() -> None:
    with (
        running({SYS_DESCR: b"x"}) as agent,
        snmp.Session("127.0.0.1", "public", port=agent.port, limit=0.0) as session,
        pytest.raises(snmp.SnmpError, match="too slowly"),
    ):
        session.get([SYS_DESCR])
    assert agent.requests == []  # nothing sent once the time is up


# ---- SNMP v3 ----

SIGNED = usm.Account("sample", usm.Auth.SHA256, "auth-pass-1")
PRIVATE = usm.Account("sample", usm.Auth.SHA, "auth-pass-1", usm.Privacy.AES128, "priv-pass-1")


@pytest.mark.parametrize("account", [usm.Account("sample"), SIGNED, PRIVATE])
def test_v3_reads_at_every_security_level(account: usm.Account) -> None:
    rows: dict[str, snmp.Value] = {f"{LEVELS}.1.{i}": i for i in range(1, 30)}
    with (
        running({SYS_DESCR: b"SAMPLE printer", **rows}, account=account) as agent,
        snmp.Session("127.0.0.1", account, port=agent.port) as session,
    ):
        assert session.get([SYS_DESCR]) == {SYS_DESCR: b"SAMPLE printer"}
        assert [v for _o, v in session.walk(LEVELS)] == list(range(1, 30))
    # The engine is found once, then every request is answered.
    assert agent.requests[:2] == [snmp.GET, snmp.REPORT]
    assert snmp.REPORT not in agent.requests[2:]


def test_v3_sets_its_clock_from_the_printer_when_the_first_report_has_none() -> None:
    with (
        running({SYS_DESCR: b"x"}, account=PRIVATE, tells_time=False) as agent,
        snmp.Session("127.0.0.1", PRIVATE, port=agent.port) as session,
    ):
        assert session.get([SYS_DESCR]) == {SYS_DESCR: b"x"}
    assert agent.requests == [snmp.GET, snmp.REPORT, snmp.REPORT, snmp.GET]


@pytest.mark.parametrize(
    ("asked", "reason"),
    [
        (usm.Account("someone", usm.Auth.SHA, "auth-pass-1", usm.Privacy.AES128, "priv-pass-1"),
         snmp.USER),
        (usm.Account("sample", usm.Auth.SHA, "wrong-pass", usm.Privacy.AES128, "priv-pass-1"),
         snmp.AUTH),
        (usm.Account("sample", usm.Auth.SHA, "auth-pass-1", usm.Privacy.AES128, "wrong-pass"),
         snmp.PRIVACY),
        (usm.Account("sample", usm.Auth.SHA, "auth-pass-1"), snmp.LEVEL),
    ],
)  # fmt: skip
def test_v3_says_why_the_printer_refused(asked: usm.Account, reason: str) -> None:
    with (
        running({SYS_DESCR: b"x"}, account=PRIVATE) as agent,
        snmp.Session("127.0.0.1", asked, port=agent.port) as session,
        pytest.raises(snmp.Refused) as refused,
    ):
        session.get([SYS_DESCR])
    assert refused.value.reason == reason
    assert "pass" not in str(refused.value)


def test_v3_ignores_answers_whose_signature_does_not_match() -> None:
    # The agent signs with another password's key, as a forged answer would: nothing is read.
    forger = usm.Account("sample", usm.Auth.SHA256, "other-pass-1")
    with running({SYS_DESCR: b"x"}, account=SIGNED) as agent:
        agent._keys = usm.keys(forger, snmp_agent.ENGINE_ID)
        with (
            snmp.Session("127.0.0.1", SIGNED, port=agent.port, timeout=0.2) as session,
            pytest.raises(snmp.SnmpError),
        ):
            session.get([SYS_DESCR])


def test_v3_messages_are_encrypted_on_the_wire() -> None:
    keys = usm.keys(PRIVATE, snmp_agent.ENGINE_ID)
    packet = snmp.message_v3(
        snmp.GET, 1, [(SYS_DESCR, None)], message_id=1, user=b"sample",
        engine_id=snmp_agent.ENGINE_ID, boots=1, engine_time=1, keys=keys, privacy=True,
    )  # fmt: skip
    header = snmp.parse_v3(packet)
    assert b"\x06\x08\x2b\x06\x01\x02\x01\x01\x01\x00" not in packet  # the OID isn't readable
    assert usm.verified(keys, packet, header.auth_at)
    assert snmp.open_v3(header, keys).bindings[0].oid == SYS_DESCR
