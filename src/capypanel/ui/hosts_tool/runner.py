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
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import (
    access,
    builtin,
    own_scripts,
    places,
    power,
    run,
    services,
    sessions,
)
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.own_scripts import OwnScript, PcProblem, State
from capypanel.core.remote.places import Console
from capypanel.core.remote.run import Problem, RunAs, RunError, RunResult
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
    output: str = ""  # what a script wrote on the PC
    running: bool = False  # not an answer yet: it was started and is still going

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
    if isinstance(error, RunError):
        return {
            Problem.NO_WAY_IN: _("CapyPanel couldn't start anything there. WinRM is off, WMI "
                                 "didn't answer, and PsExec isn't set up or didn't work."),
            Problem.BLOCKED: _("it started but never ran. Security software on the PC may have "
                               "stopped it."),
            Problem.NOT_STARTED: _("the PC couldn't start it."),
            Problem.TIMED_OUT: _("it didn't finish in time. It may still be running there."),
            Problem.NO_RESULT: _("its answer couldn't be read."),
        }[error.problem]  # fmt: skip
    if isinstance(error, ScriptFailed):
        return _("it ended with code {code}. Its output says why.").format(code=error.code)
    if isinstance(error, OnPcRefused):
        if error.problem is PcProblem.MISSING:
            return _("there's no {path} on that PC.").format(path=error.path)
        return _("every user of that PC can change {path}, and it isn't the copy reviewed, so "
                 "it only runs as the person signed in.").format(path=error.path)  # fmt: skip
    if isinstance(error, NotApproved):
        return (_("it changed since it was approved, so it didn't run. Review it again.")
                if error.state is State.CHANGED
                else _("it can't run as it is now. Rescan to see why."))  # fmt: skip
    if isinstance(error, TimeoutError):
        return _("it took too long to answer.")
    if isinstance(error, NotADirectoryError):
        return _("there's no folder there.")
    return _("{error}.").format(error=str(error).rstrip(".") or type(error).__name__)


class ScriptFailed(Exception):
    """A script ran on the PC and ended with an exit code other than 0."""

    def __init__(self, code: int) -> None:
        super().__init__(f"exit code {code}")
        self.code = code


class OnPcRefused(Exception):
    """The launcher of a file on the PC didn't run it: missing, or every user can change it."""

    def __init__(self, problem: PcProblem, path: str) -> None:
        super().__init__(f"{problem}: {path}")
        self.problem, self.path = problem, path


class NotApproved(Exception):
    """Your own script isn't as it was approved anymore, so it didn't run."""

    def __init__(self, state: State) -> None:
        super().__init__(str(state))
        self.state = state


def size_text(size: int) -> str:
    """ "312 MB" under a gigabyte, "1.4 GB" above."""
    if size < 1024**3:
        return _("{n} MB").format(n=round(size / 1024**2))
    return _("{n} GB").format(n=f"{size / 1024**3:.1f}")


def script_output(result: RunResult) -> str:
    """What a script wrote, then what it wrote as errors."""
    return "\n".join(part.strip("\n") for part in (result.output, result.errors) if part.strip())


def script_outcome(command_id: str, host: str, result: RunResult) -> Outcome:
    """The answer of a built-in script that ran: what it did, or the code it ended with."""
    where = escape(host)
    output = script_output(result)
    if not result.worked:
        name = bold(_(host_commands.command(command_id).name).rstrip("…"))
        error = ScriptFailed(result.exit_code)
        text = failed_text(_("run {name}").format(name=name), host, error)
        return Outcome(text, error, output=output)
    if command_id == "clean-temp":
        found, rest = builtin.cleaned(result.output)
        output = "\n".join(p.strip("\n") for p in (rest, result.errors) if p.strip())
        if found is not None:
            text = ngettext("Freed {size} on {host}: {n} file deleted.",
                            "Freed {size} on {host}: {n} files deleted.", found.files)  # fmt: skip
            text = text.format(size=size_text(found.freed), host=where, n=found.files)
            if found.left:
                text += " " + ngettext("{n} file in use stayed.", "{n} files in use stayed.",
                                       found.left).format(n=found.left)  # fmt: skip
            return Outcome(text, output=output)
    texts = {
        "gpupdate": _("Group policy updated on {host}."),
        "dns": _("DNS refreshed on {host}."),
        "clock": _("Clock synced on {host}."),
        "repair": _("Repair Windows files finished on {host}. Its output says what it found."),
        "clean-temp": _("Temporary files cleaned on {host}."),
    }
    return Outcome(texts[command_id].format(host=where), output=output)


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
        self._parent: QWidget | None = None  # the window a command's questions open over
        self.scripts = run.Runner(tool.psexec_path, tool.run_log_file)
        self._running: set[tuple[str, str]] = set()  # (target key, command id) of scripts going

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

    def _start_as(
        self,
        target: HostTarget,
        work: Callable[[Account | None], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
        *,
        ask: bool = True,
    ) -> bool:
        """`work` gets the account that signs in to `target` (Settings' Accounts; None for the
        Windows account). A password not typed yet this session is asked first, unless not
        `ask`; False when it wasn't typed, and nothing started."""
        go, account = self._tool.accounts.account_for(target, self._window() if ask else None)
        if go:
            self._start(lambda: work(account), done, failed)
        return go

    def _fail(
        self,
        report: Report,
        command_id: str,
        action: str,
        target: HostTarget,
        error: BaseException,
        again: Callable[[], None],
        output: str = "",
    ) -> None:
        retry = None
        if isinstance(error, RemoteError) and error.reason in RETRY_REASONS:
            retry = lambda: self.another_account(target, error, again)  # noqa: E731
        text = failed_text(action, target.name, error)
        report(command_id, Outcome(text, error, retry, output=output))

    def another_account(
        self, target: HostTarget, error: BaseException | None, again: Callable[[], None]
    ) -> None:
        """Try another account…: asks for one and which PCs it's for (Settings' Accounts keeps
        it), then runs `again`."""
        accounts = self._tool.accounts
        current = accounts.link_for(target)
        if isinstance(error, RemoteError) and error.reason is Reason.REJECTED and current:
            text = _("{host} didn't accept “{user}”. Type the password again, or use another "
                     "account.").format(host=target.name, user=current.user)  # fmt: skip
        else:
            text = _(
                "Use an account that is an administrator of {host}, such as a domain admin."
            ).format(host=target.name)
        uses = accounts.uses_for([target])
        dialog = AccountDialog(
            self._parent_widget(),
            text,
            current.user if current else "",
            saved=accounts.saving(),
            uses=uses,
        )
        if current is not None:  # the PCs it was for, unless a narrower choice is wanted
            for index, (_label, link) in enumerate(uses):
                if link.same_place(current):
                    dialog.use_for.setCurrentIndex(index)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            link = dialog.link()
            assert link is not None  # "Every PC" at least
            accounts.use(link, dialog.account(), remember=dialog.remember.isChecked())
            again()

    def _parent_widget(self) -> QWidget:
        window = self._tool.window()
        active = window.window() if window is not None else None
        return active if isinstance(active, QWidget) else self._tool

    def with_sessions(
        self,
        target: HostTarget,
        then: Callable[[Sequence[Session] | None, BaseException | None], None],
        *,
        fresh: bool = False,
    ) -> None:
        """Who is signed in, from the last check, or read now when there's none (always now
        with `fresh`: the last check may be from before someone signed in)."""
        known = None if fresh else self._tool.users_found(target.key)
        if known is not None and known[0] is not None:
            then(known[0], None)
            return

        def read(account: Account | None) -> list[Session]:
            return sessions.read_sessions(target.address, account)

        def done(found: list[Session]) -> None:
            self._tool.keep_users(target.key, tuple(found), None)
            then(found, None)

        def failed(error: BaseException) -> None:
            if isinstance(error, RemoteError):
                self._tool.keep_users(target.key, None, error)
            then(None, error)

        self._start_as(target, read, done, failed)

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
            **{
                command_id: lambda t, r, c=command_id: self._built_in(c, t, r)
                for command_id in builtin.BUILT_IN
            },
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
            path = where()
            places.require_folder(path)  # never a file: opening one would run it here
            return path

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

        def send(account: Account | None) -> None:
            for session in to:
                sessions.send_message(target.address, session.session_id, title, text, account)

        def done(_value: object) -> None:
            text_ = _("Message sent to {names} on {host}.")
            report("message", Outcome(text_.format(names=names, host=escape(target.name))))

        def failed(error: BaseException) -> None:
            again = lambda: self._send(target, report, to, text)  # noqa: E731
            action = _("send the message to {names}").format(names=names)
            self._fail(report, "message", action, target, error, again)

        self._start_as(target, send, done, failed)

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

        def act(account: Account | None) -> None:
            call(target.address, session.session_id, account)

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

        self._start_as(target, act, done, failed)

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

        def act(account: Account | None) -> None:
            call(target.address, delay, message, account)

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

        self._start_as(target, act, done, failed)

    # ---- Scripts ----

    def _built_in(self, command_id: str, target: HostTarget, report: Report) -> None:
        """A built-in script: asked first when it disturbs the PC; never twice at once."""
        command = host_commands.command(command_id)
        if (target.key, command_id) in self._running:
            name = _(command.name).rstrip("…")
            self._tool.say(_("{name} is still running on {host}.").format(
                name=name, host=target.name))  # fmt: skip
            return
        if command.risky and not windows.ask_script(self._window(), command_id, target.name):
            return
        self._run_built_in(command_id, target, report)

    def _run_built_in(self, command_id: str, target: HostTarget, report: Report) -> None:
        go, account = self._tool.accounts.account_for(target, self._window())
        if not go:
            return
        built = builtin.BUILT_IN[command_id]
        key = (target.key, command_id)
        self._running.add(key)
        name = bold(_(host_commands.command(command_id).name).rstrip("…"))
        since = check_texts.clock_text(datetime.now(UTC))
        text = _("{name} is running on {host} since {when}…").format(
            name=name, host=escape(target.name), when=since)  # fmt: skip
        report(command_id, Outcome(text, running=True))

        def work() -> RunResult:
            return self.scripts.run(target.address, built.script, account, built.timeout)

        def done(result: RunResult) -> None:
            self._running.discard(key)
            report(command_id, script_outcome(command_id, target.name, result))

        def failed(error: BaseException) -> None:
            self._running.discard(key)
            again = lambda: self._run_built_in(command_id, target, report)  # noqa: E731
            output = "\n".join((*error.tried, error.detail)).strip() if isinstance(
                error, RunError) else ""  # fmt: skip
            action = _("run {name}").format(name=name)
            self._fail(report, command_id, action, target, error, again, output)

        self._start(work, done, failed)

    def run_own(self, script: OwnScript, target: HostTarget, report: Report, run_as: RunAs) -> None:
        """One of your own scripts, approved: asked first when it's risky; as the person
        signed in at the PC with RunAs.USER; never twice at once."""
        approval = script.approval
        if not script.ready or approval is None:
            return
        if (target.key, script.id) in self._running:
            self._tool.say(_("{name} is still running on {host}.").format(
                name=script.name, host=target.name))  # fmt: skip
            return
        if approval.risky and not windows.ask_own_script(self._window(), script.name,
                                                         target.name, run_as):  # fmt: skip
            return
        if run_as is not RunAs.USER:
            self._run_own(script, target, report, run_as, "")
            return

        def go(found: Sequence[Session] | None, error: BaseException | None) -> None:
            who = folder_user([s for s in found or () if s.state == "active"])
            if who is None:
                text = _("No one is signed in to {host}, so {name} can't run as them.").format(
                    host=escape(target.name), name=bold(script.name))  # fmt: skip
                report(script.id, Outcome(text, error or RemoteError(Reason.OTHER)))
                return
            user = f"{who.domain}\\{who.user}" if who.domain else who.user
            self._run_own(script, target, report, run_as, user)

        self.with_sessions(target, go, fresh=True)  # who is there now, not at the last Refresh

    def _run_own(
        self, script: OwnScript, target: HostTarget, report: Report, run_as: RunAs, user: str
    ) -> None:
        go, account = self._tool.accounts.account_for(target, self._window())
        if not go:
            return
        key = (target.key, script.id)
        self._running.add(key)
        name = bold(script.name)
        since = check_texts.clock_text(datetime.now(UTC))
        text = _("{name} is running on {host} since {when}…").format(
            name=name, host=escape(target.name), when=since)  # fmt: skip
        report(script.id, Outcome(text, running=True))
        approval = script.approval

        def work() -> RunResult:
            # Read again on the way: what runs is what was approved, byte for byte.
            now = own_scripts.read(script.file, approval)
            if not now.ready:
                raise NotApproved(now.state)
            sent = own_scripts.to_script(now, target.name, run_as)
            return self.scripts.run(target.address, sent, account, run.TIMEOUT, run_as, user)

        def done(result: RunResult) -> None:
            self._running.discard(key)
            output = script_output(result)
            if result.worked:
                text = _("{name} finished on {host}.").format(name=name, host=escape(target.name))
                report(script.id, Outcome(text, output=output))
                return
            error: Exception = ScriptFailed(result.exit_code)
            problem = own_scripts.pc_problem(result.output) if script.on_pc else None
            if problem is not None:
                error, output = OnPcRefused(problem, script.on_pc), ""
            text = failed_text(_("run {name}").format(name=name), target.name, error)
            report(script.id, Outcome(text, error, output=output))

        def failed(error: BaseException) -> None:
            self._running.discard(key)
            if isinstance(error, NotApproved):
                self._tool.own_scripts.rescan()  # shows it as changed, to review again
            again = lambda: self._run_own(script, target, report, run_as, user)  # noqa: E731
            output = "\n".join((*error.tried, error.detail)).strip() if isinstance(
                error, RunError) else ""  # fmt: skip
            self._fail(report, script.id, _("run {name}").format(name=name), target, error,
                       again, output)  # fmt: skip

        self._start(work, done, failed)

    def _cancel_restart(self, target: HostTarget, report: Report) -> None:
        def act(account: Account | None) -> bool:
            return power.cancel(target.address, account)

        def done(cancelled: bool) -> None:
            host = escape(target.name)
            text = (_("The restart or shutdown of {host} is cancelled.") if cancelled
                    else _("Nothing was waiting to restart or shut down {host}."))  # fmt: skip
            report("cancel-restart", Outcome(text.format(host=host)))
            self._tool.power_cancelled(target)

        def failed(error: BaseException) -> None:
            again = lambda: self._cancel_restart(target, report)  # noqa: E731
            self._fail(report, "cancel-restart", _("cancel the restart"), target, error, again)

        self._start_as(target, act, done, failed)

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
        def act(account: Account | None) -> None:
            services.restart_service(target.address, services.SPOOLER, account)

        def done(_value: object) -> None:
            text = _("Print Spooler restarted on {host}.").format(host=escape(target.name))
            report("spooler", Outcome(text))
            if then is not None:
                then()

        def failed(error: BaseException) -> None:
            again = lambda: self.restart_spooler(target, report, then)  # noqa: E731
            action = _("restart the Print Spooler")
            self._fail(report, "spooler", action, target, error, again)

        self._start_as(target, act, done, failed)

    def call(
        self,
        work: Callable[[Account | None], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
        target: HostTarget | None = None,
    ) -> None:
        """For the command windows: `work` runs on a background thread and gets the account
        that signs in to `target`; with no target, None (nothing on a PC needs one)."""
        if target is None:
            self._start(lambda: work(None), done, failed)
        else:
            self._start_as(target, work, done, failed)

    # ---- Check ----

    def read_facts(self, target: HostTarget, *, report: Report | None = None) -> None:
        """PC facts: free space and the last restart at once, then the rest over WMI. Read on
        its own (no `report`), it never asks for a password: it waits for one typed."""
        go, account = self._tool.accounts.account_for(
            target, self._window() if report is not None else None
        )
        if not go:
            return
        self._tool.facts_reading(target.key)
        self.facts_changed.emit(target.key)
        from capypanel.core.remote import inventory  # its PowerShell parts load on first use

        def quick() -> tuple[Any, Any]:
            return (inventory.disk_space(target.address, account),
                    inventory.last_restart(target.address, account))  # fmt: skip

        def slow() -> Any:
            return inventory.pc_facts(target.address, account)

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
