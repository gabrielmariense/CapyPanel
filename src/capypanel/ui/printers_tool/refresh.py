"""Refresh on printers: one SNMP read each, a few at a time on a background thread. `found`
arrives once per printer, on the UI thread through Qt's queued signal."""

import json
import logging
import threading
from collections.abc import Sequence
from datetime import datetime
from functools import partial

from PySide6.QtCore import QObject, Signal

from capypanel.core import credstore
from capypanel.core.i18n import _
from capypanel.core.printers import reading, snmp, usm
from capypanel.core.remote.batch import Batch
from capypanel.ui.printers_tool.status import Checked
from capypanel.ui.saved_credentials import KeptLogin

log = logging.getLogger(__name__)
COMMUNITY = "printers/snmp-community"  # its name in Windows Credential Manager
V3_ACCOUNT = "printers/snmp-v3"  # the v3 user, its protocols and passwords, in one entry
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


def kept_logins() -> list[KeptLogin]:
    """The v3 account and the community string, when set, for Saved credentials."""
    try:
        account, secret = credstore.read(V3_ACCOUNT), credstore.read(COMMUNITY)
    except OSError as e:
        log.warning("Couldn't read the SNMP accounts: %s", e)
        return []
    tool, logins = _("Printers › Refresh"), []
    if account is not None:
        forget = partial(credstore.forget, V3_ACCOUNT)
        logins.append(KeptLogin(_("SNMP account (v3)"), tool, account[0], True, forget))
    if secret is not None:
        forget = partial(credstore.forget, COMMUNITY)
        logins.append(KeptLogin(_("SNMP community string (v2c)"), tool, "—", True, forget))
    return logins


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


class PrinterRun(QObject):
    """One Refresh over some printers: (printer id, address) each."""

    found = Signal(str, object)  # printer id, Checked
    finished = Signal()

    def __init__(self, targets: Sequence[tuple[str, str]], secret: snmp.Secret) -> None:
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
