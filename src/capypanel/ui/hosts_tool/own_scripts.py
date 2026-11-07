"""Your own scripts for the Hosts tool: the scripts folder chosen in Settings, what was found in
it and their approvals, kept in this user's settings. The folder is read in the background, when
CapyPanel opens and on Rescan, since it's often a share on a server."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from capypanel.core.remote import own_scripts
from capypanel.core.remote.own_scripts import Approval, OwnScript

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.tool import HostsTool

FOLDER_KEY = "scripts_folder"
APPROVALS_KEY = "script_approvals"


class OwnScripts(QObject):
    changed = Signal()  # a scan started or ended, or an approval changed

    def __init__(self, tool: "HostsTool") -> None:
        super().__init__(tool)
        self._tool = tool
        self.scripts: list[OwnScript] = []
        self.scanning = False
        self.error: OSError | None = None  # why the folder couldn't be read
        self._again = False  # scan once more when this one ends: the folder changed meanwhile

    def folder(self) -> Path | None:
        saved = self._tool.prefs.get(FOLDER_KEY)
        return Path(saved) if isinstance(saved, str) and saved else None

    def set_folder(self, folder: Path | None) -> None:
        if folder == self.folder():
            return
        self._tool.prefs[FOLDER_KEY] = str(folder) if folder else ""
        self._tool.save_prefs()
        self.scripts = []
        self.rescan()

    def approvals(self) -> dict[str, Approval]:
        return own_scripts.approvals_from(self._tool.prefs.get(APPROVALS_KEY))

    def find(self, script_id: str) -> OwnScript | None:
        return next((s for s in self.scripts if s.id == script_id), None)

    def rescan(self) -> None:
        folder = self.folder()
        if folder is None:
            self.scripts, self.error = [], None
            self.changed.emit()
            return
        if self.scanning:
            self._again = True
            return
        self.scanning = True
        self.changed.emit()
        approvals = self.approvals()

        def done(found: list[OwnScript]) -> None:
            self._ended(found, None, folder)

        def failed(error: BaseException) -> None:
            self._ended([], error if isinstance(error, OSError) else OSError(str(error)), folder)

        self._tool.runner.call(lambda _account: own_scripts.scan(folder, approvals), done, failed)

    def _ended(self, found: list[OwnScript], error: OSError | None, folder: Path) -> None:
        self.scanning = False
        if self._again or folder != self.folder():
            self._again = False
            self.rescan()
            return
        self.scripts, self.error = found, error
        self.changed.emit()

    def approve(self, script: OwnScript, approval: Approval) -> None:
        """Keeps the approval, then reads the folder again: the file may have changed since."""
        approvals = self.approvals()
        approvals[script.file.name.casefold()] = approval
        self._tool.prefs[APPROVALS_KEY] = own_scripts.approvals_to(approvals)
        self._tool.save_prefs()
        self.rescan()
