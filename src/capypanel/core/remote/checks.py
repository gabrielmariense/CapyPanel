"""The checks Refresh runs on one host: whether it's up, and who is logged on."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from capypanel.core.remote import sessions, status
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import BASE_PORTS, Answer, Status


@dataclass(frozen=True)
class Checks:
    status: bool = True
    users: bool = True
    ports: tuple[int, ...] = BASE_PORTS  # the field "status" hides the module here
    account: Account | None = None  # None: the Windows login


@dataclass(frozen=True)
class Found:
    """What one run learned about a host. None means "not checked this time"."""

    status: Status | None = None
    sessions: tuple[Session, ...] | None = None
    users_error: SessionsError | None = None
    answered: Answer | None = None  # the address (and port) that proved the status
    when: datetime = field(default_factory=lambda: datetime.now(UTC))


def run(address: str, checks: Checks) -> Found:
    state, answered = status.probe(address, checks.ports) if checks.status else (None, None)
    if not checks.users:
        return Found(state, answered=answered)
    if state is not None and state is not Status.ONLINE:
        # Nothing answered: reading users would only wait for the same silence.
        return Found(state, users_error=SessionsError(Reason.UNREACHABLE))
    try:
        found = tuple(sessions.read_sessions(address, checks.account))
    except SessionsError as e:
        return Found(state, users_error=e, answered=answered)
    return Found(Status.ONLINE, found, answered=answered)  # it answered, so it's up


def account_rejected(found: Found | None, _error: Exception | None = None) -> bool:
    """A host refused the account: with a typed one, stop, so it isn't tried on every host."""
    error = found.users_error if found is not None else None
    return error is not None and error.reason is Reason.REJECTED


def account_proven(found: Found | None, error: Exception | None) -> bool:
    """A host that read the users, or said "not an admin", accepted the account."""
    if found is None:
        return False
    if found.sessions is not None:
        return True
    return found.users_error is not None and found.users_error.reason is Reason.NOT_ADMIN


def tool_ports(ports: Iterable[int | None]) -> tuple[int, ...]:
    return tuple(sorted({*status.BASE_PORTS, *(p for p in ports if p)}))
