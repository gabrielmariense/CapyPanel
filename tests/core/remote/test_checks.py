import pytest

from capypanel.core.remote import checks, sessions, status
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import Status

DESK = Session("ana", "CORP", "console", "active", None)
UP = Status.ONLINE


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(
        status, "probe", lambda host, _p: seen.append(f"status {host}") or (UP, ("10.0.0.9", 445))
    )
    monkeypatch.setattr(
        sessions, "read_sessions", lambda host, _a=None: seen.append(f"users {host}") or [DESK]
    )
    return seen


def test_both_checks(calls: list[str]) -> None:
    found = checks.run("pc1", Checks())
    assert found.status is Status.ONLINE and found.sessions == (DESK,)
    assert found.answered == ("10.0.0.9", 445)
    assert calls == ["status pc1", "users pc1"]


def test_an_offline_pc_isnt_asked_for_users(
    calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status, "probe", lambda _h, _p: (Status.OFFLINE, None))
    found = checks.run("pc1", Checks())
    assert found.status is Status.OFFLINE and found.sessions is None
    assert found.users_error is not None and found.users_error.reason is Reason.UNREACHABLE
    assert calls == []


def test_reading_users_alone_also_shows_the_pc_is_up(calls: list[str]) -> None:
    found = checks.run("pc1", Checks(status=False))
    assert found.status is Status.ONLINE and calls == ["users pc1"]


def test_a_failed_users_read_alone_leaves_the_status_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_host: str, _account: Account | None = None) -> list[Session]:
        raise SessionsError(Reason.UNREACHABLE)

    monkeypatch.setattr(sessions, "read_sessions", refuse)
    found = checks.run("pc1", Checks(status=False))
    assert found.status is None and found.users_error is not None


def test_which_outcomes_prove_or_reject_an_account() -> None:
    def failed(reason: Reason) -> Found:
        return Found(users_error=SessionsError(reason))

    assert checks.account_proven(Found(sessions=()), None)
    assert checks.account_proven(failed(Reason.NOT_ADMIN), None)  # accepted, just not admin
    assert not checks.account_proven(failed(Reason.UNREACHABLE), None)
    assert checks.account_rejected(failed(Reason.REJECTED))
    assert not checks.account_rejected(failed(Reason.NOT_ADMIN))


def test_the_tools_ports_join_the_usual_ones() -> None:
    assert checks.tool_ports([5900, None, 3389, 5900]) == (22, 445, 3389, 5900)
