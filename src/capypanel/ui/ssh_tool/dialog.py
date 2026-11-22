"""An SSH host's dialog: port and Log in as never take a space or a leading "-" (an option)."""

from dataclasses import dataclass

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import MAX_ADDRESS, NO_GROUP, Host, HostList
from capypanel.core.i18n import _
from capypanel.core.ssh.host import (
    MAX_LOGIN,
    MAX_PORT,
    REFUSED_IN_LOGIN,
    SshInfo,
    group_login_of,
    info_of,
)
from capypanel.core.ssh.launch import REFUSED_IN_ADDRESS
from capypanel.ui import help_links
from capypanel.ui.dialogs import ok_cancel
from capypanel.ui.hosts import MAX_NAME, TagEdit, group_choices


@dataclass(frozen=True)
class SshValues:
    name: str
    address: str
    group: str
    tags: tuple[str, ...]
    notes: str
    info: SshInfo


class SshHostDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        hosts: HostList,
        host: Host | None = None,
        default_group: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Edit host") if host else _("Add host"))
        info = info_of(host) if host else SshInfo()
        self._extra = info.extra  # values this version can't read, kept as they are
        self._hosts = hosts

        self.name = QLineEdit(host.name if host else "")
        self.name.setMaxLength(MAX_NAME)
        self.address = QLineEdit(host.address if host else "")
        self.address.setMaxLength(MAX_ADDRESS)
        self.address.setPlaceholderText(_("IP address or network name"))
        self.address.setValidator(_as_ssh_takes(self.address, REFUSED_IN_ADDRESS))
        self.group = QComboBox()
        for group_id, label in group_choices(hosts):
            self.group.addItem(label, group_id)
        wanted = host.group if host else (default_group or NO_GROUP)
        self.group.setCurrentIndex(max(self.group.findData(wanted), 0))
        self.tags = TagEdit(known=hosts.all_tags())
        self.tags.set_tags(host.tags if host else ())
        self.port = QSpinBox()
        self.port.setRange(1, MAX_PORT)
        self.port.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.port.setValue(info.port)
        self.login = QLineEdit(info.login)
        self.login.setMaxLength(MAX_LOGIN)
        self.login.setValidator(_as_ssh_takes(self.login, REFUSED_IN_LOGIN))
        self.notes = QPlainTextEdit(host.notes if host else "")
        self.notes.setTabChangesFocus(True)

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("&Group:"), self.group)
        tags_label = QLabel(_("&Tags:"))
        tags_label.setBuddy(self.tags.input)  # Alt+T goes to the text box inside the field
        form.addRow(tags_label, self.tags)
        form.addRow(_("&Port:"), self.port)
        form.addRow(_("&Log in as:"), self.login)
        form.addRow(_("N&otes:"), self.notes)
        self.buttons = ok_cancel(self, _("Save") if host else _("Add"))  # ends in its verb
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        self.help_button = help_links.HelpButton("ssh-add-a-host")
        layout.addLayout(help_links.row(self.help_button, self.buttons))
        self.name.textChanged.connect(self._update_ok)
        self.group.currentIndexChanged.connect(self._update_login_hint)
        self._update_ok()
        self._update_login_hint()
        self.resize(460, self.sizeHint().height())

    def _update_login_hint(self) -> None:
        """Left empty, it takes the picked group's name: the hint says which."""
        group = self.group.currentData()
        login, source = group_login_of(self._hosts, group if isinstance(group, str) else None)
        self.login.setPlaceholderText(empty_text(login, source.name if source else ""))

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.name.text().strip()) and self.group.count() > 0)

    def values(self) -> SshValues:
        """An odd value the file had stays as found unless a new one is typed (with_info)."""
        info = SshInfo(self.port.value(), self.login.text().strip(), self._extra)
        return SshValues(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            group=str(self.group.currentData()),
            tags=self.tags.tags(),
            notes=self.notes.toPlainText().strip(),
            info=info,
        )


def follow_text(login: str, group: str) -> str:
    """Log in as menus' first choice: the name the group gives (`login`, from `group`), or none,
    which leaves it to ssh.exe."""
    if login:
        return _("From group “{group}”: {profile}").format(group=group, profile=login)
    return _("None: your SSH config, then your Windows user name")


def empty_text(login: str, group: str) -> str:
    """What a Log in as left empty gives, as its box's hint: the group's name, or ssh.exe's."""
    if login:
        return follow_text(login, group)
    return _("Empty: your SSH config, then your Windows user name")


class LoginDialog(QDialog):
    """Another name… under Log in as: one name, taken as the host window takes it. `about` says
    whom it is for; `empty` what leaving it empty gives (empty_text): their group's again."""

    def __init__(self, parent: QWidget | None, about: str, login: str, empty: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Log in as"))
        self.login = QLineEdit(login)
        self.login.setMaxLength(MAX_LOGIN)
        self.login.setPlaceholderText(empty)
        self.login.setValidator(_as_ssh_takes(self.login, REFUSED_IN_LOGIN))
        self.about = QLabel(about)
        self.about.setWordWrap(True)
        form = QFormLayout()
        form.addRow(_("&Log in as:"), self.login)
        self.buttons = ok_cancel(self, _("Save"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.about)
        layout.addLayout(form)
        self.help_button = help_links.HelpButton("ssh-choose-the-name-to-log-in-as")
        layout.addLayout(help_links.row(self.help_button, self.buttons))
        self.resize(420, self.sizeHint().height())

    def value(self) -> str:
        return self.login.text().strip()


def _as_ssh_takes(field: QLineEdit, refused: frozenset[str]) -> QRegularExpressionValidator:
    """No spaces, no "-" first and none of `refused`: a key that would make one does nothing."""
    bad = "".join("\\" + c for c in sorted(refused))  # each one escaped, inside a class
    pattern = QRegularExpression(rf"[^\s{bad}-][^\s{bad}]*")
    return QRegularExpressionValidator(pattern, field)
