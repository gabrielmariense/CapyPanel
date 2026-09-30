"""The tag field: chips made with Enter or commas, removed with × or Backspace."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from capypanel.core.hosts.model import HostList
from capypanel.ui.hosts import HostDialog, TagEdit


@pytest.fixture
def field(qapp: QApplication) -> TagEdit:
    return TagEdit(known=["kiosk", "floor-3"])


def _type(field: TagEdit, text: str) -> None:
    QTest.keyClicks(field.input, text)


def _enter(field: TagEdit) -> None:
    QTest.keyClick(field.input, Qt.Key.Key_Return)


def test_enter_and_commas_make_chips(field: TagEdit) -> None:
    _type(field, "reception")
    _enter(field)
    _type(field, "floor-2, printer,")
    assert field.tags() == ("reception", "floor-2", "printer")
    assert field.input.text() == ""


def test_known_tags_keep_their_spelling_and_duplicates_are_ignored(field: TagEdit) -> None:
    field.add_text("KIOSK, Floor-3, kiosk")
    assert field.tags() == ("kiosk", "floor-3")


def test_backspace_on_an_empty_box_removes_the_last_chip(field: TagEdit) -> None:
    field.add_text("a, b")
    QTest.keyClick(field.input, Qt.Key.Key_Backspace)
    assert field.tags() == ("a",)


def test_the_x_button_removes_its_chip(field: TagEdit) -> None:
    field.add_text("a, b, c")
    [chip_b] = [c for c in field._chips if c.text == "b"]
    chip_b.remove_button.click()
    assert field.tags() == ("a", "c")


def test_text_still_being_typed_is_kept(field: TagEdit) -> None:
    field.add_text("a")
    _type(field, "half-typed")
    assert field.tags() == ("a", "half-typed")  # e.g. the user clicks OK without pressing Enter


def test_enter_makes_a_chip_but_on_an_empty_box_presses_ok(qapp: QApplication) -> None:
    hl, hq = HostList().add_group("Hosts")
    dialog = HostDialog(None, hl, default_group=hq.id)
    dialog.name.setText("PC-1")
    dialog.show()
    dialog.tags.input.setFocus()
    accepted: list[bool] = []
    dialog.accepted.connect(lambda: accepted.append(True))
    QTest.keyClicks(dialog.tags.input, "kiosk")
    QTest.keyClick(dialog.tags.input, Qt.Key.Key_Return)
    assert dialog.values().tags == ("kiosk",) and not accepted  # made a chip, didn't close
    QTest.keyClick(dialog.tags.input, Qt.Key.Key_Return)
    assert accepted  # empty box: Enter confirms the dialog as usual
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok) is not None


def test_many_tags_wrap_onto_more_lines(field: TagEdit) -> None:
    field.resize(300, 30)
    one_line = field.heightForWidth(300)
    field.add_text(", ".join(f"tag-number-{n}" for n in range(8)))
    assert field.heightForWidth(300) > one_line * 2
