import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CMD = str(Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32" / "cmd.exe")

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    yield app
    # Left windows go while Qt is up: freed by Python after the app, they can crash the exit.
    # Pop-ups (a completer's list) belong to their widget: skipped.
    popup = Qt.WindowType.Popup
    for widget in app.topLevelWidgets():
        if widget.windowFlags() & popup != popup:
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def free_windows(qapp: QApplication) -> Iterator[None]:
    """Else every later theme switch restyles them (minutes over the suite)."""
    before = set(qapp.topLevelWidgets())
    yield
    popup = Qt.WindowType.Popup
    for widget in qapp.topLevelWidgets():
        if widget not in before and widget.windowFlags() & popup != popup:
            widget.close()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture
def default_theme_after(qapp: QApplication) -> Iterator[None]:
    from capypanel.ui.themes import engine as themes

    yield
    if themes.current() is not themes.DEFAULT_THEME:
        themes.apply(themes.DEFAULT_THEME)


@pytest.fixture(autouse=True)
def no_facts_on_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never on their own in tests: they'd reach made-up addresses on the real network."""
    from capypanel.ui.hosts_tool.tool import HostsTool

    monkeypatch.setattr(HostsTool, "_read_shown_facts", lambda _self: None)


@pytest.fixture(autouse=True)
def no_browser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Web links land here, never in the browser: a stray F1 would open the real website."""
    from capypanel.ui import about

    opened: list[str] = []
    monkeypatch.setattr(about, "open_url", opened.append)
    return opened


@pytest.fixture(autouse=True)
def help_boxes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Warnings land here as (text, place) instead of waiting for a click that never comes."""
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
    """ssh.exe never starts and no real port is knocked on: a tab runs cmd.exe, off the network."""
    from capypanel.core.remote.status import PortState
    from capypanel.core.ssh import known, launch, terminals
    from capypanel.ui.ssh_tool import refresh

    started: list[tuple[str, object]] = []
    monkeypatch.setattr(
        launch,
        "connect",
        lambda address, info, name="", terminal=None: started.append((address, info)),
    )
    monkeypatch.setattr(terminals, "ready_here", lambda env=None: [])

    def in_tab(address: str, info: object) -> list[str]:
        started.append((address, info))
        return [CMD, "/d"]

    monkeypatch.setattr(launch, "tab_command", in_tab)
    monkeypatch.setattr(known, "asks_to_trust", lambda _address, _info: False)
    monkeypatch.setattr(refresh, "port_state", lambda _host, _port: (PortState.NO_ANSWER, None))
    return started


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Theme tests first: a switch restyles every window still alive, so late it took minutes."""
    items.sort(key=lambda item: "test_themes.py" not in item.nodeid)
