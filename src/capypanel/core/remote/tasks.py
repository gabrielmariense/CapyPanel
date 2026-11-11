"""Starting a program on another PC through that PC's own Task Scheduler service.

CapyPanel asks the PC's Task Scheduler itself, over the network (Windows' remote calls, the
channel the reads over WMI use), to make a task for the run and start it. Nothing is started on
the PC to get in, so this works where the PC refuses programs started over WMI or by PsExec's
service, and where PsExec isn't allowed at all: the program is started by Windows' own Task
Scheduler, as the PC's own tasks are.

The task goes away by itself: the wrapper deletes it when the run ends, and its trigger expires
an hour after the run's time, when Windows deletes a task left behind (CapyPanel closed, the
wrapper never started)."""

import contextlib
import getpass
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape

from capypanel.core.remote.access import Account, code_text

TIMEOUT = 60.0  # seconds to make the task and start it
KEEP = timedelta(hours=1)  # after the run's time, before Windows deletes a task left behind
_CREATE_OR_UPDATE = 6  # TASK_CREATE_OR_UPDATE
_PASSWORD, _S4U, _SERVICE_ACCOUNT = 1, 2, 5  # TASK_LOGON_*
_ACCESS_DENIED = 0x80070005


class Refused(Exception):
    """The PC's Task Scheduler answered, and wouldn't make or start the task."""


class Failed(Exception):
    """The Task Scheduler couldn't be asked: not answering, or not usable from this PC."""


@dataclass(frozen=True)
class Principal:
    """Who the task runs as, and how Windows signs it in."""

    user: str  # "SYSTEM" or "DOMAIN\\name"
    logon: int
    password: str | None = None

    @property
    def xml(self) -> str:
        if self.logon == _SERVICE_ACCOUNT:  # no LogonType: not every Windows takes it here
            return "<UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel>"
        logon = "Password" if self.logon == _PASSWORD else "S4U"
        return (
            f"<UserId>{escape(self.user)}</UserId><LogonType>{logon}</LogonType>"
            "<RunLevel>HighestAvailable</RunLevel>"
        )


def name(run_id: str) -> str:
    """The task's name on the PC; the wrapper deletes it by this name."""
    return f"CapyPanel-{run_id}-in"


def principal(system: bool, account: Account | None) -> Principal:
    """SYSTEM; or the account CapyPanel uses for the PC: a typed one with its password, this
    Windows account without one (S4U: the task then reaches no other PC)."""
    if system:
        return Principal("SYSTEM", _SERVICE_ACCOUNT)
    if account is not None:
        return Principal(account.user, _PASSWORD, account.password)
    return Principal(windows_user(), _S4U)


def windows_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def definition(
    program: str, arguments: str, who: Principal, limit: float, now: datetime | None = None
) -> str:
    """The task, as Task Scheduler's XML. It starts only when asked (its trigger is in the
    past), Windows stops it after `limit` seconds and a minute, and deletes it once its trigger
    expires."""
    now = now or datetime.now(UTC)

    def when(moment: datetime) -> str:
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    begin, end = now - timedelta(days=1), now + timedelta(seconds=limit) + KEEP
    return (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        f"<Triggers><TimeTrigger><StartBoundary>{when(begin)}</StartBoundary>"
        f"<EndBoundary>{when(end)}</EndBoundary><Enabled>true</Enabled></TimeTrigger>"
        "</Triggers>"
        f'<Principals><Principal id="Run">{who.xml}</Principal></Principals>'
        "<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>"
        "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>"
        "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>"
        "<StartWhenAvailable>false</StartWhenAvailable>"
        "<AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled>"
        f"<ExecutionTimeLimit>PT{int(limit) + 60}S</ExecutionTimeLimit>"
        "<DeleteExpiredTaskAfter>PT0S</DeleteExpiredTaskAfter><Priority>7</Priority>"
        "</Settings>"
        f'<Actions Context="Run"><Exec><Command>{escape(program)}</Command>'
        f"<Arguments>{escape(arguments)}</Arguments></Exec></Actions></Task>"
    )


def start(
    host: str,
    account: Account | None,
    task: str,
    xml: str,
    who: Principal,
    timeout: float = TIMEOUT,
) -> None:
    """Makes `task` in the Task Scheduler of `host`, signed in with `account` (None: this
    Windows account), and starts it. Runs on a thread of its own with COM set up, so a PC that
    stops answering holds that thread only. Raises Refused, Failed, or TimeoutError."""
    box: dict[str, BaseException] = {}

    def run() -> None:
        try:
            import pythoncom
            import pywintypes
            import win32com.client
        except ImportError as e:
            box["error"] = Failed(f"it can't be used from this PC ({e})")
            return
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            if account is None:
                service.Connect(host)
            else:
                domain, _sep, user = account.user.rpartition("\\")  # or a name@domain
                service.Connect(host, user, domain, account.password)
            folder = service.GetFolder("\\")
            folder.RegisterTask(task, xml, _CREATE_OR_UPDATE, who.user, who.password, who.logon)
            folder.GetTask(task).Run(None)
        except pywintypes.com_error as e:
            box["error"] = _error(e)
        except BaseException as e:  # noqa: BLE001 - handed to the caller's thread
            box["error"] = e
        finally:
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()

    thread = threading.Thread(target=run, name="task-scheduler", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():  # left to end on its own: COM calls can't be cut short
        raise TimeoutError(f"the Task Scheduler didn't answer within {timeout:.0f} s")
    if "error" in box:
        raise box["error"]


def _error(error: Any) -> Exception:
    args = getattr(error, "args", ())
    code = 0
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 6 and args[2][5]:
        code = int(args[2][5])
    elif args and isinstance(args[0], int):
        code = int(args[0])
    code &= 0xFFFFFFFF
    said = ""
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 3 and args[2][2]:
        said = str(args[2][2]).strip()
    elif len(args) >= 2 and args[1]:
        said = str(args[1]).strip()
    if code == _ACCESS_DENIED:
        return Refused("the PC's Task Scheduler refused the task (access denied)")
    return Failed(f"{said or 'the Task Scheduler failed'} ({code_text(code)})")
