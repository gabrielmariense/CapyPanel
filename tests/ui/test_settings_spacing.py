from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QScrollArea

from capypanel.core import settings
from capypanel.ui.hosts_tool.settings import HostsSettings
from capypanel.ui.settings.pages import Section
from capypanel.ui.settings.window import GUTTER


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    yield win
    win.close()


def test_the_cards_keep_a_gutter_from_the_scroll_bar_and_the_bottom(window: CapyWindow) -> None:
    dialog = window.settings_dialog()
    dialog.show()
    page = dialog.group(HostsSettings).connections  # a long group: it scrolls
    view = page.parentWidget()
    while view is not None and not isinstance(view, QScrollArea):
        view = view.parentWidget()
    assert isinstance(view, QScrollArea)
    dialog.stack.setCurrentWidget(view)
    QApplication.processEvents()
    assert view.verticalScrollBar().maximum() > 0
    holder = view.widget()
    assert holder is not None
    sections = holder.findChildren(Section)
    right = max(s.mapTo(holder, QPoint(s.width(), 0)).x() for s in sections)
    assert holder.width() - right == GUTTER  # the same as left of them
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    bottom = max(s.mapTo(holder, QPoint(0, s.height())).y() for s in sections)
    assert holder.height() - bottom >= GUTTER
