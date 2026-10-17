import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from capypanel.ui.dialogs import run_modal
from capypanel.ui.themes import engine as themes


def _done(dialog: QDialog) -> int:
    return 0


def test_a_closed_window_is_freed_unless_the_theme_changed_while_it_was_open(
    qapp: QApplication,
) -> None:
    class Quick(QDialog):
        exec = _done  # type: ignore[assignment]

    class Switching(QDialog):
        def exec(self) -> int:  # type: ignore[override]
            themes.apply(themes.DEFAULT_THEME)  # e.g. Settings > Theme
            return 0

    quick, switching = Quick(), Switching()
    run_modal(quick)
    run_modal(switching)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(quick)  # freed: theme switches no longer restyle it
    assert shiboken6.isValid(switching)  # kept: deleting a restyled window can crash Qt
