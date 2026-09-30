"""The list that's open in the app: its file, its content, and saving each edit safely."""

from pathlib import Path

from capypanel.core.hosts import listfile
from capypanel.core.hosts.listfile import FileStamp
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _


class ReadOnlyListError(listfile.HostListFileError):
    """An edit was attempted on a list that can't be changed."""


def starter_list() -> HostList:
    """A new list starts with one group, so there's always somewhere to add the first host."""
    host_list, _group = HostList().add_group(_("Hosts"))
    return host_list


class OpenList:
    def __init__(self, path: Path, hosts: HostList, stamp: FileStamp, *, read_only: bool) -> None:
        self.path = path
        self.hosts = hosts
        self.stamp = stamp
        self.read_only = read_only

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False) -> "OpenList":
        loaded = listfile.load(path)
        read_only = read_only or not listfile.can_write(path)
        return cls(path, loaded.hosts, loaded.stamp, read_only=read_only)

    @classmethod
    def create(cls, path: Path, *, replace_existing: bool = False) -> "OpenList":
        """Writes a new starter list. `replace_existing` only after the user confirmed it."""
        return cls.save_as(path, starter_list(), replace_existing=replace_existing)

    @classmethod
    def save_as(cls, path: Path, hosts: HostList, *, replace_existing: bool = False) -> "OpenList":
        expected = listfile.stamp_of(path) if replace_existing else None
        stamp = listfile.save(path, hosts, expected=expected)
        return cls(path, hosts, stamp, read_only=False)

    def commit(self, new: HostList) -> None:
        """Saves an edited list. If the file changed on disk meanwhile, nothing changes here and
        HostListChangedError is raised, so the caller can offer a copy or a reload."""
        if self.read_only:
            raise ReadOnlyListError(_("This list is read-only."))
        self.stamp = listfile.save(self.path, new, expected=self.stamp)
        self.hosts = new

    def reload(self) -> None:
        loaded = listfile.load(self.path)
        self.hosts, self.stamp = loaded.hosts, loaded.stamp
