"""Connecting: the password prompt, manual connection, and starting the remote tool."""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect
from capypanel.core.tools.catalog import Catalog, Entry
from capypanel.core.tools.connect import Credential, SessionCredentials, Target, launch
from capypanel.core.tools.definitions import ToolDefinition

log = logging.getLogger(__name__)
VNC_TOOL_KEY = "vnc_tool"
DEFAULT_VNC_TOOL = "ultravnc"
MANY_CONNECTIONS = 5  # more than this at once asks first


class CredentialDialog(QDialog):
    def __init__(self, parent: QWidget | None, tool: ToolDefinition, target: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Password for {tool}").format(tool=tool.name))
        intro = QLabel(_("Connecting to {target}.").format(target=target))
        self.user = QLineEdit()
        self.user.setPlaceholderText(_("Only if the server asks for a Windows account"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        if tool.wants_user:
            form.addRow(_("&User:"), self.user)
        form.addRow(_("&Password:"), self.password)
        note = QLabel(
            _(
                "Kept in memory until CapyPanel closes, never saved. It's passed to the viewer "
                "on its command line, which administrators of this PC can see."
            )
        )
        note.setObjectName("hint")
        note.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.buttons)
        self.password.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(420, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.password.text()))

    def credential(self) -> Credential:
        return Credential(self.user.text().strip(), self.password.text())


class ManualConnectDialog(QDialog):
    """Connect to an address typed on the spot, without adding it to the list."""

    def __init__(self, parent: QWidget | None, default_port: int | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Manual connection"))
        self.address = QLineEdit()
        self.address.setPlaceholderText(_("Hostname or IP address"))
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        # A port is typed, not clicked up one by one; arrow keys and the wheel still work.
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.port.setValue(default_port or 5900)
        form = QFormLayout()
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("P&ort:"), self.port)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("&Connect"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.address.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(380, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.address.text().strip()))

    def target(self) -> Target:
        return Target(self.address.text().strip(), self.port.value())


class Connector:
    """Starts the VNC tool for one or more targets, asking for what's missing on the way."""

    def __init__(
        self,
        parent: QWidget,
        catalog: Catalog,
        credentials: SessionCredentials,
        prefs: dict[str, Any],
    ) -> None:
        self._parent = parent
        self.catalog = catalog
        self.credentials = credentials
        self._prefs = prefs

    def vnc_tool(self) -> Entry | None:
        wanted = self._prefs.get(VNC_TOOL_KEY, DEFAULT_VNC_TOOL)
        entry = self.catalog.find(wanted) if isinstance(wanted, str) else None
        if entry is None or entry.tool.kind != "vnc":
            available = self.catalog.of_kind("vnc")
            entry = available[0] if available else None
        return entry

    def connect(self, targets: list[tuple[str, Target]]) -> int:
        """(label, target) pairs; returns how many connections were started."""
        entry = self.vnc_tool()
        if entry is None:
            self._error(_("No VNC tool is set up."))
            return 0
        if len(targets) > MANY_CONNECTIONS and not self._confirm_many(len(targets)):
            return 0
        tool = entry.tool
        executable = detect.find_executable(tool) or self._locate(tool)
        if executable is None:
            return 0
        credential = None
        if tool.credentials != "none":
            credential = self.credentials.get(tool.id)
            if credential is None:
                label = targets[0][0] if len(targets) == 1 else _("the selected hosts")
                dialog = CredentialDialog(self._parent, tool, label)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return 0
                credential = dialog.credential()
                self.credentials.remember(tool.id, credential)
        started = 0
        for label, target in targets:
            try:
                launch(tool, executable, target, credential)
                started += 1
            except OSError as e:
                log.warning("Couldn't start %s for %s: %s", tool.id, label, e)
                self._error(
                    _("Couldn't start {tool} for {target}: {error}").format(
                        tool=tool.name, target=label, error=e
                    )
                )
                break
        return started

    def _locate(self, tool: ToolDefinition) -> Path | None:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("{tool} not found").format(tool=tool.name),
            _(
                "{tool} wasn't found on this PC. Install it, or show CapyPanel where it is. "
                "The path is saved for your account."
            ).format(tool=tool.name),
            parent=self._parent,
        )
        locate = box.addButton(_("&Locate…"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(locate)
        box.exec()
        if box.clickedButton() is not locate:
            return None
        name, _filter = QFileDialog.getOpenFileName(
            self._parent,
            _("Where is {tool}?").format(tool=tool.name),
            str(Path.home()),
            _("Programs (*.exe)"),
        )
        if not name:
            return None
        self.catalog.save_user_copy(replace(tool, executable=name))
        log.info("%s set to %s", tool.id, name)
        return Path(name)

    def _confirm_many(self, count: int) -> bool:
        answer = QMessageBox.question(
            self._parent,
            _("Many connections"),
            ngettext(
                "Open {n} remote screen at once?", "Open {n} remote screens at once?", count
            ).format(n=count),
        )
        return answer == QMessageBox.StandardButton.Yes

    def _error(self, message: str) -> None:
        QMessageBox.warning(self._parent, "CapyPanel", message)
