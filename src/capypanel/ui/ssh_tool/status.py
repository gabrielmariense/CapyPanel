"""What an SSH host's last port check says in words and colours, in its cell and Details."""

from dataclasses import dataclass
from datetime import datetime

from capypanel.core.i18n import _
from capypanel.core.remote.status import PortState
from capypanel.core.ssh.host import DEFAULT_PORT
from capypanel.ui.checks import when_text


@dataclass(frozen=True)
class Checked:
    """One host's last check of its SSH port."""

    when: datetime
    state: PortState
    address: str | None = None  # the address that answered: open or refused
    port: int = DEFAULT_PORT


@dataclass(frozen=True)
class Cell:
    """The Status cell: its words, tooltip and dot (a status colour's name, "" for none)."""

    text: str
    tip: str
    color: str
    quiet: bool = False  # greyed: anything but Online
    nothing: bool = False  # "Not checked": sorts last


_COLORS = {
    PortState.OPEN: "online",
    PortState.CLOSED: "attention",  # it answered, but ssh.exe would fail
    PortState.NO_ANSWER: "offline",
    PortState.NOT_FOUND: "not-found",
}


def state_text(state: PortState) -> str:
    return {
        PortState.OPEN: _("Online"),
        PortState.CLOSED: _("Port closed"),
        PortState.NO_ANSWER: _("Offline"),
        PortState.NOT_FOUND: _("Host not found"),
    }[state]


def state_tip(checked: Checked) -> str:
    when = _("Checked {when}.").format(when=when_text(checked.when))
    address, port = checked.address or "", checked.port
    why = {
        PortState.OPEN: _("Answered at {address}, port {port}."),
        PortState.CLOSED: _(
            "Answered at {address}, but port {port} is closed: ssh.exe would fail with "
            "“Connection refused”."
        ),
        PortState.NO_ANSWER: _("Didn't answer the Refresh."),
        PortState.NOT_FOUND: _("No computer by that name or address was found on the network."),
    }[checked.state]
    return f"{when}\n{why.format(address=address, port=port)}"


def not_checked() -> Cell:
    return Cell(_("Not checked"), _("Not checked: use Refresh"), "", quiet=True, nothing=True)


def cell(checked: Checked | None) -> Cell:
    if checked is None:
        return not_checked()
    state = checked.state
    return Cell(
        state_text(state), state_tip(checked), _COLORS[state], quiet=state is not PortState.OPEN
    )


def status_words() -> tuple[str, ...]:
    """Every word the Status column can show, so its first width cuts none of them."""
    return (*(state_text(state) for state in PortState), _("Not checked"))
