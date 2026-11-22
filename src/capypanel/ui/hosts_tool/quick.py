"""One short word, nine letters at most in any language."""

from capypanel.core.i18n import pgettext


def fixed_labels() -> dict[str, str]:
    return {
        "refresh": pgettext("button", "Refresh"),
        "commands": pgettext("button", "Commands"),
        "users": pgettext("button", "Users"),
        "power": pgettext("button", "Power"),
    }


def short_labels() -> dict[str, str]:
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
