"""What CapyPanel learned about a host this session, beside Refresh's results: its PC facts and a
restart or shutdown that's waiting. Kept in memory only, like Refresh's, since the list file is
shared."""

from dataclasses import dataclass
from datetime import datetime

from capypanel.core.remote.inventory import DiskSpace, PcFacts


@dataclass(frozen=True)
class Facts:
    """PC facts as far as they've been read: the quick part (free space, last restart) comes in
    first, the rest over WMI a few seconds later. An error stands in for a part that failed."""

    when: datetime
    reading: bool = True
    space: DiskSpace | None = None
    restarted: datetime | None = None
    quick_error: BaseException | None = None
    pc: PcFacts | None = None
    pc_error: BaseException | None = None


@dataclass(frozen=True)
class PendingPower:
    """A restart or shutdown CapyPanel asked for, still waiting (`at` is in the future), or on
    its way and watched until the PC answers again."""

    restart: bool
    at: datetime  # when Windows does it
    asked: datetime
    told: tuple[str, ...] = ()  # who was shown the message
    went_down: bool = False  # the PC stopped answering since: it's restarting
    name: str = ""  # the host's name when asked, for the notification
    address: str = ""
