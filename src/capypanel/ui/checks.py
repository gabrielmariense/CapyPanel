"""Refresh: running the status and logged-on-users checks in the background, the account
prompt, and how their results read in the table and the details pane."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, datetime

from PySide6.QtCore import QDate, QDateTime, QLocale, QObject, QTimeZone, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.hosts.accounts import Link
from capypanel.core.i18n import _
from capypanel.core.remote import checks
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.batch import Batch
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Answer, Status
from capypanel.ui.notes import hint

MAX_TEXT = 256


class CheckRun(QObject):
    """One Refresh over some hosts, on a background thread. `found` arrives once per host.
    `accounts` gives each host's account (by host id); hosts sharing one go together."""

    found = Signal(str, object)  # host id, Found
    finished = Signal()

    def __init__(
        self,
        targets: Sequence[tuple[str, str]],
        wanted: Checks,
        accounts: Callable[[str], Account | None] | None = None,
    ) -> None:
        super().__init__()
        self.wanted = wanted
        self.total = len(targets)
        self.done = 0
        self._accounts = accounts if accounts and wanted.users else lambda _key: wanted.account
        parts: dict[str, tuple[Account | None, list[tuple[str, str]]]] = {}
        for target in targets:
            account = self.account_of(target[0])
            key = account.user.casefold() if account else ""
            parts.setdefault(key, (account, []))[1].append(target)
        self._batches = [self._batch(found, account, wanted) for account, found in parts.values()]
        self._stop = threading.Event()
        self.rejected: list[Account] = []  # typed accounts a host rejected: not tried further

    def account_of(self, key: str) -> Account | None:
        """The account a host's users are read with; None: the Windows account."""
        return self._accounts(key)

    def _batch(
        self, targets: list[tuple[str, str]], account: Account | None, wanted: Checks
    ) -> tuple[Account | None, Batch[tuple[str, str], Found]]:
        wanted = replace(wanted, account=account)
        typed = wanted.users and account is not None
        return account, Batch(
            targets,
            lambda target: checks.run(target[1], wanted),
            self._report,
            # A typed password goes host by host until one accepts it, and stops at a rejection.
            halts=checks.account_rejected if typed else lambda _r, _e: False,
            proves=checks.account_proven if typed else None,
        )

    def start(self) -> None:
        threading.Thread(target=self._run, name="refresh", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        for _account, batch in self._batches:
            batch.stop()

    @property
    def stopped(self) -> bool:
        """By Stop, or by a rejected account."""
        return self._stop.is_set() or any(batch.stopped for _a, batch in self._batches)

    @property
    def halted(self) -> bool:
        """A host rejected a typed account, so the hosts left for it weren't tried."""
        return bool(self.rejected)

    def _run(self) -> None:
        try:
            for account, batch in self._batches:
                if self._stop.is_set():
                    break
                batch.run()
                if batch.halted and account is not None:
                    self.rejected.append(account)
        finally:
            self.finished.emit()

    def _report(
        self, target: tuple[str, str], found: Found | None, error: Exception | None
    ) -> None:
        if found is None:  # a bug in a check: show it as unreadable rather than lose the host
            found = Found(users_error=RemoteError(Reason.OTHER)) if error else Found()
        self.found.emit(target[0], found)


class AccountDialog(QDialog):
    """Another account for other PCs, when the Windows login can't: which PCs it's for (`uses`,
    most specific first, each a link with no user yet) and whether Windows remembers it."""

    def __init__(
        self,
        parent: QWidget | None,
        reason: str,
        user: str = "",
        *,
        saved: bool = False,
        uses: Sequence[tuple[str, Link]] = (),
        fixed_user: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Account for other PCs"))
        intro = QLabel(reason)
        intro.setWordWrap(True)
        self.user = QLineEdit(user)
        self.user.setMaxLength(MAX_TEXT)
        self.user.setPlaceholderText(_("DOMAIN\\user"))
        self.user.setReadOnly(fixed_user)  # its password only: the account is set in Settings
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(MAX_TEXT)
        self.use_for = QComboBox()
        for label, link in uses:
            self.use_for.addItem(label, link)
        self.remember = QCheckBox(_("&Remember it on this computer"))
        self.remember.setChecked(saved)
        self.remember.setToolTip(
            _("Windows keeps it in Credential Manager for your Windows account. Otherwise "
              "CapyPanel forgets it when it closes and asks once the next time.")
        )  # fmt: skip
        form = QFormLayout()
        form.addRow(_("&User:"), self.user)
        form.addRow(_("&Password:"), self.password)
        if uses:
            form.addRow(_("Use it &for:"), self.use_for)
        form.addRow("", self.remember)
        used = _("Used only to read who is logged on and for the commands you run on a host.")
        stops = _(
            "If a computer rejects it, CapyPanel stops and asks again instead of trying it on "
            "the others, so the account isn't locked."
        )
        note = hint(f"{used} {stops}")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.user.textChanged.connect(self._update_ok)
        self.password.textChanged.connect(self._update_ok)
        self._update_ok()
        (self.password if user else self.user).setFocus()
        self.resize(460, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.user.text().strip()) and bool(self.password.text()))

    def account(self) -> Account:
        return Account(self.user.text().strip(), self.password.text())

    def link(self) -> Link | None:
        """The PCs picked in Use it for, as a link to this account; None when not asked."""
        picked = self.use_for.currentData()
        return replace(picked, user=self.account().user) if isinstance(picked, Link) else None


# ---- how results read ----


def when_text(when: datetime) -> str:
    moment = QDateTime.fromSecsSinceEpoch(int(when.timestamp()), QTimeZone.systemTimeZone())
    return QLocale(i18n.language()).toString(moment, QLocale.FormatType.ShortFormat)


def date_text(day: date) -> str:
    """A day with its month's short name: "Aug 20, 2026", "20 ago 2026"."""
    language = i18n.language()
    pattern = "MMM d, yyyy" if language.startswith("en") else "d MMM yyyy"
    return QLocale(language).toString(QDate(day.year, day.month, day.day), pattern)


def local(when: datetime) -> datetime:
    """`when` in this PC's time zone. Windows can't convert a time before 1970 (or past 3000),
    and dates read from other PCs can be anything: those stay as they are."""
    try:
        return when.astimezone()
    except (OSError, OverflowError, ValueError):
        return when


def clock_text(when: datetime) -> str:
    """Just the time for today ("10:41"); the date too for an older result."""
    moment = QDateTime.fromSecsSinceEpoch(int(when.timestamp()), QTimeZone.systemTimeZone())
    if moment.date() == QDateTime.currentDateTime().date():
        return QLocale(i18n.language()).toString(moment.time(), QLocale.FormatType.ShortFormat)
    return when_text(when)


def status_text(status: Status) -> str:
    return {
        Status.ONLINE: _("Online"),
        Status.OFFLINE: _("Offline"),
        Status.NOT_FOUND: _("Host not found"),
    }[status]


def status_tip(status: Status, when: datetime, answered: Answer | None = None) -> str:
    checked = _("Checked {when}.").format(when=when_text(when))
    if answered is not None:  # e.g. only the Wi-Fi address answers: the cable is out
        address, port = answered
        how = (
            _("Answered a ping at {address}.")
            if port is None
            else _("Answered at {address}, port {port}.")
        )
        checked += "\n" + how.format(address=address, port=port)
    why = {
        Status.ONLINE: "",
        Status.OFFLINE: _(
            "Nothing answered, neither ping nor the usual ports: the computer is off, not on "
            "the network, or a firewall blocks everything."
        ),
        Status.NOT_FOUND: _("No computer by that name or address was found on the network."),
    }[status]
    return f"{checked} {why}".strip()


_show_domains = True  # View > Users > Show domain


def show_domains(shown: bool) -> None:
    global _show_domains
    _show_domains = shown


def user_name(session: Session, *, full: bool = False) -> str:
    """How a logged-on user reads everywhere: "DOMAIN\\name", or "name" with domains off.
    full: always with the domain, for tooltips (a local "admin" isn't the domain's)."""
    if session.domain and (_show_domains or full):
        return f"{session.domain}\\{session.user}"
    return session.user


def by_state(sessions: Sequence[Session]) -> list[Session]:
    """Active sessions first: who is really at the computer, then disconnected ones."""
    return sorted(sessions, key=lambda s: s.state != "active")


def users_text(
    sessions: Sequence[Session] | None, error: RemoteError | None, *, full: bool = False
) -> str:
    if error is not None:
        return {
            Reason.UNREACHABLE: _("Unreachable"),
            Reason.NOT_ADMIN: _("No admin rights"),
            Reason.REJECTED: _("Account rejected"),
            Reason.OTHER: _("Couldn't read"),
        }[error.reason]
    if not sessions:
        return _("No one")
    names = []
    for session in by_state(sessions):
        name = user_name(session, full=full)
        if session.state == "disconnected":
            name = _("{user} (disconnected)").format(user=name)
        if name not in names:
            names.append(name)
    return ", ".join(names)


def users_tip(error: RemoteError | None, when: datetime) -> str:
    checked = _("Checked {when}.").format(when=when_text(when))
    if error is None:
        return checked
    why = {
        Reason.UNREACHABLE: _(
            "Windows file sharing (port 445) didn't answer: the computer is off, not on the "
            "network, a firewall blocks file sharing, or it isn't Windows."
        ),
        Reason.NOT_ADMIN: _(
            "The account was accepted, but only administrators of that computer can see who "
            "is logged on."
        ),
        Reason.REJECTED: _(
            "The computer didn't accept the account: a wrong password, a locked account, or "
            "an account it doesn't trust."
        ),
        Reason.OTHER: _("Windows error {code}.").format(code=error.code),
    }[error.reason]
    return f"{checked} {why}"


def session_lines(sessions: Sequence[Session], *, full: bool = False) -> str:
    """One line per session, active ones first, for the details pane."""
    kinds = {"console": _("at the computer"), "rdp": _("Remote Desktop")}
    states = {"active": _("active"), "disconnected": _("disconnected"), "idle": _("idle")}
    lines = []
    for session in by_state(sessions):
        parts = [kinds.get(session.kind, ""), states.get(session.state, session.state)]
        if session.logon_time is not None:
            parts.append(_("since {when}").format(when=when_text(session.logon_time)))
        if session.client:
            parts.append(_("from {computer}").format(computer=session.client))
        details = ", ".join(p for p in parts if p)
        lines.append(f"{user_name(session, full=full)} — {details}")
    return "\n".join(lines)
