from pathlib import Path

from capypanel.core.hosts import listfile
from capypanel.core.hosts.listfile import FileStamp
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _


class ReadOnlyListError(listfile.HostListFileError):
    pass


def starter_list() -> HostList:
    host_list, _group = HostList().add_group(_("Default group"))
    return host_list


class OpenList:
    def __init__(
        self,
        path: Path,
        hosts: HostList,
        stamp: FileStamp,
        *,
        read_only: bool,
        kind: str = listfile.HOSTS,
    ) -> None:
        self.path = path
        self.hosts = hosts
        self.stamp = stamp
        self.read_only = read_only
        self.kind = kind

    @classmethod
    def open(cls, path: Path, *, read_only: bool = False, kind: str = listfile.HOSTS) -> "OpenList":
        loaded = listfile.load(path, kind)
        read_only = read_only or not listfile.can_write(path)
        return cls(path, loaded.hosts, loaded.stamp, read_only=read_only, kind=kind)

    @classmethod
    def create(
        cls, path: Path, *, replace_existing: bool = False, kind: str = listfile.HOSTS
    ) -> "OpenList":
        return cls.save_as(path, starter_list(), replace_existing=replace_existing, kind=kind)

    @classmethod
    def save_as(
        cls,
        path: Path,
        hosts: HostList,
        *,
        replace_existing: bool = False,
        kind: str = listfile.HOSTS,
    ) -> "OpenList":
        expected = listfile.stamp_of(path) if replace_existing else None
        stamp = listfile.save(path, hosts, expected=expected, kind=kind)
        return cls(path, hosts, stamp, read_only=False, kind=kind)

    def commit(self, new: HostList) -> None:
        if self.read_only:
            raise ReadOnlyListError(_("This list is read-only."))
        self.stamp = listfile.save(self.path, new, expected=self.stamp, kind=self.kind)
        self.hosts = new

    def reload(self) -> None:
        loaded = listfile.load(self.path, self.kind)
        self.hosts, self.stamp = loaded.hosts, loaded.stamp
