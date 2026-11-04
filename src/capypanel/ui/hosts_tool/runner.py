"""Running a host command: the work goes to a background thread, the answer comes back as one
Outcome (a sentence, and the error when it failed), which the Hosts tool shows in its result strip
and the Commands window beside the command. Reading who is signed in, the account to use and
"Try another account…" are shared by every command."""

import getpass
import html
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog, QWidget

from capypanel.core.hosts import commands as host_commands
from capypanel.core.i18n import _
from capypanel.core.remote import access, places, power, services, sessions
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.places import Console
from capypanel.core.remote.sessions import Session
from capypanel.ui import checks as check_texts
from capypanel.ui.checks import AccountDialog
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool import command_windows as windows

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.tool import HostsTool


def escape(text: str) -> str:
    """Text shown as rich text: <, > and & escaped; quotes stay as they are."""
    return html.escape(text, quote=False)


log = logging.getLogger(__name__)

RETRY_REASONS = (Reason.NOT_ADMIN, Reason.REJECTED)  # another account may do


@dataclass(frozen=True)
class HostTarget:
    """The PC a command is for: a host of the open list, or an address typed on the spot."""

    key: str  # the host's id, or "@" and the address: where its results are kept
    name: str  # what messages call it
    address: str


@dataclass(frozen=True)
class Outcome:
    text: str  # rich text: names in bold
    error: BaseException | None = None  # None: it worked
    retry: Callable[[], None] | None = None  # run it again once another account is typed

    @property
    def failed(self) -> bool:
        return self.error is not None


Report = Callable[[str, Outcome], None]  # command id, its outcome


class Job(QObject):
    """One piece of work on a background thread; `done` brings back its value or its error."""

    done = Signal(object, object)  # value, exception

    def __init__(self, work: Callable[[], Any]) -> None:
        super().__init__()
        self._work = work

    def start(self) -> None:
        threading.Thread(target=self._run, name="host-command", daemon=True).start()

    def _run(self) -> None:
        try:
            value = self._work()
        except Exception as e:  # noqa: BLE001 - every failure becomes an Outcome
            if not isinstance(e, (RemoteError, TimeoutError, OSError, ValueError)):
                log.exception("A host command failed")
            self.done.emit(None, e)
        else:
            self.done.emit(value, None)


# ---- how answers read ----


def bold(text: str) -> str:
    return f"<b>{escape(text)}</b>"


def reason_text(error: BaseException) -> str:
    """Why it failed, as the end of "Couldn't … on DESK-02: …"."""
    if isinstance(error, RemoteError):
        return {
            Reason.UNREACHABLE: _(
                "it didn't answer. It's off, not on the network, or a firewall blocks file sharing."
            ),
            Reason.NOT_ADMIN: _("access denied. It needs an admin account on that PC."),
            Reason.REJECTED: _(
                "it didn't accept the account: a wrong password, a locked account, or one it "
                "doesn't trust."
            ),
            Reason.OTHER: _("Windows error {code}.").format(code=error.code),
        }[error.reason]
    if isinstance(error, TimeoutError):
        return _("it took too long to answer.")
    return _("{error}.").format(error=str(error).rstrip(".") or type(error).__name__)


def failed_text(action: str, host: str, error: BaseException) -> str:
    """`action` is rich text already, e.g. "log off <b>ana</b>"."""
    return _("Couldn't {action} on {host}: {reason}").format(
        action=action, host=escape(host), reason=escape(reason_text(error))
    )


def person(session: Session) -> str:
    """A signed-in person in messages and menus: the name, without the domain."""
    return session.user


def own_session(session: Session) -> bool:
    """Whether it's the person using CapyPanel: their own session isn't sent messages."""
    try:
        me = getpass.getuser()
    except (OSError, KeyError):
        return False
    return session.user.casefold() == me.casefold()


def recipients(found: Sequence[Session]) -> list[Session]:
    """Who Send a message reaches: everyone at their screen, not disconnected sessions or the
    person sending it."""
    return [s for s in check_texts.by_state(found) if s.state == "active" and not own_session(s)]


def folder_user(found: Sequence[Session] | None) -> Session | None:
    """Whose folder "User's folder" opens: the person at the PC, else the first one active."""
    people = check_texts.by_state(found or ())
    for session in people:
        if session.kind == "console" and session.state == "active":
            return session
    return people[0] if people else None


class Runner(QObject):
    """Runs the host commands for the Hosts tool and its windows."""

    facts_changed = Signal(str)  # a target's key: its PC facts were read, or are being read

    def __init__(self, tool: "HostsTool") -> None:
        super().__init__(tool)
        self._tool = tool
        self._jobs: set[Job] = set()

    # ---- the common parts ----

    def _start(
        self,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        job = Job(work)
        self._jobs.add(job)

        def finish(value: object, error: object) -> None:
            self._jobs.discard(job)
            if isinstance(error, BaseException):
                failed(error)
            else:
                done(value)

        job.done.connect(finish)
        job.start()

    def busy(self) -> bool:
        return bool(self._jobs)

    def account(self) -> Account | None:
        return self._tool.account()

    def _fail(
        self,
        report: Report,
        command_id: str,
        action: str,
        target: HostTarget,
        error: BaseException,
        again: Callable[[], None],
    ) -> None:
        retry = None
        if isinstance(error, RemoteError) and error.reason in RETRY_REASONS:
            retry = lambda: self.another_account(target, error, again)  # noqa: E731
        report(command_id, Outcome(failed_text(action, target.name, error), error, retry))

    def another_account(
        self, target: HostTarget, error: BaseException | None, again: Callable[[], None]
    ) -> None:
        """Try another account…: asks for one, keeps it like Refresh's, then runs `again`."""
        current = self.account()
        if isinstance(error, RemoteError) and error.reason is Reason.REJECTED and current:
            text = _("{host} didn't accept “{user}”. Type the password again, or use another "
                     "account.").format(host=target.name, user=current.user)  # fmt: skip
        else:
            text = _(
                "Use an account that is an administrator of {host}, such as a domain admin."
            ).format(host=target.name)
        dialog = AccountDialog(
            self._parent_widget(),
            text,
            current.user if current else "",
            saved=self._tool.connector.credentials.saving,
        )
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._tool.use_account(dialog.account())
            again()

    def _parent_widget(self) -> QWidget:
        window = self._tool.window()
        active = window.window() if window is not None else None
        return active if isinstance(active, QWidget) else self._tool

    def with_sessions(
        self,
        target: HostTarget,
        then: Callable[[Sequence[Session] | None, BaseException | None], None],
    ) -> None:
        """Who is signed in, from the last check, or read now when there's none."""
        known = self._tool.users_found(target.key)
        if known is not None and known[0] is not None:
            then(known[0], None)
            return

        def read() -> list[Session]:
            return sessions.read_sessions(target.address, self.account())

        def done(found: list[Session]) -> None:
            self._tool.keep_users(target.key, tuple(found), None)
            then(found, None)

        def failed(error: BaseException) -> None:
            if isinstance(error, RemoteError):
                self._tool.keep_users(target.key, None, error)
            then(None, error)

        self._start(read, done, failed)

    # ---- running a command ----

    def run(
        self,
        command_id: str,
        target: HostTarget,
        report: Report,
        *,
        parent: QWidget | None = None,
        session: Session | None = None,
    ) -> None:
        """Runs one command of core.hosts.commands for `target`. `session`: the person a
        per-person command is for. `parent`: the window its questions open over."""
        self._parent = parent
        handler = {
            "all-checks": self._all_checks,
            "status": lambda t, r: self._tool.check_target(t, status=True, users=False, report=r),
            "users": lambda t, r: self._tool.check_target(t, status=False, users=True, report=r),
            "facts": lambda t, r: self.read_facts(t, report=r),
            "programs": self._programs,
            "c-share": lambda t, r: self._open(t, r, "c-share", lambda: places.share(t.address)),
            "startup": lambda t, r: self._open(
                t, r, "startup", lambda: places.startup_folder(t.address)
            ),
            "path": self._open_path,
            "user-folder": self._user_folder,
            "computer-management": lambda t, r: self._console(t, Console.COMPUTER_MANAGEMENT),
            "event-viewer": lambda t, r: self._console(t, Console.EVENT_VIEWER),
            "services": lambda t, r: self._console(t, Console.SERVICES),
            "message": lambda t, r: self._message(t, r, session),
            "restart": lambda t, r: self._power(t, r, restart=True),
            "shut-down": lambda t, r: self._power(t, r, restart=False),
            "cancel-restart": self._cancel_restart,
            "printers": self._printers,
            "spooler": self._spooler,
        }
        if command_id in ("log-off", "disconnect"):
            if session is not None:
                self._session_action(command_id, target, report, session)
            return
        handler[command_id](target, report)

    def _window(self) -> QWidget:
        return self._parent if self._parent is not None else self._parent_widget()

    def _all_checks(self, target: HostTarget, report: Report) -> None:
        self._tool.check_target(target, status=True, users=True, report=report)
        self.read_facts(target, report=report)

    # ---- Open ----

    def _open(
        self, target: HostTarget, report: Report, command_id: str, where: Callable[[], str]
    ) -> None:
        """File Explorer on `where()`, once the PC answers: Explorer itself can hang for half a
        minute on a PC that's off."""
        name = _(host_commands.command(command_id).name)

        def check() -> str:
            access.check_reachable(target.address)
            return where()

        def done(path: str) -> None:
            try:
                places.open_folder(path)
            except OSError as e:
                failed(e)
                return
            self._tool.say(_("Opened {path}").format(path=path))

        def failed(error: BaseException) -> None:
            action = _("open {what}").format(what=escape(name))
            again = lambda: self._open(target, report, command_id, where)  # noqa: E731
            self._fail(report, command_id, action, target, error, again)

        self._start(check, done, failed)

    def _open_path(self, target: HostTarget, report: Report) -> None:
        dialog = windows.OpenPathDialog(self._window(), target.name, self._tool.recent_paths())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        typed = dialog.typed()
        self._tool.remember_path(typed)
        self._open(target, report, "path", lambda: places.typed_path(target.address, typed))

    def _user_folder(self, target: HostTarget, report: Report) -> None:
        def go(found: Sequence[Session] | None, error: BaseException | None) -> None:
            who = folder_user(found)
            if who is None:
                text = _("No one is signed in to {host}, so there's no user's folder to open.")
                failure = error or RemoteError(Reason.OTHER)
                report("user-folder", Outcome(text.format(host=escape(target.name)), failure))
                return
            self._open(
                target,
                report,
                "user-folder",
                lambda: places.user_folder(target.address, person(who)),
            )

        self.with_sessions(target, go)

    def _console(self, target: HostTarget, console: Console) -> None:
        try:
            places.open_console(target.address, console)
        except OSError as e:
            self._tool.say(_("Couldn't open it: {error}").format(error=e))

    # ---- Users ----

    def _message(self, target: HostTarget, report: Report, only: Session | None) -> None:
        def ask(found: Sequence[Session] | None, error: BaseException | None) -> None:
            if found is None:
                action = _("send a message")
                again = lambda: self._message(target, report, only)  # noqa: E731
                self._fail(report, "message", action, target, error or RemoteError(Reason.OTHER),
                           again)  # fmt: skip
                return
            to = [only] if only is not None else recipients(found)
            dialog = windows.MessageDialog(self._window(), target.name, to)
            if run_modal(dialog) == QDialog.DialogCode.Accepted and to:
                self._send(target, report, to, dialog.text())

        if only is not None:
            ask([only], None)
        else:
            self.with_sessions(target, ask)

    def _send(self, target: HostTarget, report: Report, to: Sequence[Session], text: str) -> None:
        names = ", ".join(bold(person(s)) for s in to)
        title = _("Message from {user}").format(user=_sender())

        def send() -> None:
            for session in to:
                sessions.send_message(target.address, session.session_id, title, text,
                                      self.account())  # fmt: skip

        def done(_value: object) -> None:
            text_ = _("Message sent to {names} on {host}.")
            report("message", Outcome(text_.format(names=names, host=escape(target.name))))

        def failed(error: BaseException) -> None:
            again = lambda: self._send(target, report, to, text)  # noqa: E731
            action = _("send the message to {names}").format(names=names)
            self._fail(report, "message", action, target, error, again)

        self._start(send, done, failed)

    def _session_action(
        self, command_id: str, target: HostTarget, report: Report, session: Session
    ) -> None:
        log_off = command_id == "log-off"
        if not windows.ask_session_action(self._window(), target.name, session, log_off=log_off):
            return
        self._do_session_action(command_id, target, report, session)

    def _do_session_action(
        self, command_id: str, target: HostTarget, report: Report, session: Session
    ) -> None:
        log_off = command_id == "log-off"
        call = sessions.log_off if log_off else sessions.disconnect
        who = bold(person(session))

        def act() -> None:
            call(target.address, session.session_id, self.account())

        def done(_value: object) -> None:
            text = (
                _("Logged off {user} on {host}.")
                if log_off
                else _("Disconnected {user} on {host}.")
            )
            report(command_id, Outcome(text.format(user=who, host=escape(target.name))))
            self._tool.check_target(target, status=False, users=True, report=None)

        def failed(error: BaseException) -> None:
            action = (_("log off {user}") if log_off else _("disconnect {user}")).format(user=who)
            again = lambda: self._do_session_action(command_id, target, report, session)  # noqa: E731
            self._fail(report, command_id, action, target, error, again)

        self._start(act, done, failed)

    # ---- Power ----

    def _power(self, target: HostTarget, report: Report, *, restart: bool) -> None:
        def ask(found: Sequence[Session] | None, error: BaseException | None) -> None:
            dialog = windows.PowerDialog(self._window(), target.name, found, restart=restart)
            if run_modal(dialog) == QDialog.DialogCode.Accepted:
                people = [s for s in found or () if s.state == "active"]
                self._shut_down(target, report, restart, dialog.delay(), dialog.message(), people)

        self.with_sessions(target, ask)

    def _shut_down(
        self,
        target: HostTarget,
        report: Report,
        restart: bool,
        delay: int,
        message: str,
        people: Sequence[Session],
    ) -> None:
        command_id = "restart" if restart else "shut-down"
        call = power.restart if restart else power.shut_down
        asked = datetime.now(UTC)

        def act() -> None:
            call(target.address, delay, message, self.account())

        def done(_value: object) -> None:
            at = asked + timedelta(seconds=delay)
            host = escape(target.name)
            clock = check_texts.clock_text(at)
            if delay:
                text = (_("{host} restarts at {when}.") if restart
                        else _("{host} shuts down at {when}."))  # fmt: skip
                text = text.format(host=host, when=clock)
            else:
                text = (_("{host} is restarting.") if restart
                        else _("{host} is shutting down.")).format(host=host)  # fmt: skip
            report(command_id, Outcome(text))
            told = [person(p) for p in people] if message else []
            self._tool.power_started(target, restart=restart, at=at, asked=asked, told=told)

        def failed(error: BaseException) -> None:
            if isinstance(error, RemoteError) and power.already_pending(error):
                error = RemoteError(Reason.OTHER, error.code)
                text = _("Couldn't {action} on {host}: a restart or shutdown is already on its "
                         "way. Cancel it first.")  # fmt: skip
                action = _("restart it") if restart else _("shut it down")
                report(command_id, Outcome(text.format(action=action, host=escape(target.name)),
                                           error))  # fmt: skip
                return
            action = _("restart it") if restart else _("shut it down")
            again = lambda: self._shut_down(target, report, restart, delay, message, people)  # noqa: E731
            self._fail(report, command_id, action, target, error, again)

        self._start(act, done, failed)

    def _cancel_restart(self, target: HostTarget, report: Report) -> None:
        def act() -> bool:
            return power.cancel(target.address, self.account())

        def done(cancelled: bool) -> None:
            host = escape(target.name)
            text = (_("The restart or shutdown of {host} is cancelled.") if cancelled
                    else _("Nothing was waiting to restart or shut down {host}."))  # fmt: skip
            report("cancel-restart", Outcome(text.format(host=host)))
            self._tool.power_cancelled(target)

        def failed(error: BaseException) -> None:
            again = lambda: self._cancel_restart(target, report)  # noqa: E731
            self._fail(report, "cancel-restart", _("cancel the restart"), target, error, again)

        self._start(act, done, failed)

    # ---- Printers ----

    def _printers(self, target: HostTarget, report: Report) -> None:
        dialog = windows.PrintersDialog(self._window(), self, target, report)
        run_modal(dialog)

    def _spooler(self, target: HostTarget, report: Report) -> None:
        if windows.ask_spooler(self._window(), target.name):
            self.restart_spooler(target, report)

    def restart_spooler(
        self, target: HostTarget, report: Report, then: Callable[[], None] | None = None
    ) -> None:
        def act() -> None:
            services.restart_service(target.address, services.SPOOLER, self.account())

        def done(_value: object) -> None:
            text = _("Print Spooler restarted on {host}.").format(host=escape(target.name))
            report("spooler", Outcome(text))
            if then is not None:
                then()

        def failed(error: BaseException) -> None:
            again = lambda: self.restart_spooler(target, report, then)  # noqa: E731
            action = _("restart the Print Spooler")
            self._fail(report, "spooler", action, target, error, again)

        self._start(act, done, failed)

    def call(
        self,
        work: Callable[[Account | None], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        """For the command windows: `work` gets the account to use, on a background thread."""
        self._start(lambda: work(self.account()), done, failed)

    # ---- Check ----

    def read_facts(self, target: HostTarget, *, report: Report | None = None) -> None:
        """PC facts: free space and the last restart at once, then the rest over WMI."""
        self._tool.facts_reading(target.key)
        self.facts_changed.emit(target.key)
        from capypanel.core.remote import inventory  # its PowerShell parts load on first use

        def quick() -> tuple[Any, Any]:
            account = self.account()
            return (inventory.disk_space(target.address, account),
                    inventory.last_restart(target.address, account))  # fmt: skip

        def slow() -> Any:
            return inventory.pc_facts(target.address, self.account())

        def quick_done(found: tuple[Any, Any]) -> None:
            self._tool.keep_facts(target.key, quick=found)
            self.facts_changed.emit(target.key)
            self._start(slow, slow_done, slow_failed)

        def quick_failed(error: BaseException) -> None:
            self._tool.keep_facts(target.key, quick_error=error)
            self.facts_changed.emit(target.key)
            if isinstance(error, RemoteError) and error.reason is Reason.UNREACHABLE:
                self._tool.keep_facts(target.key, slow_error=error)  # WMI would only time out
                self._facts_failed(target, error, report)
                return
            self._start(slow, slow_done, slow_failed)

        def slow_done(found: Any) -> None:
            self._tool.keep_facts(target.key, slow=found)
            self.facts_changed.emit(target.key)

        def slow_failed(error: BaseException) -> None:
            self._tool.keep_facts(target.key, slow_error=error)
            self.facts_changed.emit(target.key)
            self._facts_failed(target, error, report)

        self._start(quick, quick_done, quick_failed)

    def _facts_failed(
        self, target: HostTarget, error: BaseException, report: Report | None
    ) -> None:
        if report is not None:
            again = lambda: self.read_facts(target, report=report)  # noqa: E731
            self._fail(report, "facts", _("read the PC facts"), target, error, again)

    def _programs(self, target: HostTarget, report: Report) -> None:
        dialog = windows.ProgramsDialog(self._window(), self, target, self._tool.csv_folder)
        run_modal(dialog)


def _sender() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return "IT"
