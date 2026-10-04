import time
from datetime import UTC, datetime

import pytest

from capypanel.core.remote import sessions
from capypanel.core.remote.sessions import Account, Reason, SessionsError


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (259, Reason.NOT_ADMIN),  # seen on real hosts for a non-admin account
        (5, Reason.REJECTED),  # seen for an account the host didn't accept
        (1326, Reason.REJECTED),  # wrong password
        (1722, Reason.UNREACHABLE),  # RPC server unavailable: the PC is off
        (53, Reason.UNREACHABLE),
        (87, Reason.OTHER),
    ],
)
def test_windows_errors_get_a_reason_the_user_can_act_on(code: int, reason: Reason) -> None:
    assert sessions.reason_of(code) is reason


def test_session_kinds_and_logon_times() -> None:
    assert sessions.session_kind("Console") == "console"
    assert sessions.session_kind("RDP-Tcp#3") == "rdp"
    assert sessions.session_kind("") == "unknown"  # a disconnected session's type is gone
    assert sessions.filetime(0) is None
    # 2026-10-04 12:00 UTC as a FILETIME: 100 ns steps since 1601.
    ft = int((datetime(2026, 10, 4, 12, tzinfo=UTC) - datetime(1601, 1, 1, tzinfo=UTC))
             .total_seconds() * 10_000_000)  # fmt: skip
    assert sessions.filetime(ft) == datetime(2026, 10, 4, 12, tzinfo=UTC)


def test_this_pc_can_be_read_with_the_real_api() -> None:
    found = sessions.read_sessions(None)  # this PC: checks the structures match Windows
    assert all(isinstance(s, sessions.Session) and s.user for s in found)


def test_another_account_only_changes_the_network_identity() -> None:
    # Windows doesn't check a "new credentials" password locally: reading this PC still works.
    found = sessions.read_sessions(None, Account("EXAMPLE\\nobody", "not-a-real-password"))
    assert isinstance(found, list)


def test_an_unreachable_host_fails_fast() -> None:
    began = time.monotonic()
    with pytest.raises(SessionsError) as caught:
        sessions.read_sessions("192.0.2.1")  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE
    assert time.monotonic() - began < sessions.REACH_TIMEOUT + 2
