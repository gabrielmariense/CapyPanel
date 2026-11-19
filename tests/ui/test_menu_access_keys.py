"""No right-click menu on hosts gives one access key to two items, in either language: Alt and
that letter would only ever reach the first. Hosts, SSH, Printers and Profile cleanup's Hosts
tab, with one host picked and with two, and Hosts', SSH's and Printers' group menus, each with
the menus inside it (Satya's keys, build 618: Re&fresh, At&ualizar, Commands run a&s, To&dos,
Sho&w, en&dereço)."""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QMenu

from capypanel.core import i18n, settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.printers.printer import PrinterInfo
from capypanel.core.printers.printer import with_info as with_printer_info
from capypanel.core.ssh.host import SshInfo, with_info
from capypanel.ui import language, menus
from capypanel.ui.list_workspace import workspace as workspace_module
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.profiles_tool import tool as profiles_module
from capypanel.ui.profiles_tool import work
from capypanel.ui.profiles_tool.tool import ProfilesTool

KEY = re.compile(r"&([^&])")  # the letter after a lone "&"; "&&" writes an "&"


@pytest.fixture
def window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[CapyWindow]:
    monkeypatch.setattr(work, "start", lambda *_args, **_kwargs: None)  # no PC is ever read
    (tmp_path / settings.PORTABLE_MARKER).touch()
    office, group = HostList().add_group("Office")
    for name, address in (("DESK-01", "192.0.2.11"), ("DESK-02", "192.0.2.12")):
        office, _host = office.add_host(name, group.id, address=address)
    office, racks = office.add_group("Racks")  # SSH shows the same list: its servers are in it
    for name, address in (("core-sw-01", "192.0.2.40"), ("nas-01", "192.0.2.41")):
        office, host = office.add_host(name, racks.id, address=address)
        office = office.update_host(with_info(host, SshInfo(login="admin")))
    listfile.save(tmp_path / "office.json", office, expected=None)
    printers, floor = HostList().add_group("Second floor")
    for name, address in (("2F-LABELS", "192.0.2.25"), ("2F-OFFICE-01", "192.0.2.21")):
        printers, printer = printers.add_host(name, floor.id, address=address)
        printers = printers.update_host(with_printer_info(printer, PrinterInfo(brand="ZEBRA")))
    listfile.save(tmp_path / "printers.json", printers, expected=None, kind="printers")
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(tmp_path / "office.json")
    ssh = win.tools["ssh"]
    assert isinstance(ssh, ListWorkspace) and ssh.document is win.hosts.document
    printers_tool = win.tools["printers"]
    assert isinstance(printers_tool, ListWorkspace)
    assert printers_tool.open_list(tmp_path / "printers.json")
    yield win
    win.close()
    language.apply(i18n.DEFAULT_LANGUAGE)
    QApplication.processEvents()


def _repeats(menu: QMenu, where: str) -> dict[str, dict[str, list[str]]]:
    """Each access key two or more items share, in the menu and in each menu inside it (filled
    as it opens), with their words."""
    items: dict[str, list[str]] = {}
    found: dict[str, dict[str, list[str]]] = {}
    for action in menu.actions():
        if action.isSeparator() or not action.isVisible():
            continue
        text = menus.label(action)
        if key := KEY.search(text):
            items.setdefault(key.group(1).casefold(), []).append(text)
        inside = action.menu()
        if isinstance(inside, QMenu):
            inside.aboutToShow.emit()
            found.update(_repeats(inside, f"{where} › {menus.plain(text)}"))
    if shared := {key: texts for key, texts in items.items() if len(texts) > 1}:
        found[where] = shared
    return found


def _list_menus(
    tool: ListWorkspace, name: str, found: dict[str, dict[str, list[str]]]
) -> dict[str, QMenu]:
    """Each is checked as soon as it's filled, into `found`: the menus share one Refresh action,
    whose words the next menu changes ("Re&fresh printer", then "Re&fresh 2 printers")."""
    doc = tool.document
    assert doc is not None
    ids = [h.id for h in doc.hosts.hosts]
    made: dict[str, QMenu] = {}
    for picked in (ids[:1], ids[:2]):
        tool.table.select_ids(picked)
        menu = QMenu()
        tool.fill_item_menu(menu, tool.selected_items())
        made[f"{name}, {len(picked)} picked"] = menu
        found.update(_repeats(menu, f"{name}, {len(picked)} picked"))
    return made


def _group_menus(win: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> dict[str, QMenu]:
    shown: list[QMenu] = []
    monkeypatch.setattr(workspace_module, "popup", lambda menu, _where: shown.append(menu))
    made: dict[str, QMenu] = {}
    for name, tool in (
        ("Hosts", win.hosts),
        ("SSH", win.tools["ssh"]),
        ("Printers", win.tools["printers"]),
    ):
        assert isinstance(tool, ListWorkspace) and tool.document is not None
        group = tool.document.hosts.groups[0].id
        monkeypatch.setattr(tool.nav, "group_at", lambda _where, g=group: g)  # the one clicked
        tool._group_menu(QPoint(0, 0))  # noqa: SLF001
        made[f"{name}'s group menu"] = shown[-1]
    return made


def _profiles_menus(win: CapyWindow, monkeypatch: pytest.MonkeyPatch) -> dict[str, QMenu]:
    tool = win.tools["profiles"]
    assert isinstance(tool, ProfilesTool)
    win.show_tool("profiles")
    shown: list[QMenu] = []
    monkeypatch.setattr(profiles_module, "popup", lambda menu, _where: shown.append(menu))
    tree = tool.hosts_page.table.tree
    made: dict[str, QMenu] = {}
    for count in (1, 2):
        tree.clearSelection()
        for index in range(count):
            row = tree.topLevelItem(index)
            assert row is not None
            row.setSelected(True)
        tool._hosts_menu(QPoint(0, 0))  # noqa: SLF001
        made[f"Profile cleanup's Hosts tab, {count} picked"] = shown[-1]
    return made


@pytest.mark.parametrize("code", ["en", "pt_BR"])
def test_no_host_menu_gives_one_access_key_to_two_items(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    window.set_language(code)
    QApplication.processEvents()
    ssh, printers = window.tools["ssh"], window.tools["printers"]
    assert isinstance(ssh, ListWorkspace) and isinstance(printers, ListWorkspace)
    repeats: dict[str, dict[str, list[str]]] = {}
    listed = {
        **_list_menus(window.hosts, "Hosts", repeats),
        **_list_menus(ssh, "SSH", repeats),
        **_list_menus(printers, "Printers", repeats),
    }
    others = {**_group_menus(window, monkeypatch), **_profiles_menus(window, monkeypatch)}
    made = {**listed, **others}
    assert len(made) == 11 and all(menu.actions() for menu in made.values())
    for name, menu in others.items():
        repeats.update(_repeats(menu, name))
    assert repeats == {}
