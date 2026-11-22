from dataclasses import dataclass
from datetime import datetime

from capypanel.core.remote.inventory import DiskSpace, PcFacts


@dataclass(frozen=True)
class Facts:
    when: datetime
    reading: bool = True
    space: DiskSpace | None = None
    restarted: datetime | None = None
    quick_error: BaseException | None = None
    pc: PcFacts | None = None
    pc_error: BaseException | None = None


@dataclass(frozen=True)
class PendingPower:
    restart: bool
    at: datetime
    asked: datetime
    told: tuple[str, ...] = ()
    went_down: bool = False
    name: str = ""
    address: str = ""
