import ctypes
import time
from datetime import UTC, datetime

import pytest

from capypanel.core.remote import access, sessions
from capypanel.core.remote.access import Account, Reason, RemoteError


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
    assert access.reason_of(code) is reason


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
    with pytest.raises(RemoteError) as caught:
        sessions.read_sessions("192.0.2.1")  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE
    assert time.monotonic() - began < access.REACH_TIMEOUT + 2


class FakeWts:
    """The session API calls Log off, Disconnect and Send a message make, recorded."""

    def __init__(self, works: bool = True) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.works = works

    def _answer(self) -> bool:
        if not self.works:
            ctypes.set_last_error(5)  # access denied, as Windows would leave it
        return self.works

    def WTSOpenServerW(self, host: str) -> int:  # noqa: N802 (Windows' names)
        self.calls.append(("open", host))
        return 7

    def WTSCloseServer(self, server: int) -> None:  # noqa: N802
        self.calls.append(("close", server))

    def WTSLogoffSession(self, server: int, session: int, wait: bool) -> bool:  # noqa: N802
        self.calls.append(("logoff", server, session, wait))
        return self._answer()

    def WTSDisconnectSession(self, server: int, session: int, wait: bool) -> bool:  # noqa: N802
        self.calls.append(("disconnect", server, session, wait))
        return self._answer()

    def WTSSendMessageW(self, server: int, session: int, title: str, title_size: int,  # noqa: N802
                        text: str, text_size: int, *rest: object) -> bool:  # fmt: skip
        self.calls.append(("message", server, session, title, title_size, text, text_size))
        return self._answer()


@pytest.fixture
def fake_wts(monkeypatch: pytest.MonkeyPatch) -> FakeWts:
    fake = FakeWts()
    monkeypatch.setattr(sessions, "_wts", fake)
    monkeypatch.setattr(sessions, "check_reachable", lambda host: None)
    return fake


def test_log_off_disconnect_and_message_reach_the_picked_session(fake_wts: FakeWts) -> None:
    sessions.log_off("192.0.2.10", 2)
    sessions.disconnect("192.0.2.10", 3)
    sessions.send_message("192.0.2.10", 2, "IT", "Restarting in 5 minutes")
    assert fake_wts.calls == [
        ("open", "192.0.2.10"), ("logoff", 7, 2, False), ("close", 7),
        ("open", "192.0.2.10"), ("disconnect", 7, 3, False), ("close", 7),
        ("open", "192.0.2.10"), ("message", 7, 2, "IT", 4, "Restarting in 5 minutes", 46),
        ("close", 7),
    ]  # fmt: skip


def test_a_refused_action_says_why_and_still_closes_the_handle(fake_wts: FakeWts) -> None:
    fake_wts.works = False
    with pytest.raises(RemoteError) as caught:
        sessions.log_off("192.0.2.10", 2)
    assert caught.value.reason is Reason.REJECTED
    assert fake_wts.calls[-1] == ("close", 7)


def test_an_action_on_an_unreachable_host_fails_fast() -> None:
    with pytest.raises(RemoteError) as caught:
        sessions.log_off("192.0.2.1", 1)  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE


def test_sessions_on_this_pc_carry_their_windows_number() -> None:
    assert all(s.session_id >= 0 for s in sessions.read_sessions(None))
