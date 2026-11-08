"""Which account signs in to which PCs: the links (core.hosts.accounts) in the person's own
settings, the passwords typed for them, and their table in Settings › Hosts › Connecting.

A password is kept in memory once typed, and in Windows Credential Manager when "Remember it on
this computer" is ticked; a link whose password isn't known yet asks for it the first time it's
needed, once per session."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import credstore
from capypanel.core.hosts import accounts
from capypanel.core.hosts.accounts import Link, Place, Scope
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.i18n import _
from capypanel.core.remote.access import Account
from capypanel.ui.checks import AccountDialog
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts import group_path
from capypanel.ui.notes import notes
from capypanel.ui.saved_credentials import KeptLogin
from capypanel.ui.settings.pages import Section
from capypanel.ui.tables import add_action, fit_rows, grid_table, row_menu, with_buttons

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.runner import HostTarget
    from capypanel.ui.hosts_tool.tool import HostsTool

log = logging.getLogger(__name__)
PREFS_KEY = "accounts"
OLD_SAVED = "account/logged-on-users"  # 0.23's one account for every PC, in Credential Manager


def group_chain(host_list: HostList, group_id: str) -> tuple[str, ...]:
    """The group's id, then each parent's."""
    chain: list[str] = []
    group = host_list.group(group_id) if group_id != NO_GROUP else None
    while group is not None and group.id not in chain:
        chain.append(group.id)
        group = host_list.group(group.parent) if group.parent else None
    return tuple(chain)


def _same_list(link: Link, doc: OpenList | None) -> bool:
    return doc is not None and accounts.same_file(link.list, str(doc.path))


def used_for(link: Link, doc: OpenList | None) -> str:
    """What the Used for column says: "Every PC", "DESK-02", "Group Clinic › Front desk"."""
    if link.scope is Scope.ALL:
        return _("Every PC")
    if link.scope is Scope.PC:
        name = link.name
        return f"{name} ({link.value})" if name and name.casefold() != link.value.casefold() \
            else link.value  # fmt: skip
    here = _same_list(link, doc)
    if link.scope is Scope.GROUP:
        name = link.name
        if here and doc is not None and doc.hosts.group(link.value) is not None:
            name = group_path(doc.hosts, link.value)
        text = _("Group {group}").format(group=name or link.value)
    else:
        text = _("Tag {tag}").format(tag=link.value)
    return text if here else _("{what}, in {list}").format(what=text, list=Path(link.list).name)


class Accounts(QObject):
    """The links and their passwords, for the Hosts tool, its commands and Settings."""

    changed = Signal()

    def __init__(self, tool: "HostsTool") -> None:
        super().__init__(tool)
        self._tool = tool
        self.links: list[Link] = accounts.load(tool.prefs.get(PREFS_KEY))
        self._typed: dict[str, tuple[Account, bool]] = {}  # by user, folded: (account, saved)
        if PREFS_KEY not in tool.prefs:
            self._adopt_old()

    def _adopt_old(self) -> None:
        """0.23 kept one account for every PC: it becomes a link for every PC."""
        try:
            found = credstore.read(OLD_SAVED)
        except OSError as e:
            log.warning("Couldn't read the account saved by an older CapyPanel: %s", e)
            return
        if found is None:
            return
        account = Account(*found)
        self.use(Link(account.user, Scope.ALL), account, remember=True)
        try:
            credstore.forget(OLD_SAVED)
        except OSError as e:
            log.warning("Couldn't delete the old saved account: %s", e)

    def _store(self, links: list[Link]) -> None:
        self.links = links
        self._tool.keep_pref(PREFS_KEY, accounts.dump(links))
        self.changed.emit()

    # ---- which account a PC gets ----

    def place(self, target: "HostTarget") -> Place:
        doc = self.document()
        host = doc.hosts.host(target.key) if doc is not None else None
        if doc is None or host is None:  # an address typed in the Commands window
            return Place(target.address)
        return Place(target.address, str(doc.path), group_chain(doc.hosts, host.group), host.tags)

    def link_for(self, target: "HostTarget") -> Link | None:
        return accounts.pick(self.links, self.place(target))

    def known(self, user: str) -> Account | None:
        """Its password, typed this session or remembered by Windows; None until typed."""
        kept = self._typed.get(user.casefold())
        if kept is not None:
            return kept[0]
        try:
            found = credstore.read(accounts.credential_name(user))
        except OSError as e:
            log.warning("Couldn't read a saved account: %s", e)
            return None
        if found is None:
            return None
        account = Account(user, found[1])
        self._typed[user.casefold()] = (account, True)
        return account

    def saved(self, user: str) -> bool:
        return self.known(user) is not None and self._typed[user.casefold()][1]

    def kept_in(self, user: str) -> str:
        if self.known(user) is None:
            return _("Asked when needed")
        return _("Credential Manager") if self.saved(user) else _("Temporary")

    def account_for(
        self, target: "HostTarget", parent: QWidget | None
    ) -> tuple[bool, Account | None]:
        """(go on, the account; None is the Windows account). With no password typed yet for
        the PC's account, asks for it over `parent`; (False, None) when cancelled, or with no
        `parent` to ask over."""
        link = self.link_for(target)
        if link is None:
            return True, None
        known = self.known(link.user)
        if known is not None:
            return True, known
        if parent is None:
            return False, None
        text = _("Type the password of “{user}”. It signs in to {host} ({uses}).").format(
            user=link.user, host=target.name, uses=used_for(link, self.document())
        )
        dialog = AccountDialog(parent, text, link.user, saved=self.saving(), fixed_user=True)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return False, None
        account = dialog.account()
        self.keep(account, remember=dialog.remember.isChecked())
        return True, account

    def uses_for(self, targets: Sequence["HostTarget"]) -> list[tuple[str, Link]]:
        """What "Use it for" offers for these PCs, most specific first: this PC, each group
        they're all in, each tag they all have, every PC."""
        places = [self.place(t) for t in targets]
        found: list[tuple[str, Link]] = []
        if len(targets) == 1 and targets[0].address:
            target = targets[0]
            pc = Link("", Scope.PC, target.address, name=target.name)
            found.append((_("This PC ({name})").format(name=target.name), pc))
        doc = self.document()
        lists = {p.list for p in places}
        if doc is not None and len(lists) == 1 and "" not in lists:
            shared = [g for g in places[0].groups if all(g in p.groups for p in places)]
            for group_id in shared:
                name = group_path(doc.hosts, group_id)
                link = Link("", Scope.GROUP, group_id, str(doc.path), name)
                found.append((_("Every PC in group {group}").format(group=name), link))
            for tag in places[0].tags:
                if all(tag.casefold() in {t.casefold() for t in p.tags} for p in places):
                    link = Link("", Scope.TAG, tag, str(doc.path))
                    found.append((_("Every PC tagged {tag}").format(tag=tag), link))
        found.append((_("Every PC"), Link("", Scope.ALL)))
        return found

    # ---- changes ----

    def saving(self) -> bool:
        """Settings' Credentials: what "Remember it on this computer" starts as."""
        return self._tool.connector.credentials.saving

    def document(self) -> OpenList | None:
        return self._tool.document

    def keep(self, account: Account, *, remember: bool) -> None:
        """Its password from now on; in Credential Manager too when `remember`."""
        name = accounts.credential_name(account.user)
        saved = False
        try:
            if remember:
                credstore.save(name, account.password, user=account.user)
                saved = True
            else:
                credstore.forget(name)
        except (OSError, ValueError) as e:
            log.warning("Couldn't save or delete a saved account: %s", e)
            if remember:
                QMessageBox.warning(
                    self._tool,
                    "CapyPanel",
                    _("Couldn't save the password in Windows Credential Manager: {error}\n\n"
                      "It's kept until CapyPanel closes.").format(error=e),
                )  # fmt: skip
        self._typed[account.user.casefold()] = (account, saved)
        self.changed.emit()

    def use(self, link: Link, account: Account | None, *, remember: bool) -> None:
        """A link added (or replacing the one for the same PCs); its password, when typed."""
        self._store(accounts.with_link(self.links, link))
        if account is not None:
            self.keep(account, remember=remember)

    def replace_link(self, old: Link, new: Link) -> None:
        """An edited row: in the same place in the table."""
        links = [new if lk == old else lk for lk in self.links
                 if lk == old or not lk.same_place(new)]  # fmt: skip
        self._store(links if new in links else [*links, new])
        if not accounts.uses(self.links, old.user):
            self.forget(old.user)

    def remove(self, link: Link) -> None:
        """The link goes; its password too when no other link uses that account."""
        self._store([lk for lk in self.links if lk != link])
        if not accounts.uses(self.links, link.user):
            self.forget(link.user)

    def forget(self, user: str) -> None:
        """Its password, from memory and Credential Manager. Raises OSError."""
        self._typed.pop(user.casefold(), None)
        try:
            credstore.forget(accounts.credential_name(user))
        finally:
            self.changed.emit()

    def forget_saved(self) -> None:
        """Settings' Temporary credentials: every remembered password leaves Credential
        Manager; what was typed this session stays until CapyPanel closes. Raises OSError."""
        for user in accounts.users(self.links):
            credstore.forget(accounts.credential_name(user))
            kept = self._typed.get(user.casefold())
            if kept is not None:
                self._typed[user.casefold()] = (kept[0], False)
        credstore.forget(OLD_SAVED)
        self.changed.emit()

    def kept_logins(self) -> list[KeptLogin]:
        """For the Saved credentials window: each account whose password is kept."""
        logins = []
        for user in accounts.users(self.links):
            if self.known(user) is None:
                continue
            where = ", ".join(used_for(lk, self.document())
                              for lk in accounts.uses(self.links, user))  # fmt: skip
            logins.append(KeptLogin(where, _("Hosts › Accounts"), user, self.saved(user),
                                    lambda u=user: self.forget(u)))  # fmt: skip
        return logins


# ---- Settings › Hosts › Connecting › Accounts ----


class LinkDialog(QDialog):
    """Add or edit one row of the Accounts table: the account, its password (optional), the
    PCs it's for and whether Windows remembers it."""

    def __init__(
        self, parent: QWidget | None, title: str, manager: Accounts, link: Link | None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._manager = manager
        doc = self._doc = manager.document()
        self.user = QLineEdit(link.user if link else "")
        self.user.setMaxLength(accounts.MAX_TEXT)
        self.user.setPlaceholderText(_("DOMAIN\\user"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(accounts.MAX_TEXT)
        known = link is not None and manager.known(link.user) is not None
        self.password.setPlaceholderText(
            _("Unchanged") if known else _("Optional: asked the first time it's needed")
        )
        self.kind = QComboBox()
        for label, scope in ((_("Every PC"), Scope.ALL), (_("One PC"), Scope.PC),
                             (_("A group"), Scope.GROUP), (_("A tag"), Scope.TAG)):  # fmt: skip
            self.kind.addItem(label, scope)
        self.address = QLineEdit()
        self.address.setMaxLength(253)
        self.address.setPlaceholderText(_("Its address or name, as in the host list"))
        self.group = QComboBox()
        self.tag = QComboBox()
        self.tag.setEditable(True)
        if doc is not None:
            paths = sorted(((group_path(doc.hosts, g.id), g.id) for g in doc.hosts.groups),
                           key=lambda pair: pair[0].casefold())  # fmt: skip
            for path, group_id in paths:
                self.group.addItem(path, group_id)
            self.tag.addItems(sorted(doc.hosts.all_tags(), key=str.casefold))
        self.tag.setCurrentText("")
        empty = QWidget()
        self.value = QStackedWidget()
        for widget in (empty, self.address, self.group, self.tag):
            self.value.addWidget(widget)
        for index in (2, 3):  # a group or a tag belongs to the open list
            if doc is None:
                self.kind.model().item(index).setEnabled(False)  # type: ignore[attr-defined]
        self.remember = QCheckBox(_("&Remember it on this computer"))
        self.remember.setChecked(manager.saved(link.user) if known and link else manager.saving())
        form = QFormLayout()
        form.addRow(_("&User:"), self.user)
        form.addRow(_("&Password:"), self.password)
        form.addRow(_("Use it &for:"), self.kind)
        form.addRow("", self.value)
        form.addRow("", self.remember)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(notes(
            _("A PC's own account wins over its group's, a group's over a tag's, and those "
              "over Every PC. PCs none of them names use your Windows account."),
            _("Groups and tags are the open list's."),
        ))  # fmt: skip
        layout.addWidget(self.buttons)
        self.kind.currentIndexChanged.connect(self._kind_picked)
        for edit in (self.user, self.address):
            edit.textChanged.connect(self._update_ok)
        self.tag.currentTextChanged.connect(self._update_ok)
        if link is not None:
            self._show(link)
        self._kind_picked()
        self.resize(480, self.sizeHint().height())

    def _show(self, link: Link) -> None:
        self.kind.setCurrentIndex(max(self.kind.findData(link.scope), 0))
        if link.scope is Scope.PC:
            self.address.setText(link.value)
        elif link.scope is Scope.GROUP:
            index = self.group.findData(link.value) if _same_list(link, self._doc) else -1
            if index < 0:  # another list's group: kept as it is
                self.group.addItem(used_for(link, self._doc), link.value)
                index = self.group.count() - 1
            self.group.setCurrentIndex(index)
        elif link.scope is Scope.TAG:
            self.tag.setCurrentText(link.value)
        self._original = link

    def scope(self) -> Scope:
        return Scope(self.kind.currentData())  # Qt hands the item's data back as a str

    def _kind_picked(self) -> None:
        self.value.setCurrentIndex(max(self.kind.currentIndex(), 0))
        self.value.setVisible(self.scope() is not Scope.ALL)
        self._update_ok()

    def _update_ok(self) -> None:
        scope = self.scope()
        value = {
            Scope.ALL: "-",
            Scope.PC: self.address.text().strip(),
            Scope.GROUP: self.group.currentData() or "",
            Scope.TAG: self.tag.currentText().strip(),
        }.get(scope, "")
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.user.text().strip()) and bool(value))

    def link(self) -> Link:
        user = self.user.text().strip()
        scope = self.scope()
        old: Link | None = getattr(self, "_original", None)
        if scope is Scope.PC:
            value = self.address.text().strip()
            name = old.name if old and old.scope is Scope.PC and old.value == value else ""
            return Link(user, scope, value, name=name)
        if scope is Scope.GROUP:
            group_id = str(self.group.currentData())
            if old and old.scope is Scope.GROUP and old.value == group_id and not _same_list(
                    old, self._doc):  # fmt: skip
                return Link(user, scope, group_id, old.list, old.name)
            assert self._doc is not None
            return Link(user, scope, group_id, str(self._doc.path),
                        self.group.currentText())  # fmt: skip
        if scope is Scope.TAG:
            tag = self.tag.currentText().strip()
            where = old.list if old and old.scope is Scope.TAG and not _same_list(
                old, self._doc) else str(self._doc.path if self._doc else "")  # fmt: skip
            return Link(user, scope, tag, where)
        return Link(user, Scope.ALL)


class AccountsSection(Section):
    """Which account signs in to which PCs: one row per link, in the table every list uses."""

    def __init__(self, manager: Accounts) -> None:
        super().__init__(_("Accounts"))
        self._manager = manager
        self.table = grid_table([_("Account"), _("Used for"), _("Kept in")])
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda *_a: self.edit())
        self.add_button = QPushButton(_("&Add…"))
        self.edit_button = QPushButton(_("&Edit…"))
        self.remove_button = QPushButton(_("Re&move"))
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.remove_button.clicked.connect(self.remove)
        row_menu(self.table, self._fill_row_menu)
        self.content.addWidget(
            with_buttons(self.table, [self.add_button, self.edit_button, self.remove_button])
        )
        self.content.addWidget(notes(
            _("Which account signs in to which PCs, for Refresh's logged-on users and the "
              "commands you run on a host. PCs no row names use your Windows account."),
            _("Yours only: kept in your own settings, never in the shared host lists."),
        ))  # fmt: skip
        manager.changed.connect(self.fill)
        self.fill()

    def fill(self) -> None:
        picked = self._picked()
        self.table.clear()
        doc = self._manager.document()
        for link in self._manager.links:
            where = used_for(link, doc)
            item = QTreeWidgetItem([link.user, where, self._manager.kept_in(link.user)])
            item.setData(0, Qt.ItemDataRole.UserRole, link)
            for column in range(3):
                item.setToolTip(column, item.text(column))
            if link.list:
                item.setToolTip(1, f"{where}\n{link.list}")
            self.table.addTopLevelItem(item)
            if link == picked:
                self.table.setCurrentItem(item)
        fit_rows(self.table)
        self._update_buttons()

    def _picked(self) -> Link | None:
        item = self.table.currentItem() if self.table.selectedItems() else None
        link = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return link if isinstance(link, Link) else None

    def _update_buttons(self) -> None:
        picked = self._picked() is not None
        self.edit_button.setEnabled(picked)
        self.remove_button.setEnabled(picked)

    def _fill_row_menu(self, menu: QMenu) -> None:
        picked = self._picked() is not None
        add_action(menu, _("&Edit…"), self.edit, picked)
        add_action(menu, _("Re&move"), self.remove, picked)

    def _save(self, dialog: LinkDialog, old: Link | None) -> None:
        link = dialog.link()
        manager = self._manager
        if old is None:
            manager.use(link, None, remember=False)
        else:
            manager.replace_link(old, link)
        typed = dialog.password.text()
        remember = dialog.remember.isChecked()
        if typed:
            manager.keep(Account(link.user, typed), remember=remember)
        elif (known := manager.known(link.user)) is not None and remember != manager.saved(
                link.user):  # fmt: skip
            manager.keep(known, remember=remember)  # only where it's kept changed

    def add(self) -> None:
        dialog = LinkDialog(self.window(), _("Add an account"), self._manager, None)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._save(dialog, None)

    def edit(self) -> None:
        old = self._picked()
        if old is None:
            return
        dialog = LinkDialog(self.window(), _("Edit the account"), self._manager, old)
        if run_modal(dialog) == QDialog.DialogCode.Accepted:
            self._save(dialog, old)

    def remove(self) -> None:
        link = self._picked()
        if link is None:
            return
        try:
            self._manager.remove(link)
        except OSError as e:
            text = _("Couldn't delete its saved password: {error}").format(error=e)
            QMessageBox.warning(self, "CapyPanel", text)
