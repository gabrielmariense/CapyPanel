"""Refresh: running the status and logged-on-users checks in the background, the account
prompt, and how their results read in the table and the details pane."""

import threading
from collections.abc import Sequence
from datetime import datetime

from PySide6.QtCore import QDateTime, QLocale, QObject, QTimeZone, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n
from capypanel.core.i18n import _
from capypanel.core.remote import checks
from capypanel.core.remote.batch import Batch
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Account, Reason, Session, SessionsError
from capypanel.core.remote.status import Answer, Status

MAX_TEXT = 256


class CheckRun(QObject):
    """One Refresh over some hosts, on a background thread. `found` arrives once per host."""

    found = Signal(str, object)  # host id, Found
    finished = Signal()

    def __init__(self, targets: Sequence[tuple[str, str]], wanted: Checks) -> None:
        super().__init__()
        self.wanted = wanted
        self.total = len(targets)
        self.done = 0
        typed = wanted.users and wanted.account is not None
        self._batch = Batch(
            list(targets),
            lambda target: checks.run(target[1], wanted),
            self._report,
            # A typed password goes host by host until one accepts it, and stops at a rejection.
            halts=checks.account_rejected if typed else lambda _r, _e: False,
            proves=checks.account_proven if typed else None,
        )

    def start(self) -> None:
        threading.Thread(target=self._run, name="refresh", daemon=True).start()

    def stop(self) -> None:
        self._batch.stop()

    @property
    def stopped(self) -> bool:
        """By Stop, or by a rejected account."""
        return self._batch.stopped

    @property
    def halted(self) -> bool:
        """Stopped because a host rejected the typed account."""
        return self._batch.halted

    def _run(self) -> None:
        try:
            self._batch.run()
        finally:
            self.finished.emit()

    def _report(
        self, target: tuple[str, str], found: Found | None, error: Exception | None
    ) -> None:
        if found is None:  # a bug in a check: show it as unreadable rather than lose the host
            found = Found(users_error=SessionsError(Reason.OTHER)) if error else Found()
        self.found.emit(target[0], found)


class AccountDialog(QDialog):
    """Another account for reading who is logged on, when the Windows login can't."""

    def __init__(self, parent: QWidget | None, reason: str, user: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Account for logged-on users"))
        intro = QLabel(reason)
        intro.setWordWrap(True)
        self.user = QLineEdit(user)
        self.user.setMaxLength(MAX_TEXT)
        self.user.setPlaceholderText(_("DOMAIN\\user"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(MAX_TEXT)
        form = QFormLayout()
        form.addRow(_("&User:"), self.user)
        form.addRow(_("&Password:"), self.password)
        note = QLabel(
            _(
                "Kept in memory until CapyPanel closes, never saved, and used only to read who "
                "is logged on. If a computer rejects it, CapyPanel stops and asks again instead "
                "of trying it on the others, so the account isn't locked."
            )
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
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


# ---- how results read ----


def when_text(when: datetime) -> str:
    moment = QDateTime.fromSecsSinceEpoch(int(when.timestamp()), QTimeZone.systemTimeZone())
    return QLocale(i18n.language()).toString(moment, QLocale.FormatType.ShortFormat)


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


def user_name(session: Session) -> str:
    """How a logged-on user reads everywhere: "DOMAIN\\name", or "name" with domains off."""
    if session.domain and _show_domains:
        return f"{session.domain}\\{session.user}"
    return session.user


def users_text(sessions: Sequence[Session] | None, error: SessionsError | None) -> str:
    if error is not None:
        return {
            Reason.UNREACHABLE: _("Unreachable"),
            Reason.NOT_ADMIN: _("Not an admin there"),
            Reason.REJECTED: _("Account rejected"),
            Reason.OTHER: _("Couldn't read"),
        }[error.reason]
    if not sessions:
        return _("Nobody")
    names = []
    for session in sessions:
        name = user_name(session)
        if session.state == "disconnected":
            name = _("{user} (disconnected)").format(user=name)
        if name not in names:
            names.append(name)
    return ", ".join(names)


def users_tip(error: SessionsError | None, when: datetime) -> str:
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


def session_lines(sessions: Sequence[Session]) -> str:
    """One line per session, for the details pane."""
    kinds = {"console": _("at the computer"), "rdp": _("Remote Desktop")}
    states = {"active": _("active"), "disconnected": _("disconnected"), "idle": _("idle")}
    lines = []
    for session in sessions:
        parts = [kinds.get(session.kind, ""), states.get(session.state, session.state)]
        if session.logon_time is not None:
            parts.append(_("since {when}").format(when=when_text(session.logon_time)))
        if session.client:
            parts.append(_("from {computer}").format(computer=session.client))
        details = ", ".join(p for p in parts if p)
        lines.append(f"{user_name(session)} — {details}")
    return "\n".join(lines)
