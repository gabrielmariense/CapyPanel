import os
from collections.abc import Iterator

import pytest

# Run Qt without a screen, so UI tests work in CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    yield app


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Theme tests first. A theme switch restyles every window still alive, and closed windows
    from earlier tests pile up, so the theme tests took minutes at the end of the run."""
    items.sort(key=lambda item: "test_themes.py" not in item.nodeid)  # keeps the rest in order
