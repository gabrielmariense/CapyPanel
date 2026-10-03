"""Connecting: the password prompt, manual connection, and starting the right tool for each
host's connection profile."""

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
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

from capypanel.core.hosts.model import Group
from capypanel.core.i18n import _, ngettext
from capypanel.core.tools import detect, profiles, rfb
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.connect import Credential, SessionCredentials, Target, launch
from capypanel.core.tools.definitions import ToolDefinition
from capypanel.core.tools.profiles import ConnectionProfile, ProfileError

log = logging.getLogger(__name__)
MANY_CONNECTIONS = 5  # more than this at once asks first
MAX_TEXT = 256  # longest user name or password accepted, unless the tool allows less
DEFAULT_PORT = 5900
MAX_ADDRESS = 253  # the longest DNS name


@dataclass(frozen=True)
class Request:
    label: str  # how the host is named in messages
    target: Target
    profile: str = ""  # "" = the default profile


@dataclass(frozen=True)
class Ready:
    profile: ConnectionProfile
    tool: ToolDefinition


class CredentialDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, ready: Ready, target: str, *, on_command_line: bool
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Password for {profile}").format(profile=ready.profile.name))
        intro = QLabel(_("Connecting to {target}.").format(target=target))
        intro.setWordWrap(True)
        self.wants_user = ready.profile.login == "account"
        self.user = QLineEdit()
        self.user.setMaxLength(MAX_TEXT)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        # Classic VNC passwords stop at 8 characters: the box does too, so nothing is cut silently.
        self.password.setMaxLength(ready.tool.max_password.get(ready.profile.login, MAX_TEXT))
        form = QFormLayout()
        if self.wants_user:
            form.addRow(_("&User:"), self.user)
        form.addRow(_("&Password:"), self.password)
        remembered = _(
            "Kept in memory until CapyPanel closes, never saved, and used only for hosts with "
            "this connection profile."
        )
        how = (
            _("It's passed to the viewer on its command line, which administrators of this PC "
              "can see.")
            if on_command_line
            else _("It's handed to the viewer privately, never on its command line.")
        )  # fmt: skip
        note = QLabel(f"{remembered} {how}")
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
        self.user.textChanged.connect(self._update_ok)
        self.password.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(440, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        has_user = bool(self.user.text().strip()) or not self.wants_user
        ok.setEnabled(has_user and bool(self.password.text()))

    def credential(self) -> Credential:
        user = self.user.text().strip() if self.wants_user else ""
        return Credential(user, self.password.text())


class ManualConnectDialog(QDialog):
    """Connect to an address typed on the spot, without adding it to the list."""

    def __init__(
        self, parent: QWidget | None, choices: list[tuple[str, str]], default_profile: str
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Manual connection"))
        self.address = QLineEdit()
        self.address.setPlaceholderText(_("Hostname or IP address"))
        self.address.setMaxLength(MAX_ADDRESS)
        self.port = QSpinBox()
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText(_("Default"))  # shown for 0: the profile's own port
        # A port is typed, not clicked up one by one; arrow keys and the wheel still work.
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.profile = QComboBox()
        for profile_id, text in choices:
            self.profile.addItem(text, profile_id)
        self.profile.setCurrentIndex(max(self.profile.findData(default_profile), 0))
        form = QFormLayout()
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("P&ort:"), self.port)
        form.addRow(_("Connection &profile:"), self.profile)
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
        self.resize(460, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.address.text().strip()) and self.profile.count() > 0)

    def request(self) -> Request:
        address = self.address.text().strip()
        port = self.port.value() or None
        return Request(address, Target(address, port), self.profile.currentData() or "")


class Connector:
    """Starts the right tool for each host's connection profile, asking for what's missing."""

    def __init__(
        self,
        parent: QWidget,
        catalogs: Catalogs,
        credentials: SessionCredentials,
        prefs: dict[str, Any],
    ) -> None:
        self._parent = parent
        self.catalogs = catalogs
        self.credentials = credentials
        self._prefs = prefs
        self.open_settings: Callable[[], None] | None = None  # Settings > Connections

    # ---- profiles ----

    def default_profile(self) -> str:
        return self.catalogs.profiles.default_id()

    def label(self, profile_id: str) -> str:
        """The profile's name; for an id this PC doesn't have, the id and a note saying so."""
        profile = self.catalogs.profiles.find(profile_id or self.default_profile())
        if profile is None:
            return _("{profile} (not available on this PC)").format(profile=profile_id)
        return profile.name

    def choices(self) -> list[tuple[str, str]]:
        """(id, name) of every profile whose tool CapyPanel knows, by name."""
        return [
            (p.id, p.name)
            for p in self.catalogs.profiles.all()
            if self.catalogs.tools.find(p.tool) is not None
        ]

    def inherited_label(self, profile_id: str, source: Group | None) -> str:
        """What "follow the group" means right now, e.g. "From group “Pis”: RealVNC …"."""
        if source is not None:
            return _("From group “{group}”: {profile}").format(
                group=source.name, profile=self.label(profile_id)
            )
        return _("Default: {profile}").format(profile=self.label(self.default_profile()))

    def resolve(self, profile_id: str) -> Ready:
        """The profile and its tool, or ProfileError saying why it can't be used here."""
        profile_id = profile_id or self.default_profile()
        if not profile_id:
            raise ProfileError(
                _("There are no connection profiles. Create one in Settings > Connections.")
            )
        profile = self.catalogs.profiles.find(profile_id)
        if profile is None:
            raise ProfileError(
                _("The connection profile “{profile}” isn't available on this PC.").format(
                    profile=profile_id
                )
            )
        tool = self.catalogs.tools.find(profile.tool)
        if tool is None:
            raise ProfileError(
                _("The connection profile “{profile}” needs the tool “{tool}”, which isn't "
                  "available on this PC.").format(profile=profile.name, tool=profile.tool)
            )  # fmt: skip
        profiles.check_fits(profile, tool.item)
        return Ready(profile, tool.item)

    # ---- connecting ----

    def connect(self, requests: list[Request]) -> int:
        """Returns how many connections were started."""
        if len(requests) > MANY_CONNECTIONS and not self._confirm_many(len(requests)):
            return 0
        by_profile: dict[str, list[Request]] = {}
        for request in requests:
            by_profile.setdefault(request.profile or self.default_profile(), []).append(request)
        started = 0
        for profile_id, group in by_profile.items():
            started += self._connect_profile(profile_id, group)
        return started

    def _connect_profile(self, profile_id: str, requests: list[Request]) -> int:
        try:
            ready = self.resolve(profile_id)
        except ProfileError as e:
            self._error(f"{e}\n\n{self._names(requests)}")
            return 0
        tool, profile = ready.tool, ready.profile
        executable = detect.find_executable(tool) or self._locate(tool)
        if executable is None:
            return 0
        if profile.login == "account" and tool.account_types:
            requests = self._only_account_servers(ready, requests)
            if not requests:
                return 0
        credential = None
        if profile.login != "none":
            credential = self.credentials.get(profile.id)
            if credential is None:
                label = requests[0].label if len(requests) == 1 else _("the selected hosts")
                dialog = CredentialDialog(
                    self._parent, ready, label, on_command_line=tool.credentials == "arguments"
                )
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return 0
                credential = dialog.credential()
                self.credentials.remember(profile.id, credential)
        started = 0
        for request in requests:
            target = request.target
            if target.port is None and profile.port is not None:
                target = replace(target, port=profile.port)
            try:
                launch(tool, executable, target, credential, profile.options)
                started += 1
            except OSError as e:
                log.warning("Couldn't start %s for %s: %s", tool.id, request.label, e)
                self._error(
                    _("Couldn't start {tool} for {target}: {error}").format(
                        tool=tool.name, target=request.label, error=e
                    )
                )
                break
        return started

    def _only_account_servers(self, ready: Ready, requests: list[Request]) -> list[Request]:
        """Drops the hosts whose server offers no user-and-password login (e.g. it only wants a
        VNC password, which would get the first 8 characters through a login cracked offline)."""
        tool, profile = ready.tool, ready.profile

        def offers_account(request: Request) -> bool:
            port = request.target.port or profile.port or tool.port or DEFAULT_PORT
            began = time.perf_counter()
            try:
                offered = rfb.security_types(request.target.address, port)
            except rfb.ProbeError as e:
                log.info("Login check for %s: couldn't ask (%s); opening anyway", request.label, e)
                return True  # can't tell: the viewer will say what's wrong
            fits = any(t in tool.account_types for t in offered)
            log.info(
                "Login check for %s: login types %s in %d ms, %s",
                request.label, list(offered), (time.perf_counter() - began) * 1000,
                "fits" if fits else "refused",
            )  # fmt: skip
            return fits

        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                fits = list(pool.map(offers_account, requests))
        finally:
            QGuiApplication.restoreOverrideCursor()
        refused = [r for r, ok in zip(requests, fits, strict=True) if not ok]
        if refused:
            self._error(
                ngettext(
                    "{names} doesn't take a user and password (it may want a VNC password, or be "
                    "another kind of VNC server), so CapyPanel didn't send your password. Check "
                    "its connection profile.",
                    "{names} don't take a user and password (they may want a VNC password, or be "
                    "another kind of VNC server), so CapyPanel didn't send your password. Check "
                    "their connection profile.",
                    len(refused),
                ).format(names=", ".join(r.label for r in refused))
            )
        return [r for r, ok in zip(requests, fits, strict=True) if ok]

    def _names(self, requests: list[Request]) -> str:
        names = ", ".join(r.label for r in requests[:5])
        if len(requests) > 5:
            names += " …"
        return ngettext("Not opened: {names}", "Not opened ({n}): {names}", len(requests)).format(
            n=len(requests), names=names
        )

    def _locate(self, tool: ToolDefinition) -> Path | None:
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            _("{tool} not found").format(tool=tool.name),
            _(
                "{tool} wasn't found on this PC. Install it, or show CapyPanel where it is. "
                "The path is saved for your account; you can also change it later in "
                "Settings > Connections."
            ).format(tool=tool.name),
            parent=self._parent,
        )
        locate = box.addButton(_("&Locate…"), QMessageBox.ButtonRole.AcceptRole)
        settings = None
        if self.open_settings is not None:
            settings = box.addButton(_("Open &Settings"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(locate)
        box.exec()
        if settings is not None and box.clickedButton() is settings and self.open_settings:
            self.open_settings()
            return None
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
        self.catalogs.tools.save_user_copy(replace(tool, executable=name))
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
