from dataclasses import dataclass


@dataclass(frozen=True)
class ListTexts:
    kind: str
    everything: str
    lists: str
    new: str
    add: str
    open: str
    remove: str
    manage: str
    no_list: str
    choose_first: str
    not_this_kind: str
    file_filter: str
    not_this_kind_place: str = ""


@dataclass(frozen=True)
class EmptyTexts:
    empty_list: str = ""
    read_only_list: str = ""
    group: str = ""
    loose: str = ""
    search: str = ""
