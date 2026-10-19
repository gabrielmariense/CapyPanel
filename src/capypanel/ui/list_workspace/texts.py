"""The words a list tool uses for its lists, and the kind its list files say they are."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ListTexts:
    """Made by the tool each time it's needed (list_texts()), so it's in the current language."""

    kind: str  # "hosts": written in each list file, and its lists folders' name
    everything: str  # "All hosts": pinned on top of the Groups panel, and Show first
    lists: str  # "Host lists": the Settings page and its table's heading
    new: str  # "New host list": the New list window
    add: str  # "Add a host list": Add existing…'s file dialog
    open: str  # "Open a host list": Open list…'s file dialog
    remove: str  # "Remove host list": the question when removing one
    manage: str  # "&Manage host lists…": the list dropdown's last item
    no_list: str  # "No host list is open.": the status bar
    choose_first: str  # "Open a host list to choose what it shows first."
    not_this_kind: str  # "“{path}” isn't a host list.": another tool's list was opened
    file_filter: str  # "Host lists (*.json);;All files (*)"
