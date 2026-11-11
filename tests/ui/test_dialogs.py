import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QPushButton

from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.ui import hosts as hosts_ui
from capypanel.ui.dialogs import ok_cancel, quiet_default, run_modal
from capypanel.ui.groups import ManageGroupsDialog
from capypanel.ui.hosts import HostDialog
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


def _main_button(box: QDialogButtonBox) -> QPushButton:
    button = box.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None
    return button


def test_a_window_ends_in_what_it_does_not_in_ok(qapp: QApplication) -> None:
    plain = QDialog()
    assert _main_button(ok_cancel(plain)).text() == "OK"  # no verb given: Qt's own
    box = ok_cancel(plain, "Save")
    assert _main_button(box).text() == "Save"
    _main_button(box).click()
    assert plain.result() == QDialog.DialogCode.Accepted
    hl, group = HostList().add_group("Front desks")
    hl, host = hl.add_host("DESK-01", group.id)
    assert _main_button(HostDialog(None, hl).buttons).text() == "Add"
    assert _main_button(HostDialog(None, hl, host).buttons).text() == "Save"
    groups = ManageGroupsDialog(None, hl)
    assert _main_button(groups.box).text() == "Save"
    groups.show()
    qapp.processEvents()
    # As every list screen: the buttons in a row under the list, not a column beside it.
    row = (groups.up_button, groups.down_button, groups.move_button, groups.sort_button)
    assert len({b.y() for b in row}) == 1 and row[0].y() >= groups.tree.geometry().bottom()
    assert [b.x() for b in row] == sorted(b.x() for b in row)
    groups.close()
    assert hl.hosts_in(NO_GROUP) == ()


def test_only_a_window_s_main_action_is_the_filled_button(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    close = QPushButton("Close")
    quiet_default(close)
    assert close.isDefault() and close.objectName() == "quietDefault"  # Enter still presses it
    sheet = themes.stylesheet(themes.Registry().find("capypanel-dark"))
    filled = sheet.split("QPushButton:default {")[1].split("}")[0]
    quiet = sheet.split("QPushButton#quietDefault:default {")[1].split("}")[0]
    assert "#ffffff" in filled and "#ffffff" not in quiet  # plain text on a plain button
    seen: list[QMessageBox] = []

    def answer(box: QMessageBox) -> int:
        seen.append(box)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", answer)
    parent = QDialog()  # kept: the box lives as long as its parent
    assert not hosts_ui.confirm(parent, "Remove hosts", "Remove “DESK-01”?", "Remove")
    default = seen[0].defaultButton()
    # A question's Cancel is where Enter goes, and it isn't drawn as the main action.
    assert default is not None and default.objectName() == "quietDefault"
