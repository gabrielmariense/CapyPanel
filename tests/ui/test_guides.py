"""First-run guides: the cards beside real controls, when they show, and the User profiles
warning before its first use. Tests have no screen, so nothing shows on its own here: each
test starts what it checks."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from capypanel.core import settings
from capypanel.ui import guides
from capypanel.ui.guides import Guide, Step
from capypanel.ui.main_window import window as window_module
from capypanel.ui.profiles_tool import first_use


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[CapyWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    win = CapyWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.resize(1280, 760)
    win.show()
    QApplication.processEvents()
    yield win
    win.close()


def _settle() -> None:
    for _ in range(5):
        QApplication.processEvents()


def test_nothing_shows_on_its_own_without_a_screen(window: CapyWindow) -> None:
    assert not guides.on_screen(window)  # tests and screenshot scripts: no person to read it
    window.show_tool("hosts")
    _settle()
    assert window.guides.running == "" and window.guides.card.isHidden()


def test_someone_new_gets_every_guide_and_someone_upgrading_none_of_them() -> None:
    assert guides.seen_from({"schema": 1}) == []
    upgrading = {"schema": 1, "window_geometry": "AAA"}  # CapyPanel ran here before
    assert guides.seen_from(upgrading) == list(guides.FIRST_STEPS)
    assert upgrading["guides"] == list(guides.FIRST_STEPS)  # kept
    kept = {"guides": ["home"], "window_geometry": "AAA"}
    assert guides.seen_from(kept) == ["home"]


def test_home_s_guide_steps_through_and_is_kept_as_seen(window: CapyWindow) -> None:
    runner = window.guides
    runner.show(window._home_guide())
    _settle()
    card = runner.card
    assert runner.running == "home" and not card.isHidden()
    assert card.title.text() == "Welcome to CapyPanel" and not card.mascot.isHidden()
    assert card.dots.text() == "● ○ ○" and card.back_button.isHidden()
    assert not runner.outline.isHidden()
    outline = runner.outline.geometry()
    rail = QRect(window.rail.mapTo(window, QPoint(0, 0)), window.rail.size())
    assert outline.contains(rail)  # the outline goes round the rail
    assert not card.geometry().intersects(rail)  # and the card beside it, not over it
    assert window.rect().contains(card.geometry())
    card.next_button.click()
    assert card.title.text() == "Every tool works the same way" and card.mascot.isHidden()
    assert card.dots.text() == "○ ● ○" and not card.back_button.isHidden()
    card.next_button.click()
    assert card.next_button.text() == "Done" and card.skip_button.isHidden()
    assert "getting-started/" in card.text.text()  # the last card links to its docs page
    card.next_button.click()
    assert runner.running == "" and card.isHidden() and runner.seen("home")
    assert window.prefs["guides"] == ["home"]


def test_skip_counts_as_seen_and_leaving_the_screen_doesn_t(window: CapyWindow) -> None:
    runner = window.guides
    runner.show(window.hosts.guide())
    runner.card.skip_button.click()
    assert runner.seen("hosts")
    window.prefs["guides"].clear()
    runner.show(window._home_guide())
    window.show_tool("hosts")  # another screen: Home's guide goes, unseen
    assert runner.running == "" and not runner.seen("home")


def test_a_card_whose_control_is_hidden_shows_beside_its_panel(window: CapyWindow) -> None:
    hidden = window.hosts.details
    guide = Guide("test", lambda: [Step("Hidden", "Its control is out of sight.",
                                        lambda: hidden, lambda: window.hosts)])  # fmt: skip
    window.show_tool("hosts")
    hidden.hide()
    window.guides.show(guide)
    _settle()
    assert not window.guides.card.isHidden() and window.guides.outline.isHidden()
    assert window.rect().contains(window.guides.card.geometry())
    window.guides.stop()
    hidden.show()


def test_a_card_always_fits_in_the_window() -> None:
    room = QRect(0, 0, 1000, 700)
    gap = guides.GAP + guides.OUTLINE
    spot = QRect(10, 10, 50, 50)  # room on its right: the card goes there
    assert guides._card_spot(spot, 300, 150, room) == QPoint(spot.right() + gap, 10)
    edge = QRect(900, 10, 80, 40)  # no room on its right, nor under it: on its left
    left = guides._card_spot(edge, 300, 150, room)
    assert left == QPoint(edge.left() - gap - 300, 10)
    low = QRect(10, 600, 900, 50)  # wide and low: over it
    over = guides._card_spot(low, 300, 150, room)
    assert over == QPoint(10, low.top() - gap - 150)
    huge = guides._card_spot(QRect(0, 0, 1000, 700), 300, 150, room)  # nowhere free
    assert room.contains(QRect(huge.x(), huge.y(), 300, 150))


def test_help_shows_this_screen_s_guide_and_about_shows_them_all_again(
    window: CapyWindow,
) -> None:
    window.show_tool("hosts")
    texts = [a.text() for a in window._help_menu.actions() if a.text()]
    assert texts[0] == "&Guide to this screen"
    window.commands.show_guide.trigger()
    assert window.guides.running == "hosts"
    assert window.guides.card.title.text() == "Your host lists"
    window.guides.card.skip_button.click()
    dialog = window.settings_dialog()
    dialog.about.guides_button.click()
    assert window.prefs["guides"] == []
    dialog.close()


def test_every_tool_s_guide_ends_on_its_docs_page(window: CapyWindow) -> None:
    for tool_id, page in (("hosts", "hosts/host-lists/"), ("profiles", "profiles/user-profiles/")):
        guide = window.tools[tool_id].guide()
        assert guide is not None and guide.docs == page and len(list(guide.steps())) >= 3
        assert (Path("docs") / page.rstrip("/")).with_suffix(".md").exists()


def test_the_user_profiles_warning_needs_its_tick(qapp: QApplication) -> None:
    warning = first_use.FirstUseWarning(None)
    assert not warning.go_on.isEnabled() and warning.cancel.isDefault()
    words = " ".join(label.text() for label in warning.findChildren(QLabel))
    assert "C:\\Users" in words and "registry" in words and "can't be brought back" in words
    warning.understood.setChecked(True)
    assert warning.go_on.isEnabled()
    warning.understood.setChecked(False)
    assert not warning.go_on.isEnabled()
    warning.close()


def test_user_profiles_asks_first_and_cancel_keeps_you_where_you_were(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window_module, "on_screen", lambda _window: True)  # as for a person
    monkeypatch.setattr(guides, "on_screen", lambda _window: True)
    answers = iter([QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted])
    asked: list[bool] = []

    def answer(dialog: QDialog) -> int:
        asked.append(isinstance(dialog, first_use.FirstUseWarning))
        return next(answers)

    monkeypatch.setattr(first_use, "run_modal", answer)
    profiles = window.tools["profiles"]
    window.show_tool("hosts")
    window.show_tool("profiles")  # Cancel
    assert asked == [True] and window.shown_tool() is window.hosts
    assert profiles.first_use_pending()
    window.show_tool("profiles")  # ticked and continued
    assert window.shown_tool() is profiles and not profiles.first_use_pending()
    window.show_tool("hosts")
    window.show_tool("profiles")  # never again
    assert asked == [True, True]


def test_a_start_on_user_profiles_waits_for_its_warning(qapp: QApplication, tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    prefs = {"schema": 1, settings.START_KEY: "profiles"}
    win = CapyWindow(settings.resolve_paths(tmp_path), prefs)
    assert win.shown_tool() is None  # Home: the warning comes when the person opens it
    win.close()
