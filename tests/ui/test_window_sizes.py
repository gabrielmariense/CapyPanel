"""No window grows by accident: each one's height as recorded when the spacing scale came in
(4 px between an icon and its word, 8 between controls on a line, 12 inside a panel or card, 16
around a window and between sections). A change that makes one taller fails here, and is then
either fixed or recorded on purpose."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.remote.sessions import Session
from capypanel.ui.checks import AccountDialog
from capypanel.ui.groups import ManageGroupsDialog
from capypanel.ui.hosts import HostDialog
from capypanel.ui.hosts_tool.command_windows import MessageDialog, OpenPathDialog, PowerDialog
from capypanel.ui.hosts_tool.commands_window import CommandsWindow
from capypanel.ui.import_hosts import ImportDialog
from capypanel.ui.new_list import NewListDialog
from capypanel.ui.saved_credentials import SavedCredentialsDialog
from capypanel.ui.settings.window import WIDTH
from capypanel.ui.themes import engine as themes

# Measured in the CapyPanel dark theme, as people see them. With another font than the theme's
# (a PC without it), heights differ and the comparison says nothing.
FONT = (13, 13)  # a line's height, an average letter's width
RECORDED = {
    "add host": 427,
    "edit host": 427,
    "manage groups": 326,
    "import hosts": 481,
    "new list": 175,
    "account for other PCs": 237,
    "restart": 292,
    "open a folder": 176,
    "send a message": 242,
    "saved credentials": 335,
    "commands": 620,
    "settings": 336,
}


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, desks = HostList().add_group("Front desks")
    hl, _desk = hl.add_host("DESK-01", desks.id, address="192.0.2.11")
    path = tmp_path / "clinic.json"
    listfile.save(path, hl, expected=None)
    themes.apply(themes.Registry().find("capypanel-dark"))  # whatever ran before this test
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


def heights(win: CapyWindow) -> dict[str, int]:
    """Every window that can be built without a person, by name: how tall it wants to be."""
    hosts = win.hosts
    doc = hosts.document
    assert doc is not None
    hl, host = doc.hosts, doc.hosts.hosts[0]
    hosts.table.select_ids([host.id])
    target = hosts.selected_target()
    assert target is not None
    ana = Session("ana", "EXAMPLE", "console", "active", None, session_id=1)
    places = win.paths.lists("hosts")
    made: dict[str, QWidget] = {
        "add host": HostDialog(win, hl),
        "edit host": HostDialog(win, hl, host),
        "manage groups": ManageGroupsDialog(win, hl),
        "import hosts": ImportDialog(win, hl, hl.groups[0].id),
        "new list": NewListDialog(
            win, shared_dir=places.shared_dir, user_dir=places.user_dir, texts=hosts.list_texts()
        ),
        "account for other PCs": AccountDialog(win, "DESK-01 didn't accept the account."),
        "restart": PowerDialog(win, "DESK-01", (ana,), restart=True),
        "open a folder": OpenPathDialog(win, "DESK-01", ()),
        "send a message": MessageDialog(win, "DESK-01", (ana,)),
        "saved credentials": SavedCredentialsDialog(win, lambda: []),
        "commands": CommandsWindow(hosts, target, hosts.profile_for(target)),
        "settings": win.settings_dialog(),
    }
    found = {}
    for name, widget in made.items():
        widget.ensurePolished()
        fixed = widget.minimumHeight() == widget.maximumHeight()
        found[name] = widget.height() if fixed else widget.sizeHint().height()
        if name != "settings":  # the window keeps its own
            widget.deleteLater()
    return found


def test_no_window_is_taller_than_when_the_spacing_scale_came_in(window: CapyWindow) -> None:
    metrics = QFontMetrics(window.font())
    if (metrics.height(), metrics.averageCharWidth()) != FONT:
        pytest.skip("another font than the heights were recorded with")
    found = heights(window)
    assert set(found) == set(RECORDED)
    taller = {n: (found[n], RECORDED[n]) for n in found if found[n] > RECORDED[n]}
    assert not taller, f"taller than recorded (now, recorded): {taller}"


def test_settings_opens_wide_enough_for_its_tables(window: CapyWindow) -> None:
    """960 px: a row with a domain account, a PC by name and address and "Gerenciador de
    Credenciais" shows whole, with nothing to scroll sideways (measured in the dark theme with
    its own font; the test font is twice as wide). A narrower size kept by an older version
    opens at this width too."""
    dialog = window.settings_dialog()
    assert (dialog.width(), dialog.height()) == (WIDTH, 700) and WIDTH == 960
    dialog.resize(860, 700)
    assert dialog.width() == WIDTH
    dialog.resize(1100, 700)  # wider is the person's choice
    assert dialog.width() == 1100
