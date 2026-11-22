import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Run Qt without a screen, so UI tests work in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CMD = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "cmd.exe")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    yield app
    # Windows the tests left go while Qt is still up: freed by Python after the app, they can
    # crash the process at exit. Pop-ups (a completer's list) belong to their widget: skipped.
    popup = Qt.WindowType.Popup
    for widget in app.topLevelWidgets():
        if widget.windowFlags() & popup != popup:
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def free_windows(qapp: QApplication) -> Iterator[None]:
    """Windows a test leaves go after it, or every later theme switch restyles them all: minutes
    over the suite. Not after a theme switch: deleting a restyled window can crash Qt."""
    from capypanel.ui.themes import engine as themes

    before, generation = set(qapp.topLevelWidgets()), themes.generation()
    yield
    if themes.generation() != generation:
        return
    popup = Qt.WindowType.Popup
    for widget in qapp.topLevelWidgets():
        if widget not in before and widget.windowFlags() & popup != popup:
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def default_theme_after(qapp: QApplication) -> Iterator[None]:
    """For a test that switches themes: the default one again after it."""
    from capypanel.ui.themes import engine as themes

    yield
    if themes.current() is not themes.DEFAULT_THEME:  # a theme switch restyles every window
        themes.apply(themes.DEFAULT_THEME)


@pytest.fixture(autouse=True)
def no_facts_on_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host shown in Details has its PC facts read after a moment: never in tests, which would
    reach out to the made-up addresses on the real network. Tests of it call it themselves."""
    from capypanel.ui.hosts_tool.tool import HostsTool

    monkeypatch.setattr(HostsTool, "_read_shown_facts", lambda _self: None)


@pytest.fixture(autouse=True)
def no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Help and the other web links land here, never in the browser: an F1 pressed for something
    else would open the real website. A test of a link reads this list or patches open_url."""
    from capypanel.ui import about

    opened: list[str] = []
    monkeypatch.setattr(about, "open_url", opened.append)
    return opened


@pytest.fixture(autouse=True)
def help_boxes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Warnings and errors with "What does this mean?" land here as (text, place), not waiting for
    a click that never comes; a test wanting the box itself patches dialogs.run_modal over this."""
    from message_boxes import help_place
    from PySide6.QtWidgets import QMessageBox

    from capypanel.ui import dialogs

    shown: list[tuple[str, str]] = []

    def run(box: QMessageBox) -> int:
        shown.append((box.text(), help_place(box)))
        box.deleteLater()
        return 0

    monkeypatch.setattr(dialogs, "run_modal", run)
    return shown


@pytest.fixture(autouse=True)
def no_ssh(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    """The SSH tool never starts ssh.exe or knocks on a real port in tests: Connect lands here as
    (address, SshInfo), and a tab runs Windows' own cmd.exe in ssh.exe's place, off the network."""
    from capypanel.core.remote.status import PortState
    from capypanel.core.ssh import launch
    from capypanel.ui.ssh_tool import refresh

    started: list[tuple[str, object]] = []
    monkeypatch.setattr(
        launch, "connect", lambda address, info, name="": started.append((address, info))
    )

    def in_tab(address: str, info: object) -> list[str]:
        started.append((address, info))
        return [CMD, "/d"]  # no AutoRun

    monkeypatch.setattr(launch, "tab_command", in_tab)
    monkeypatch.setattr(refresh, "port_state", lambda _host, _port: (PortState.NO_ANSWER, None))
    return started


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Theme tests first. A theme switch restyles every window still alive, and closed windows
    from earlier tests pile up: at the end of the run, the theme tests would take minutes."""
    items.sort(key=lambda item: "test_themes.py" not in item.nodeid)  # keeps the rest in order
