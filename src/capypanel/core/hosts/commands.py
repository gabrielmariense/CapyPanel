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


class Group(StrEnum):  # in the order the menus and the Commands window show them
    CHECK = "check"
    FOLDERS = "folders"
    ADMIN = "admin"
    USERS = "users"
    PRINTERS = "printers"
    POWER = "power"  # last: it disturbs whoever is at the PC


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
    name: str  # English; shown through _(). Ends with "…" when a window or question comes first.
    description: str  # one line, for the manual connection window and tooltips
    icon: str  # a Tabler icon's name
    need: Need
    risky: bool = False  # disturbs whoever uses the PC: shown in amber, always asks first
    needs_user: bool = False  # only when someone is logged on to the PC
    # Acts on one signed-in person: offered on that person (Details, Users ▾), not in the lists.
    per_person: bool = False
    # Set apart from the ones above it: a line in menus, a small gap in the Commands window.
    apart: bool = False


COMMANDS: tuple[HostCommand, ...] = (
    HostCommand(
        "all-checks", Group.CHECK, N_("Quick check"),
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
        apart=True,  # a long table, not part of Quick check
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
        N_("Restarts Windows' printing service, which unsticks most queues."), "printer-off",
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

# The Details panel's icon buttons, in order; then Users ▾ and Power ▾, then … for every one.
QUICK = ("c-share", "user-folder", "computer-management", "message")


def command(command_id: str) -> HostCommand:
    """Raises KeyError for an unknown id."""
    return _BY_ID[command_id]


def in_group(group: Group) -> list[HostCommand]:
    """The group's commands as menus and lists show them: without the per-person ones."""
    return [c for c in COMMANDS if c.group is group and not c.per_person]


_BY_ID = {c.id: c for c in COMMANDS}
