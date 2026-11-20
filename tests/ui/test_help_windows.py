"""The ? in the main window's tools' windows (topic-030): first in each window's button row, on
its left, opening that window's own part of the docs, and F1 with it. A question has no ?: F1
opens the part of the window that asked. Printers' own windows are in its tests; the places
themselves are checked against the docs by tests/docs/test_help_places.py."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.commands import COMMANDS
from capypanel.core.hosts.model import HostList
from capypanel.core.remote.sessions import Session
from capypanel.ui import help_links
from capypanel.ui.about import LicenseReader
from capypanel.ui.checks import AccountDialog
from capypanel.ui.error_window import ErrorWindow
from capypanel.ui.export_hosts import ExportDialog
from capypanel.ui.groups import ManageGroupsDialog
from capypanel.ui.hosts import HostDialog
from capypanel.ui.hosts_tool import command_windows as windows
from capypanel.ui.hosts_tool.accounts import LinkDialog
from capypanel.ui.hosts_tool.commands_window import COMMAND_PLACES, CommandsWindow
from capypanel.ui.hosts_tool.drive_windows import DrivesDialog
from capypanel.ui.import_hosts import FormatsDialog, ImportDialog
from capypanel.ui.list_workspace import customize, workspace
from capypanel.ui.new_list import NewListDialog
from capypanel.ui.profiles_tool.first_use import FirstUseWarning
from capypanel.ui.profiles_tool.side import ProfileWindow
from capypanel.ui.saved_credentials import SavedCredentialsDialog
from capypanel.ui.settings.connections import ProfileDialog
from capypanel.ui.ssh_tool.dialog import LoginDialog, SshHostDialog

SITE = "https://gabrielmariense.github.io/CapyPanel/"


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, desks = HostList().add_group("Front desks")
    hl, _desk = hl.add_host("DESK-01", desks.id, address="192.0.2.11")
    path = tmp_path / "clinic.json"
    listfile.save(path, hl, expected=None)
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.hosts.open_list(path)
    yield win
    win.close()


def _first_in_its_row(dialog: QWidget, button: QWidget) -> bool:
    """The ? is left of every button on its line."""
    dialog.show()
    QApplication.processEvents()
    left, middle = (
        button.mapTo(dialog, QPoint(0, 0)).x(),
        button.mapTo(dialog, button.rect().center()).y(),
    )
    row = [
        b
        for b in dialog.findChildren(QPushButton)
        if b.isVisible() and abs(b.mapTo(dialog, b.rect().center()).y() - middle) < button.height()
    ]
    return bool(row) and all(left < b.mapTo(dialog, QPoint(0, 0)).x() for b in row)


def test_each_window_s_question_mark_comes_first_and_opens_its_part(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = window.hosts
    doc = hosts.document
    assert doc is not None
    hl, host = doc.hosts, doc.hosts.hosts[0]
    hosts.table.select_ids([host.id])
    target = hosts.selected_target()
    assert target is not None
    ana = Session("ana", "EXAMPLE", "console", "active", None, session_id=1)
    places = window.paths.lists("hosts")
    tools = [e.item for e in hosts.connector.catalogs.tools.all()]
    made: dict[str, tuple[QWidget, str]] = {
        "add host": (HostDialog(window, hl), "start-add-your-first-hosts"),
        "manage groups": (ManageGroupsDialog(window, hl), "host-lists-arrange-hosts-in-groups"),
        "import hosts": (
            ImportDialog(window, hl, hl.groups[0].id),
            "host-lists-add-hosts-from-a-spreadsheet",
        ),
        "formats": (FormatsDialog(window), "host-lists-add-hosts-from-a-spreadsheet"),
        "new list": (
            NewListDialog(
                window,
                shared_dir=places.shared_dir,
                user_dir=places.user_dir,
                texts=hosts.list_texts(),
            ),
            "host-lists-switch-make-and-share-lists",
        ),  # fmt: skip
        "another account": (
            AccountDialog(window, "DESK-01 didn't accept the account."),
            "hosts-checking-when-a-host-refuses-your-account",
        ),
        "an account for some PCs": (
            LinkDialog(window, "Add", hosts.accounts, None),
            "connecting-use-another-account-on-some-pcs",
        ),
        "connection profile": (
            ProfileDialog(window, "New", tools, set()),
            "connecting-set-up-connection-profiles",
        ),
        "saved credentials": (
            SavedCredentialsDialog(window, lambda: []),
            "connecting-forget-a-saved-password",
        ),
        "open a folder": (
            windows.OpenPathDialog(window, "DESK-01", ()),
            "commands-open-a-pcs-folders-and-admin-tools",
        ),
        "send a message": (
            windows.MessageDialog(window, "DESK-01", (ana,)),
            "commands-message-log-off-or-disconnect-someone",
        ),
        "printers on a PC": (
            windows.PrintersDialog(window, hosts.runner, target, hosts.show_outcome),
            "commands-fix-a-pcs-printing",
        ),
        "programs": (
            windows.ProgramsDialog(window, hosts.runner, target, hosts.csv_folder),
            "commands-see-whats-installed-and-mapped",
        ),
        "drives": (
            DrivesDialog(window, hosts.runner, target),
            "commands-see-whats-installed-and-mapped",
        ),
        "ssh host": (SshHostDialog(window, HostList()), "ssh-add-a-host"),
        "log in as": (
            LoginDialog(window, "About.", "admin", "Your Windows name"),
            "ssh-choose-the-name-to-log-in-as",
        ),
        "first use": (FirstUseWarning(window), "profiles/user-profiles/"),
        "a profile": (
            ProfileWindow(window, "DESK-01", "ana"),
            "profiles-see-which-profiles-can-be-deleted",
        ),
        "unexpected error": (ErrorWindow(), "start-get-help-or-report-a-problem"),
        "a license": (LicenseReader(window), "settings-about"),
    }
    for name, (dialog, place) in made.items():
        button = dialog.findChild(help_links.HelpButton)
        assert button is not None, name
        assert button.place() == place, name
        assert _first_in_its_row(dialog, button), name
        dialog.close()
    # The Report and Customize open through their tools.
    reports: list[ExportDialog] = []
    monkeypatch.setattr(ExportDialog, "exec", lambda d: reports.append(d) or 0)
    hosts.commands.export_hosts.trigger()
    [report] = reports
    assert report.help_button.place() == "host-lists-export-hosts-to-a-spreadsheet"
    assert _first_in_its_row(report, report.help_button)
    shown: list[customize.CustomizeDialog] = []
    monkeypatch.setattr(workspace, "run_modal", lambda d: shown.append(d) or 0)
    hosts.customize_details(0)  # Quick commands
    hosts.customize_details(1)  # Information
    assert [d.help_place() for d in shown] == [
        "commands-choose-your-quick-commands",
        "start-hide-parts-of-the-details-panel",
    ]
    assert _first_in_its_row(shown[0], shown[0].help_button)


def test_the_commands_window_s_question_mark_follows_the_command_picked(
    window: CapyWindow, no_browser: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = window.hosts
    doc = hosts.document
    assert doc is not None
    hosts.table.select_ids([doc.hosts.hosts[0].id])
    target = hosts.selected_target()
    assert target is not None
    commands = CommandsWindow(hosts, target, hosts.profile_for(target))
    assert _first_in_its_row(commands, commands.help_button)
    assert commands.help_place() == "hosts-checking-check-your-hosts"  # opens on Refresh host
    commands.pick(next(r for r in commands.rows if r.command.id == "restart"))
    commands.help_button.click()
    assert no_browser == [f"{SITE}hosts/commands/#commands-restart-or-shut-down-a-pc"]
    monkeypatch.setattr(commands, "picked", lambda: None)
    assert commands.help_place() == "commands-the-commands-window"  # none picked
    assert set(COMMAND_PLACES) == {c.id for c in COMMANDS}  # every command has its part
    assert set(COMMAND_PLACES.values()) <= set(help_links.PLACES)
    commands.close()


def test_f1_in_a_question_opens_the_part_of_the_window_that_asked(
    qapp: QApplication, no_browser: list[str]
) -> None:
    ana = Session("ana", "EXAMPLE", "console", "active", None, session_id=1)
    question = windows.PowerDialog(None, "DESK-01", (ana,), restart=True)
    assert question.findChild(help_links.HelpButton) is None  # a question has no ?
    question.show()
    question.activateWindow()
    QApplication.processEvents()
    QTest.keyClick(question, Qt.Key.Key_F1)
    assert no_browser == [f"{SITE}hosts/commands/#commands-restart-or-shut-down-a-pc"]
    question.close()
