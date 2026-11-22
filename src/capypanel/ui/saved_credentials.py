import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QPushButton,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import credstore
from capypanel.core.i18n import _, ngettext
from capypanel.ui import help_links, spacing
from capypanel.ui.dialogs import quiet_default
from capypanel.ui.hosts import confirm
from capypanel.ui.notes import notes
from capypanel.ui.tables import fit_rows, grid_table, with_buttons

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeptLogin:
    used_for: str
    tool: str
    user: str
    saved: bool
    forget: Callable[[], object]


def kept_text(logins: list[KeptLogin]) -> str:
    if not logins:
        return _("None kept.")
    saved = sum(login.saved for login in logins)
    places = []
    if saved:
        places.append(_("{n} in Credential Manager").format(n=saved))
    if len(logins) > saved:
        n = len(logins) - saved
        places.append(ngettext("{n} temporary", "{n} temporary", n).format(n=n))
    return ngettext("{n} kept: {places}.", "{n} kept: {places}.", len(logins)).format(
        n=len(logins), places=", ".join(places)
    )


def forget_failed(parent: QWidget, error: OSError) -> None:
    log.warning("Couldn't delete a saved password: %s", error)
    help_links.warning(
        parent,
        "CapyPanel",
        _("Couldn't delete the password saved in Windows Credential Manager: {error}\n\n"
          "You can delete it in Control Panel › Credential Manager › Windows "
          "Credentials, under “{prefix}”.").format(error=error, prefix=credstore.PREFIX),
        place="connect-password-not-deleted",
    )  # fmt: skip


def forget_details(logins: list[KeptLogin]) -> str:
    parts = []
    for heading, saved in (
        (_("Saved in Credential Manager:"), True),
        (_("Temporary:"), False),
    ):
        lines = [f"• {login.used_for} · {login.user}" for login in logins if login.saved == saved]
        if lines:
            parts.append("\n".join([heading, *lines]))
    return "\n\n".join([*parts, _("CapyPanel asks for them again when it needs them.")])


class SavedCredentialsDialog(QDialog):
    def __init__(self, parent: QWidget | None, kept: Callable[[], list[KeptLogin]]) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Saved credentials"))
        self._kept = kept
        self._logins: list[KeptLogin] = []
        column = QVBoxLayout(self)
        column.setContentsMargins(spacing.WINDOW, spacing.WINDOW, spacing.WINDOW, spacing.WINDOW)
        column.setSpacing(spacing.CONTROLS)
        column.addWidget(
            notes(_("Every login CapyPanel keeps for you. Passwords never show here."))
        )
        self.table = grid_table([_("Used for"), _("Tool"), _("User"), _("Kept")])
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.forget_button = QPushButton(_("&Forget"))
        self.forget_all_button = QPushButton(_("Forget &all"))
        self.forget_button.clicked.connect(self.forget)
        self.forget_all_button.clicked.connect(self.forget_all)
        column.addWidget(with_buttons(self.table, [self.forget_button, self.forget_all_button]))
        column.addWidget(
            notes(
                _(
                    "Forgotten logins are deleted from Credential Manager too; you type them "
                    "again the next time. A new one is saved only when you tick Remember it on "
                    "this computer as you type it."
                )
            )
        )
        self.help_button = help_links.HelpButton("connecting-forget-a-saved-password")
        buttons = QHBoxLayout()
        buttons.addWidget(self.help_button)
        buttons.addStretch(1)
        close = QPushButton(_("Close"))
        quiet_default(close)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        column.addLayout(buttons)
        self._fill(0)
        self.resize(720, self.sizeHint().height())

    def _fill(self, row: int) -> None:
        self._logins = sorted(self._kept(), key=lambda login: login.used_for.casefold())
        self.table.clear()
        for login in self._logins:
            place = _("Credential Manager") if login.saved else _("Temporary")
            item = QTreeWidgetItem([login.used_for, login.tool, login.user, place])
            for index in range(4):
                item.setToolTip(index, item.text(index))
            self.table.addTopLevelItem(item)
        fit_rows(self.table)
        for index, width in enumerate((160, 150, 170)):
            self.table.setColumnWidth(index, max(self.table.columnWidth(index), width))
        picked = self.table.topLevelItem(min(row, len(self._logins) - 1))
        if picked is not None:
            self.table.setCurrentItem(picked)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.forget_button.setEnabled(bool(self.table.selectedItems()))
        self.forget_all_button.setEnabled(bool(self._logins))

    def forget(self) -> None:
        item = self.table.currentItem()
        if item is None or not item.isSelected():
            return
        row = self.table.indexOfTopLevelItem(item)
        self._run([self._logins[row]])
        self._fill(row)

    def forget_all(self) -> None:
        n = len(self._logins)
        if n and confirm(
            self,
            _("Saved credentials"),
            ngettext("Forget this login?", "Forget these {n} logins?", n).format(n=n),
            ngettext("&Forget {n} login", "&Forget {n} logins", n).format(n=n),
            forget_details(self._logins),
        ):
            self._run(self._logins)
            self._fill(0)

    def _run(self, logins: list[KeptLogin]) -> None:
        failed: OSError | None = None
        for login in logins:
            try:
                login.forget()
            except OSError as e:
                failed = failed or e
        if failed is not None:
            forget_failed(self, failed)
