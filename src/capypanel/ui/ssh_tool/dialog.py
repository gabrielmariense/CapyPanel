"""Adding and editing an SSH host: what the host dialog asks (name, address, group, tags, notes),
plus its port and the name to log in as. Neither field takes a space or a leading "-", which
ssh.exe would read as an option. No password: ssh.exe asks for it, or uses a key."""

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
from capypanel.core.ssh.host import MAX_LOGIN, MAX_PORT, SshInfo, info_of
from capypanel.ui.dialogs import ok_cancel
from capypanel.ui.hosts import MAX_NAME, TagEdit, group_choices

NO_OPTION = r"[^\s-]\S*"  # no spaces, and no "-" first: what ssh.exe takes as an address or name


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

        self.name = QLineEdit(host.name if host else "")
        self.name.setMaxLength(MAX_NAME)
        self.address = QLineEdit(host.address if host else "")
        self.address.setMaxLength(MAX_ADDRESS)
        self.address.setPlaceholderText(_("IP address or network name"))
        self.address.setValidator(_no_option(self.address))
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
        self.login.setPlaceholderText(_("Empty: your SSH config, then your Windows user name"))
        self.login.setValidator(_no_option(self.login))
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
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(460, self.sizeHint().height())

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


def _no_option(field: QLineEdit) -> QRegularExpressionValidator:
    return QRegularExpressionValidator(QRegularExpression(NO_OPTION), field)
