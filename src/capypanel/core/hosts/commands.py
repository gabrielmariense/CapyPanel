"""Every command that acts on one host, defined once. The host right-click menu, the Details
panel's buttons and the manual connection window are all built from this list, so a new command
shows up everywhere at once and looks the same in each place.

Each command says what it needs from the PC, which is how CapyPanel knows what can fail: READ
only reads (status, users, facts), OPEN_HERE opens something on this PC pointed at the PC (File
Explorer, a console), and ASK_WINDOWS asks Windows on the PC to do something through its own
remote calls (log off, restart, the print spooler). Nothing in this list installs or runs a
program on the PC."""

from dataclasses import dataclass
from enum import StrEnum

from capypanel.core.i18n import N_


class Need(StrEnum):
    READ = "read"
    OPEN_HERE = "open-here"
    ASK_WINDOWS = "ask-windows"


class Group(StrEnum):
    CHECK = "check"
    OPEN = "open"
    USERS = "users"
    POWER = "power"
    PRINTERS = "printers"


GROUP_NAMES = {  # in the order the menu and the manual connection window show them
    Group.CHECK: N_("Check"),
    Group.OPEN: N_("Open"),
    Group.USERS: N_("Users"),
    Group.POWER: N_("Power"),
    Group.PRINTERS: N_("Printers"),
}


@dataclass(frozen=True)
class HostCommand:
    id: str
    group: Group
    name: str  # English; shown through _(). Ends with "…" when a window or question comes first.
    description: str  # one line, for the manual connection window and tooltips
    icon: str  # a Tabler icon's name
    need: Need
    risky: bool = False  # disturbs whoever uses the PC: shown in amber, always asks first
    needs_user: bool = False  # only when someone is logged on to the PC


COMMANDS: tuple[HostCommand, ...] = (
    HostCommand(
        "status", Group.CHECK, N_("Refresh status"),
        N_("Whether the PC answers on the network."), "refresh", Need.READ,
    ),
    HostCommand(
        "users", Group.CHECK, N_("Refresh logged-on users"),
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
    ),
    HostCommand(
        "c-share", Group.OPEN, N_("C$ share"),
        N_("The PC's C: drive in File Explorer."), "folder-share", Need.OPEN_HERE,
    ),
    HostCommand(
        "startup", Group.OPEN, N_("Startup folder"),
        N_("The programs that start for every user who signs in."), "rocket", Need.OPEN_HERE,
    ),
    HostCommand(
        "path", Group.OPEN, N_("Open a path…"),
        N_("Any folder on the PC, such as D:\\Logs."), "folder-search", Need.OPEN_HERE,
    ),
    HostCommand(
        "user-folder", Group.OPEN, N_("User's folder"),
        N_("The logged-on user's profile folder."), "folder-user", Need.OPEN_HERE,
        needs_user=True,
    ),
    HostCommand(
        "computer-management", Group.OPEN, N_("Computer Management"),
        N_("Windows' Computer Management, pointed at the PC."), "device-desktop-cog",
        Need.OPEN_HERE,
    ),
    HostCommand(
        "event-viewer", Group.OPEN, N_("Event Viewer"),
        N_("The PC's event logs."), "list-search", Need.OPEN_HERE,
    ),
    HostCommand(
        "services", Group.OPEN, N_("Services"),
        N_("The PC's Windows services."), "settings-cog", Need.OPEN_HERE,
    ),
    HostCommand(
        "message", Group.USERS, N_("Send a message…"),
        N_("A pop-up on the screen of everyone signed in."), "message", Need.ASK_WINDOWS,
        needs_user=True,
    ),
    HostCommand(
        "disconnect", Group.USERS, N_("Disconnect…"),
        N_("Ends a user's session connection; their programs keep running."), "plug-connected-x",
        Need.ASK_WINDOWS, risky=True, needs_user=True,
    ),
    HostCommand(
        "log-off", Group.USERS, N_("Log off…"),
        N_("Signs a user out; unsaved work is lost."), "logout", Need.ASK_WINDOWS,
        risky=True, needs_user=True,
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
        "cancel-restart", Group.POWER, N_("Cancel restart"),
        N_("Stops a restart or shutdown that is still waiting."), "clock-x", Need.ASK_WINDOWS,
    ),
    HostCommand(
        "printers", Group.PRINTERS, N_("Printers on this PC"),
        N_("The printers installed on the PC, their queues and problems."), "printer",
        Need.ASK_WINDOWS,
    ),
    HostCommand(
        "spooler", Group.PRINTERS, N_("Restart Print Spooler…"),
        N_("Restarts Windows' printing service, which unsticks most queues."), "printer-off",
        Need.ASK_WINDOWS, risky=True,
    ),
)  # fmt: skip

# The Details panel's icon row, in order; every command is under its … button.
QUICK = ("c-share", "user-folder", "computer-management", "message", "log-off", "restart")


def command(command_id: str) -> HostCommand:
    """Raises KeyError for an unknown id."""
    return _BY_ID[command_id]


def in_group(group: Group) -> list[HostCommand]:
    return [c for c in COMMANDS if c.group is group]


_BY_ID = {c.id: c for c in COMMANDS}
