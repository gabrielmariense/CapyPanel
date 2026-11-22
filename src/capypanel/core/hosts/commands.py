"""No command installs or runs a program on the PC."""

from dataclasses import dataclass
from enum import StrEnum

from capypanel.core.i18n import N_


class Need(StrEnum):
    READ = "read"
    OPEN_HERE = "open-here"
    ASK_WINDOWS = "ask-windows"


class Group(StrEnum):
    CHECK = "check"
    FOLDERS = "folders"
    ADMIN = "admin"
    USERS = "users"
    PRINTERS = "printers"
    POWER = "power"


GROUP_NAMES = {
    Group.CHECK: N_("Check"),
    Group.FOLDERS: N_("Folders"),
    Group.ADMIN: N_("Admin tools"),
    Group.USERS: N_("Users"),
    Group.PRINTERS: N_("Printers"),
    Group.POWER: N_("Power"),
}


@dataclass(frozen=True)
class HostCommand:
    id: str
    group: Group
    name: str
    description: str
    icon: str
    need: Need
    risky: bool = False
    needs_user: bool = False
    per_person: bool = False
    apart: bool = False


COMMANDS: tuple[HostCommand, ...] = (
    HostCommand(
        "all-checks", Group.CHECK, N_("Refresh host"),
        N_("Status, logged-on users and PC facts, one after the other."), "list-check",
        Need.READ,
    ),
    HostCommand(
        "status", Group.CHECK, N_("Status"),
        N_("Whether the PC answers on the network."), "activity", Need.READ,
    ),
    HostCommand(
        "users", Group.CHECK, N_("Logged-on users"),
        N_("Who is signed in to the PC, and since when."), "users", Need.READ,
    ),
    HostCommand(
        "facts", Group.CHECK, N_("PC facts"),
        N_("Windows version, model, serial number, memory, free space and last restart."),
        "device-desktop-analytics", Need.READ,
    ),
    HostCommand(
        "programs", Group.CHECK, N_("Installed programs"),
        N_("The programs installed for every user of the PC."), "apps", Need.READ,
        apart=True,
    ),
    HostCommand(
        "c-share", Group.FOLDERS, N_("C$ share"),
        N_("The PC's C: drive in File Explorer."), "folder-share", Need.OPEN_HERE,
    ),
    HostCommand(
        "user-folder", Group.FOLDERS, N_("User's folder"),
        N_("The logged-on user's profile folder."), "folder-person", Need.OPEN_HERE,
        needs_user=True,
    ),
    HostCommand(
        "startup", Group.FOLDERS, N_("Startup folder"),
        N_("The programs that start for every user who signs in."), "rocket", Need.OPEN_HERE,
    ),
    HostCommand(
        "path", Group.FOLDERS, N_("Open a path…"),
        N_("Any folder on the PC, such as D:\\Logs."), "folder-search", Need.OPEN_HERE,
    ),
    HostCommand(
        "computer-management", Group.ADMIN, N_("Computer Management"),
        N_("Windows' Computer Management, pointed at the PC."), "device-desktop-cog",
        Need.OPEN_HERE,
    ),
    HostCommand(
        "event-viewer", Group.ADMIN, N_("Event Viewer"),
        N_("The PC's event logs."), "list-search", Need.OPEN_HERE,
    ),
    HostCommand(
        "services", Group.ADMIN, N_("Services"),
        N_("The PC's Windows services."), "services-play", Need.OPEN_HERE,
    ),
    HostCommand(
        "message", Group.USERS, N_("Send a message…"),
        N_("A pop-up on the screen of everyone signed in."), "message", Need.ASK_WINDOWS,
        needs_user=True,
    ),
    HostCommand(
        "drives", Group.USERS, N_("Mapped drives"),
        N_("The network drives of the people signed in: each letter and where it points."),
        "server-2", Need.READ, needs_user=True, apart=True,
    ),
    HostCommand(
        "disconnect", Group.USERS, N_("Disconnect…"),
        N_("Ends a user's session connection; their programs keep running."), "plug-connected-x",
        Need.ASK_WINDOWS, risky=True, needs_user=True, per_person=True,
    ),
    HostCommand(
        "log-off", Group.USERS, N_("Log off…"),
        N_("Signs a user out; unsaved work is lost."), "logout", Need.ASK_WINDOWS,
        risky=True, needs_user=True, per_person=True,
    ),
    HostCommand(
        "printers", Group.PRINTERS, N_("Printers on this PC"),
        N_("The printers installed on the PC, their queues and problems."), "printer",
        Need.ASK_WINDOWS,
    ),
    HostCommand(
        "spooler", Group.PRINTERS, N_("Restart Print Spooler…"),
        N_("Restarts Windows' printing service, which unsticks most queues."), "spooler-restart",
        Need.ASK_WINDOWS, risky=True,
    ),
    HostCommand(
        "restart", Group.POWER, N_("Restart…"),
        N_("Restarts Windows, now or after a delay with a message."), "refresh",
        Need.ASK_WINDOWS, risky=True,
    ),
    HostCommand(
        "shut-down", Group.POWER, N_("Shut down…"),
        N_("Turns the PC off; someone has to turn it back on."), "power", Need.ASK_WINDOWS,
        risky=True,
    ),
    HostCommand(
        "cancel-restart", Group.POWER, N_("Cancel the pending restart"),
        N_("Stops a restart or shutdown that is still waiting."), "clock-x", Need.ASK_WINDOWS,
        apart=True,
    ),
)  # fmt: skip

QUICK = ("c-share", "user-folder", "computer-management", "message")
# Quick commands never cut a person off or delete their files.
CAN_BE_QUICK = (
    "status", "users", "facts", "programs", "c-share", "user-folder", "startup", "path",
    "computer-management", "event-viewer", "services", "message", "drives", "printers",
    "spooler",
)  # fmt: skip
MENU_QUICK = 4


def quick_from(kept: object) -> tuple[str, ...]:
    """None ever chosen: the starting four; an empty choice stays empty."""
    if not isinstance(kept, list):
        return QUICK
    return tuple(command_id for command_id in CAN_BE_QUICK if command_id in kept)


def command(command_id: str) -> HostCommand:
    return _BY_ID[command_id]


def in_group(group: Group) -> list[HostCommand]:
    return [c for c in COMMANDS if c.group is group and not c.per_person]


_BY_ID = {c.id: c for c in COMMANDS}
