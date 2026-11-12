"""The words on Details' command buttons: one short word under each icon, nine letters at most
in every language, where menus and windows use the command's full name."""

from capypanel.core.i18n import pgettext


def fixed_labels() -> dict[str, str]:
    """The fixed row, which every admin has: this PC's refresh, the Commands window, and the two
    menus that act on people and on the PC's power."""
    return {
        "refresh": pgettext("button", "Refresh"),
        "commands": pgettext("button", "Commands"),
        "users": pgettext("button", "Users"),
        "power": pgettext("button", "Power"),
    }


def short_labels() -> dict[str, str]:
    """Each command that can be a quick command, by its id."""
    return {
        "status": pgettext("button", "Status"),
        "users": pgettext("button", "Logged on"),
        "facts": pgettext("button", "PC facts"),
        "programs": pgettext("button", "Programs"),
        "c-share": pgettext("button", "C$"),
        "user-folder": pgettext("button", "Folder"),
        "startup": pgettext("button", "Startup"),
        "path": pgettext("button", "Path"),
        "computer-management": pgettext("button", "Manage"),
        "event-viewer": pgettext("button", "Events"),
        "services": pgettext("button", "Services"),
        "message": pgettext("button", "Message"),
        "drives": pgettext("button", "Drives"),
        "printers": pgettext("button", "Queues"),
        "spooler": pgettext("button", "Spooler"),
    }
