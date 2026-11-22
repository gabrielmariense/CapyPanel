import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from capypanel.core.remote.batch import Batch
from capypanel.core.remote.status import PortState, port_state
from capypanel.ui.ssh_tool.status import Checked


@dataclass(frozen=True)
class Target:
    host_id: str
    address: str
    port: int


def check(target: Target) -> Checked:
    when = datetime.now()
    state, address = port_state(target.address, target.port)
    return Checked(when, state, address, target.port)


class SshRun(QObject):
    found = Signal(str, object)
    finished = Signal()

    def __init__(self, targets: Sequence[Target]) -> None:
        super().__init__()
        self.total = len(targets)
        self.done = 0
        self._batch = Batch(list(targets), check, self._report)

    def start(self) -> None:
        threading.Thread(target=self._run, name="ssh-refresh", daemon=True).start()

    def stop(self) -> None:
        self._batch.stop()

    @property
    def stopped(self) -> bool:
        return self._batch.stopped

    def _run(self) -> None:
        try:
            self._batch.run()
        finally:
            self.finished.emit()

    def _report(self, target: Target, found: Checked | None, error: Exception | None) -> None:
        if found is None:
            found = Checked(datetime.now(), PortState.NO_ANSWER, None, target.port)
        self.found.emit(target.host_id, found)
