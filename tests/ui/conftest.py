import os
from collections.abc import Iterator

import pytest

# Run Qt without a screen, so UI tests work in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Theme tests first. A theme switch restyles every window still alive, and closed windows
    from earlier tests pile up, so the theme tests took minutes at the end of the run."""
    items.sort(key=lambda item: "test_themes.py" not in item.nodeid)  # keeps the rest in order
