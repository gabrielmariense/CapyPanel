"""Refresh on printers: one SNMP read each, a few at a time on a background thread, and when
some printers' page counters come from Doc360 MPS, one Doc360 download beside them. `found`
arrives once per printer and `counted` once per Refresh, on the UI thread through Qt's queued
signals."""

import json
import logging
import threading
from collections.abc import Sequence
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from capypanel.core import credstore
from capypanel.core.i18n import _
from capypanel.core.printers import doc360, reading, snmp, usm
from capypanel.core.remote.batch import Batch
from capypanel.ui.printers_tool.status import NO_ACCOUNT, REFUSED, Checked, Counted

log = logging.getLogger(__name__)
COMMUNITY = "printers/snmp-community"  # its name in Windows Credential Manager
V3_ACCOUNT = "printers/snmp-v3"  # the v3 user, its protocols and passwords, in one entry
DOC360_ACCOUNT = "printers/doc360"  # the Doc360 MPS login: the user, then partner and password
DEFAULT_COMMUNITY = "public"  # what most printers answer to, until one is set
V2C, V3 = "v2c", "v3"  # Settings' SNMP version


def community() -> str:
    """The community string set in Settings, or "public"."""
    try:
        return credstore.load(COMMUNITY) or DEFAULT_COMMUNITY
    except OSError as e:
        log.warning("Couldn't read the SNMP community string: %s", e)
        return DEFAULT_COMMUNITY


def v3_account() -> usm.Account | None:
    """The SNMP v3 account set in Settings, or None when there's none (or it can't be read)."""
    try:
        found = credstore.read(V3_ACCOUNT)
        if found is None:
            return None
        user, kept = found
        fields = json.loads(kept)
        auth = _by_label(usm.Auth, fields.get("auth"))
        privacy = _by_label(usm.Privacy, fields.get("privacy"))
        return usm.Account(
            user,
            auth,
            str(fields.get("auth_password", "")) if auth else "",
            privacy,
            str(fields.get("privacy_password", "")) if privacy else "",
        )
    except (OSError, ValueError, AttributeError) as e:  # not a word of the secrets in the log
        log.warning("Couldn't read the SNMP v3 account: %s", type(e).__name__)
        return None


def save_v3_account(account: usm.Account) -> None:
    """Keeps the account in Windows Credential Manager. Raises OSError or ValueError."""
    fields = {
        "auth": account.auth.label if account.auth else None,
        "auth_password": account.auth_password,
        "privacy": account.privacy.value if account.privacy else None,
        "privacy_password": account.privacy_password,
    }
    credstore.save(V3_ACCOUNT, json.dumps(fields), user=account.user)


def doc360_account() -> doc360.Account | None:
    """The Doc360 MPS login set in Settings, or None when there's none (or it can't be read)."""
    try:
        found = credstore.read(DOC360_ACCOUNT)
        if found is None:
            return None
        user, kept = found
        fields = json.loads(kept)
        return doc360.Account(str(fields["partner"]), user, str(fields["password"]))
    except (OSError, ValueError, KeyError, TypeError) as e:  # not a word of the secret in the log
        log.warning("Couldn't read the Doc360 MPS account: %s", type(e).__name__)
        return None


def save_doc360_account(account: doc360.Account) -> None:
    """Keeps the login in Windows Credential Manager. Raises OSError or ValueError."""
    fields = {"partner": account.partner, "password": account.password}
    credstore.save(DOC360_ACCOUNT, json.dumps(fields), user=account.user)


def _by_label[E: (usm.Auth, usm.Privacy)](kind: type[E], label: object) -> E | None:
    for member in kind:
        if label in (getattr(member, "label", None), member.value):
            return member
    return None


def check(address: str, secret: snmp.Secret) -> Checked:
    """One printer's reading, or why there's none. Never raises."""
    when = datetime.now()
    try:
        return Checked(when, reading.read(reading.snmp_host(address), secret))
    except snmp.NoAnswer:
        return Checked(when, offline=True)
    except snmp.Refused as e:
        return Checked(when, refused=e.reason)
    except snmp.SnmpError as e:
        log.info("Unreadable SNMP answer from a printer: %s", e)
        return Checked(when, error=str(e))


def count(account: doc360.Account | None) -> Counted:
    """Every printer's latest counters from Doc360 MPS, or why there are none. Never raises."""
    when = datetime.now()
    if account is None:
        return Counted(when, error=_("No Doc360 MPS account is set."), account=NO_ACCOUNT)
    try:
        return Counted(when, doc360.read_counters(account))
    except doc360.Refused:
        log.info("Doc360 MPS: the login was refused")
        return Counted(when, error=_("Doc360 MPS refused the login."), account=REFUSED)
    except doc360.Doc360Error as e:
        log.info("Doc360 MPS: %s", e)  # its own few words: never a page, a login or a serial
        return Counted(when, error=_doc360_error(e))
    except Exception as e:  # a bug here mustn't stop the printers' Refresh
        log.exception("Reading Doc360 MPS failed")
        return Counted(when, error=type(e).__name__)


def _doc360_error(error: doc360.Doc360Error) -> str:
    if isinstance(error, doc360.NoAnswer):
        return _("Doc360 MPS didn't answer.")
    if isinstance(error, doc360.Changed):
        return _("Doc360 MPS's pages changed, so CapyPanel couldn't read the counters.")
    return _("Doc360 MPS answered with an error.")


class PrinterRun(QObject):
    """One Refresh over some printers: (printer id, address) each, plus Doc360 MPS's counters
    when `counts` is set."""

    found = Signal(str, object)  # printer id, Checked
    counted = Signal(object)  # Counted
    finished = Signal()

    def __init__(
        self,
        targets: Sequence[tuple[str, str]],
        secret: snmp.Secret,
        *,
        counts: bool = False,
        account: doc360.Account | None = None,
    ) -> None:
        super().__init__()
        self.total = len(targets)
        self.done = 0
        self.counts, self._account = counts, account
        self._batch = Batch(list(targets), lambda t: check(t[1], secret), self._report)

    def start(self) -> None:
        threading.Thread(target=self._run, name="printers-refresh", daemon=True).start()

    def stop(self) -> None:
        self._batch.stop()

    @property
    def stopped(self) -> bool:
        return self._batch.stopped

    def _run(self) -> None:
        doc360_job = None
        if self.counts:  # one download, beside the printers: Stop lets it finish
            doc360_job = threading.Thread(
                target=lambda: self.counted.emit(count(self._account)),
                name="printers-doc360",
                daemon=True,
            )
            doc360_job.start()
        try:
            self._batch.run()
        finally:
            if doc360_job is not None:
                doc360_job.join()
            self.finished.emit()

    def _report(
        self, target: tuple[str, str], found: Checked | None, error: Exception | None
    ) -> None:
        if found is None:  # a bug in the reading: show the printer as unreadable, keep going
            found = Checked(datetime.now(), error=str(error or ""))
        self.found.emit(target[0], found)
