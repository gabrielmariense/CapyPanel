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
    """Windows a test leaves go after it, or every later theme switch restyles them all (the
    suite took minutes). Not after a theme switch: deleting a restyled window can crash Qt."""
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


@pytest.fixture(autouse=True)
def no_facts_on_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host shown in Details has its PC facts read after a moment: never in tests, which would
    reach out to the made-up addresses on the real network. Tests of it call it themselves."""
    from capypanel.ui.hosts_tool.tool import HostsTool

    monkeypatch.setattr(HostsTool, "_read_shown_facts", lambda _self: None)


@pytest.fixture(autouse=True)
def no_ssh(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    """The SSH tool never starts ssh.exe in tests, and its Refresh never knocks on a real port:
    Connect lands here as (address, SshInfo), in a tab or a separate window, and every port
    says nothing until a test gives its own answers. A tab runs Windows' own cmd.exe in place
    of ssh.exe, so it has a live program on its pseudo console that never reaches the network
    and ends when the tab closes."""
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
    from earlier tests pile up, so the theme tests took minutes at the end of the run."""
    items.sort(key=lambda item: "test_themes.py" not in item.nodeid)  # keeps the rest in order
