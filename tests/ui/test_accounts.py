"""Which account signs in to which PC: Settings' Accounts table, the login window's "Use it
for", Details' Signs in as, and Refresh and the host commands using each PC's own account."""

import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from capywindow import CapyWindow
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu

from capypanel.core import credstore, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.accounts import Link, Scope, credential_name
from capypanel.core.hosts.model import HostList
from capypanel.core.remote import checks
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.checks import Checks, Found
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.core.tools.connect import Credential
from capypanel.ui import checks as check_ui
from capypanel.ui.hosts_tool import accounts as accounts_ui
from capypanel.ui.hosts_tool.accounts import AccountsSection, LinkDialog
from capypanel.ui.hosts_tool.runner import HostTarget
from capypanel.ui.hosts_tool.settings import HostsSettings

DESK = Session("ana", "EXAMPLE", "console", "active", None)
ADMIN = Account("EXAMPLE\\admin", "pw")


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, clinic = HostList().add_group("Clinic")
    hl, front = hl.add_group("Front desk", parent=clinic.id)
    for name, group, address, tags in [
        ("DESK-01", front.id, "192.0.2.11", ()), ("DESK-02", front.id, "192.0.2.12", ("VPN",)),
        ("DESK-03", clinic.id, "192.0.2.13", ("VPN",)),
    ]:  # fmt: skip
        hl, host = hl.add_host(name, group, address=address)
        hl = hl.update_host(host.__class__(**{**host.__dict__, "tags": tags}))
    path = tmp_path / "clinic.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


def _host(win: CapyWindow, name: str) -> HostTarget:
    doc = win.hosts.document
    assert doc is not None
    host = next(h for h in doc.hosts.hosts if h.name == name)
    return HostTarget(host.id, host.name, host.connect_address)


def _group_id(win: CapyWindow, name: str) -> str:
    doc = win.hosts.document
    assert doc is not None
    return next(g.id for g in doc.hosts.groups if g.name == name)


def _list(win: CapyWindow) -> str:
    doc = win.hosts.document
    assert doc is not None
    return str(doc.path)


def _settle(win: CapyWindow) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not win.hosts.runner.busy() and win.hosts._run is None:  # pyright: ignore[reportPrivateUsage]
            return
    pytest.fail("never finished")


def _account_used(win: CapyWindow, target: HostTarget) -> list[Account | None]:
    """The account a host command for `target` gets."""
    seen: list[Account | None] = []
    win.hosts.runner.call(seen.append, lambda _v: None, lambda e: pytest.fail(str(e)), target)
    _settle(win)
    return seen


def _answer(monkeypatch: pytest.MonkeyPatch, fill: Callable[[check_ui.AccountDialog], bool],
            asked: list[check_ui.AccountDialog] | None = None) -> None:  # fmt: skip
    def run(dialog: check_ui.AccountDialog) -> int:
        if asked is not None:
            asked.append(dialog)
        return QDialog.DialogCode.Accepted if fill(dialog) else QDialog.DialogCode.Rejected

    monkeypatch.setattr(check_ui.AccountDialog, "exec", run)


def test_each_pc_gets_its_own_account_and_details_says_which(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    accounts = window.hosts.accounts
    accounts.use(Link(ADMIN.user, Scope.GROUP, _group_id(window, "Front desk"), _list(window),
                      "Clinic › Front desk"), ADMIN, remember=False)  # fmt: skip
    other = Account("EXAMPLE\\desk2", "x")
    accounts.use(Link(other.user, Scope.PC, "192.0.2.12", name="DESK-02"), other, remember=False)
    assert _account_used(window, _host(window, "DESK-01")) == [ADMIN]  # its group's
    assert _account_used(window, _host(window, "DESK-02")) == [other]  # its own wins
    assert _account_used(window, _host(window, "DESK-03")) == [None]  # the Windows account
    typed = HostTarget("@192.0.2.12", "192.0.2.12", "192.0.2.12")  # the Commands window's
    assert _account_used(window, typed) == [other]

    window.hosts.table.select_ids([_host(window, "DESK-01").key])
    labels = [w.text() for w in window.hosts.details.findChildren(QLabel)]
    at = labels.index("Commands run as")
    assert labels[at + 1 : at + 3] == [ADMIN.user, "from Accounts"]
    assert "Connect with" in labels  # the profile: what Connect uses, named apart
    window.hosts.table.select_ids([_host(window, "DESK-03").key])
    labels = [w.text() for w in window.hosts.details.findChildren(QLabel)]
    at = labels.index("Commands run as")
    assert labels[at + 1 : at + 3] == [accounts_ui.windows_account(), "your Windows account"]


def test_a_password_not_typed_yet_is_asked_once_and_never_for_a_read_on_its_own(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.hosts.accounts.use(Link(ADMIN.user, Scope.TAG, "vpn", _list(window)), None,
                              remember=False)  # fmt: skip
    target = _host(window, "DESK-02")
    window.hosts.runner.read_facts(target)  # on its own, as when a host stays selected
    assert not window.hosts.runner.busy()  # nothing asked, nothing read

    asked: list[check_ui.AccountDialog] = []
    _answer(monkeypatch, lambda d: False, asked)
    assert _account_used(window, target) == []  # cancelled: nothing ran
    assert asked[-1].user.isReadOnly() and asked[-1].user.text() == ADMIN.user

    def type_it(dialog: check_ui.AccountDialog) -> bool:
        dialog.password.setText("pw")
        return True

    _answer(monkeypatch, type_it, asked)
    assert _account_used(window, target) == [ADMIN]
    assert _account_used(window, _host(window, "DESK-03")) == [ADMIN]  # the same tag
    assert len(asked) == 2  # asked once, then known
    assert credstore.read(credential_name(ADMIN.user)) is None  # not remembered


def test_try_another_account_offers_the_pcs_and_keeps_the_choice(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    offered: list[str] = []

    def pick_group(dialog: check_ui.AccountDialog) -> bool:
        offered.extend(dialog.use_for.itemText(i) for i in range(dialog.use_for.count()))
        dialog.user.setText(ADMIN.user)
        dialog.password.setText(ADMIN.password)
        dialog.use_for.setCurrentIndex(1)  # every PC in its group
        dialog.remember.setChecked(True)
        return True

    _answer(monkeypatch, pick_group)
    again: list[str] = []
    target = _host(window, "DESK-02")
    window.hosts.runner.another_account(target, RemoteError(Reason.NOT_ADMIN, 5),
                                        lambda: again.append("again"))  # fmt: skip
    assert offered == ["This PC (DESK-02)", "Every PC in group Clinic › Front desk",
                       "Every PC in group Clinic", "Every PC tagged VPN", "Every PC"]  # fmt: skip
    assert again == ["again"]
    [link] = window.hosts.accounts.links
    assert (link.scope, link.user, link.name) == (Scope.GROUP, ADMIN.user, "Clinic › Front desk")
    assert credstore.read(credential_name(ADMIN.user)) == (ADMIN.user, ADMIN.password)
    assert _account_used(window, _host(window, "DESK-01")) == [ADMIN]
    assert window.hosts.prefs["accounts"][0]["scope"] == "group"  # kept for the next start


def test_a_rejected_account_stops_only_the_pcs_that_use_it(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, Account | None]] = []

    def run(address: str, wanted: Checks) -> Found:
        seen.append((address, wanted.account))
        if wanted.account == ADMIN:
            return Found(Status.ONLINE, users_error=RemoteError(Reason.REJECTED, 1326))
        return Found(Status.ONLINE, (DESK,))

    monkeypatch.setattr(checks, "run", run)
    _answer(monkeypatch, lambda _d: False)  # the question after the Refresh: no
    window.hosts.accounts.use(Link(ADMIN.user, Scope.GROUP, _group_id(window, "Front desk"),
                                   _list(window)), ADMIN, remember=False)  # fmt: skip
    doc = window.hosts.document
    assert doc is not None
    window.hosts.table.select_ids([h.id for h in doc.hosts.hosts])
    window.hosts.commands.check_users.trigger()
    _settle(window)
    tried = dict(seen)
    assert tried["192.0.2.13"] is None  # the Windows account's PC still read
    assert sum(account == ADMIN for _a, account in seen) == 1  # one rejection, then stopped


def _section(win: CapyWindow) -> AccountsSection:
    return win.settings_dialog().group(HostsSettings).accounts


def _rows(section: AccountsSection) -> list[list[str]]:
    table = section.table
    return [[table.topLevelItem(r).text(c) for c in range(3)]  # type: ignore[union-attr]
            for r in range(table.topLevelItemCount())]  # fmt: skip


def test_the_settings_table_adds_edits_and_removes_accounts(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = _section(window)
    assert _rows(section) == []

    def add_group(dialog: LinkDialog) -> int:
        dialog.user.setText(ADMIN.user)
        dialog.kind.setCurrentIndex(dialog.kind.findData(Scope.GROUP))
        dialog.group.setCurrentIndex(dialog.group.findText("Clinic › Front desk"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LinkDialog, "exec", add_group)
    section.add_button.click()
    assert _rows(section) == [[ADMIN.user, "Group Clinic › Front desk", "Asked when needed"]]

    def edit_to_pc(dialog: LinkDialog) -> int:
        assert dialog.scope() is Scope.GROUP  # shows the row as it is
        dialog.kind.setCurrentIndex(dialog.kind.findData(Scope.PC))
        dialog.address.setText("192.0.2.13")
        dialog.password.setText("pw")
        dialog.remember.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LinkDialog, "exec", edit_to_pc)
    section.table.setCurrentItem(section.table.topLevelItem(0))  # type: ignore[arg-type]
    section.edit_button.click()
    assert _rows(section) == [[ADMIN.user, "192.0.2.13", "Credential Manager"]]
    assert _account_used(window, _host(window, "DESK-03")) == [ADMIN]

    section.table.setCurrentItem(section.table.topLevelItem(0))  # type: ignore[arg-type]
    section.remove_button.click()
    assert _rows(section) == [] and window.hosts.accounts.links == []
    assert credstore.read(credential_name(ADMIN.user)) is None  # its password went too


def test_a_group_or_tag_needs_the_list_it_belongs_to(window: CapyWindow) -> None:
    dialog = LinkDialog(None, "Add", window.hosts.accounts, None)
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    dialog.user.setText(ADMIN.user)
    assert ok.isEnabled()  # Every PC needs nothing more
    dialog.kind.setCurrentIndex(dialog.kind.findData(Scope.TAG))
    assert not ok.isEnabled()
    dialog.tag.setCurrentText("VPN")
    assert ok.isEnabled()
    assert dialog.link() == Link(ADMIN.user, Scope.TAG, "VPN", _list(window))


def test_the_account_an_older_capypanel_saved_becomes_every_pc(
    qapp: QApplication, tmp_path: Path
) -> None:
    credstore.save(accounts_ui.OLD_SAVED, "pw", user=ADMIN.user)
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1, "save_passwords": True})
    try:
        assert win.hosts.accounts.links == [Link(ADMIN.user, Scope.ALL)]
        assert win.hosts.accounts.known(ADMIN.user) == ADMIN
        assert credstore.read(accounts_ui.OLD_SAVED) is None
        assert credstore.read(credential_name(ADMIN.user)) == (ADMIN.user, "pw")
    finally:
        win.close()


def test_links_never_go_in_the_shared_list(window: CapyWindow, tmp_path: Path) -> None:
    window.hosts.accounts.use(Link(ADMIN.user, Scope.ALL), ADMIN, remember=False)
    text = (tmp_path / "clinic.json").read_text(encoding="utf-8")
    assert ADMIN.user.replace("\\", "\\\\") not in text and "admin" not in text


def test_connect_with_shows_the_login_kept_for_the_profile(window: CapyWindow) -> None:
    hosts = window.hosts
    hosts.table.select_ids([_host(window, "DESK-01").key])
    labels = [w.text() for w in hosts.details.findChildren(QLabel)]
    profile = labels[labels.index("Connect with") + 1]
    assert "· as" not in profile  # nothing typed for it yet
    profile_id = hosts.connector.catalogs.profiles.default_id()
    hosts.connector.credentials.remember(profile_id, Credential("EXAMPLE\\helpdesk", "x"))
    hosts.table.select_ids([_host(window, "DESK-03").key])
    hosts.table.select_ids([_host(window, "DESK-01").key])
    labels = [w.text() for w in hosts.details.findChildren(QLabel)]
    assert labels[labels.index("Connect with") + 1] == f"{profile} · as EXAMPLE\\helpdesk"


def _texts(menu: Any) -> list[str]:
    return [a.text() for a in menu.actions() if a.text()]


def _choose(menu: Any, text: str) -> None:
    next(a for a in menu.actions() if a.text().startswith(text)).trigger()


def test_details_arrow_picks_the_account_for_this_pc(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = window.hosts
    accounts = hosts.accounts
    accounts.use(Link(ADMIN.user, Scope.GROUP, _group_id(window, "Front desk"), _list(window)),
                 ADMIN, remember=False)  # fmt: skip
    hosts.table.select_ids([_host(window, "DESK-01").key])
    menu = hosts.details.account_menu
    menu.aboutToShow.emit()
    texts = _texts(menu)
    assert texts[0] == f"Follow Accounts: {ADMIN.user}"
    assert texts[1].startswith("Your Windows account (") and ADMIN.user in texts
    assert texts[-1] == "&Another account…"
    assert next(a for a in menu.actions() if a.text() == texts[0]).isChecked()

    _choose(menu, "Your Windows account")  # this PC stays on mine, despite its group
    target = _host(window, "DESK-01")
    assert _account_used(window, target) == [None]
    assert _account_used(window, _host(window, "DESK-02")) == [ADMIN]  # the group's others
    labels = [w.text() for w in hosts.details.findChildren(QLabel)]
    at = labels.index("Commands run as")
    assert labels[at + 1 : at + 3] == [accounts_ui.windows_account(), "your Windows account"]

    menu.aboutToShow.emit()
    _choose(menu, "Follow Accounts")  # its own row goes; the group's applies again
    assert accounts.own(target) is None
    assert _account_used(window, target) == [ADMIN]

    other = Account("EXAMPLE\\desk1", "y")

    def type_it(dialog: check_ui.AccountDialog) -> bool:
        dialog.user.setText(other.user)
        dialog.password.setText(other.password)
        return True

    _answer(monkeypatch, type_it)
    menu.aboutToShow.emit()
    _choose(menu, "&Another account")
    assert _account_used(window, target) == [other]


def test_right_click_sets_several_pcs_or_a_group(window: CapyWindow) -> None:
    hosts = window.hosts
    accounts = hosts.accounts
    accounts.use(Link(ADMIN.user, Scope.ALL), ADMIN, remember=False)
    doc = hosts.document
    assert doc is not None
    picked = [h for h in doc.hosts.hosts if h.name in ("DESK-01", "DESK-03")]
    menu = QMenu()
    hosts._fill_hosts_account_menu(menu, picked)  # pyright: ignore[reportPrivateUsage]
    assert _texts(menu)[0] == "Follow Accounts"
    _choose(menu, "Your Windows account")
    assert _account_used(window, _host(window, "DESK-01")) == [None]
    assert _account_used(window, _host(window, "DESK-03")) == [None]
    assert _account_used(window, _host(window, "DESK-02")) == [ADMIN]  # not picked

    group = next(g for g in doc.hosts.groups if g.name == "Front desk")
    menu = QMenu()
    hosts._fill_group_account_menu(menu, group)  # pyright: ignore[reportPrivateUsage]
    _choose(menu, "Your Windows account")
    assert accounts.group_row(group.id) is not None
    assert _account_used(window, _host(window, "DESK-02")) == [None]
    _choose(menu, "Follow Accounts")
    assert accounts.group_row(group.id) is None
    assert _account_used(window, _host(window, "DESK-02")) == [ADMIN]
