"""Refresh on printers: one SNMP read each, a few at a time on a background thread. `found`
arrives once per printer, on the UI thread through Qt's queued signal."""

import logging
import threading
from collections.abc import Sequence
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from capypanel.core import credstore
from capypanel.core.printers import reading, snmp
from capypanel.core.remote.batch import Batch
from capypanel.ui.printers_tool.status import Checked

log = logging.getLogger(__name__)
COMMUNITY = "printers/snmp-community"  # its name in Windows Credential Manager
DEFAULT_COMMUNITY = "public"  # what most printers answer to, until one is set


def community() -> str:
    """The community string set in Settings, or "public"."""
    try:
        return credstore.load(COMMUNITY) or DEFAULT_COMMUNITY
    except OSError as e:
        log.warning("Couldn't read the SNMP community string: %s", e)
        return DEFAULT_COMMUNITY


def check(address: str, secret: str) -> Checked:
    """One printer's reading, or why there's none. Never raises."""
    when = datetime.now()
    try:
        return Checked(when, reading.read(reading.snmp_host(address), secret))
    except snmp.NoAnswer:
        return Checked(when, offline=True)
    except snmp.SnmpError as e:
        log.info("Unreadable SNMP answer from a printer: %s", e)
        return Checked(when, error=str(e))


class PrinterRun(QObject):
    """One Refresh over some printers: (printer id, address) each."""

    found = Signal(str, object)  # printer id, Checked
    finished = Signal()

    def __init__(self, targets: Sequence[tuple[str, str]], secret: str) -> None:
        super().__init__()
        self.total = len(targets)
        self.done = 0
        self._batch = Batch(list(targets), lambda t: check(t[1], secret), self._report)

    def start(self) -> None:
        threading.Thread(target=self._run, name="printers-refresh", daemon=True).start()

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

    def _report(
        self, target: tuple[str, str], found: Checked | None, error: Exception | None
    ) -> None:
        if found is None:  # a bug in the reading: show the printer as unreadable, keep going
            found = Checked(datetime.now(), error=str(error or ""))
        self.found.emit(target[0], found)
