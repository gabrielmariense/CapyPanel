"""Dialogs for hosts and groups: add/edit host, and confirming removals."""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import Host, HostList, clean_tags
from capypanel.core.i18n import _


@dataclass(frozen=True)
class HostValues:
    name: str
    address: str
    group: str
    tags: tuple[str, ...]
    notes: str


def list_file_filter() -> str:
    """The file-type filter for choosing host list files in file dialogs."""
    return _("Host lists (*.json);;All files (*)")


def group_choices(host_list: HostList) -> list[tuple[str, str]]:
    """(id, label) for every group, depth-first, indented to show nesting."""
    choices: list[tuple[str, str]] = []

    def visit(parent: str | None, depth: int) -> None:
        for group in sorted(host_list.children(parent), key=lambda g: g.name.casefold()):
            choices.append((group.id, "    " * depth + group.name))
            visit(group.id, depth + 1)

    visit(None, 0)
    return choices


class HostDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        host_list: HostList,
        host: Host | None = None,
        default_group: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Edit host") if host else _("Add host"))
        self.name = QLineEdit(host.name if host else "")
        self.address = QLineEdit(host.address if host else "")
        self.address.setPlaceholderText(_("Hostname or IP address; leave blank to use the name"))
        self.group = QComboBox()
        for group_id, label in group_choices(host_list):
            self.group.addItem(label, group_id)
        wanted = host.group if host else default_group
        index = self.group.findData(wanted) if wanted else -1
        self.group.setCurrentIndex(max(index, 0))
        self.tags = QLineEdit(", ".join(host.tags) if host else "")
        self.tags.setPlaceholderText(_("Separate tags with commas"))
        self.notes = QPlainTextEdit(host.notes if host else "")
        self.notes.setTabChangesFocus(True)

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("&Group:"), self.group)
        form.addRow(_("&Tags:"), self.tags)
        form.addRow(_("N&otes:"), self.notes)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.name.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(420, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.name.text().strip()) and self.group.count() > 0)

    def values(self) -> HostValues:
        return HostValues(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            group=self.group.currentData(),
            tags=clean_tags(self.tags.text().split(",")),
            notes=self.notes.toPlainText().strip(),
        )


def confirm(parent: QWidget, title: str, text: str, action: str) -> bool:
    """A yes/no question whose default is Cancel, so Enter or a stray click never confirms."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    yes = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is yes
