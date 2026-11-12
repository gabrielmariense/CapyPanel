"""First-run guides: the cards beside real controls, when they show, and the User profiles
warning before its first use. Tests have no screen, so nothing shows on its own here: each
test starts what it checks."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from capywindow import CapyWindow
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

from capypanel.core import settings
from capypanel.ui import guides
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.guides import Guide, Step
from capypanel.ui.list_workspace.panels import is_sample
from capypanel.ui.list_workspace.workspace import SAMPLE_ID
from capypanel.ui.main_window import window as window_module
from capypanel.ui.printers_tool import tool as printer_tool_module
from capypanel.ui.printers_tool.tool import PrintersTool
from capypanel.ui.profiles_tool import first_use
from capypanel.ui.profiles_tool.tool import ProfilesTool


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
    assert card.dots.text() == "● ○ ○ ○" and card.back_button.isHidden()
    assert not runner.shade.isHidden() and runner.shade.geometry() == window.rect()
    assert runner.shade.holes == []  # a welcome points at nothing: in the middle
    middle = card.geometry().center() - window.rect().center()
    assert abs(middle.x()) <= 1 and abs(middle.y()) <= 1
    card.next_button.click()
    assert card.title.text() == "Three tools" and card.mascot.isHidden()
    tiles = [QRect(t.mapTo(window, QPoint(0, 0)), t.size()) for t in window.home.tiles]
    shown = [
        t for t, tile in zip(tiles, window.home.tiles, strict=True) if tile.isVisibleTo(window)
    ]
    assert runner.shade.holes == shown  # every tile outlined, or none: never just one
    card.next_button.click()
    assert card.title.text() == "The sidebar"
    assert card.dots.text() == "○ ○ ● ○" and not card.back_button.isHidden()
    rail = QRect(window.rail.mapTo(window, QPoint(0, 0)), window.rail.size())
    assert runner.shade.holes == [rail]  # the rail stays bright, outlined
    assert not card.geometry().intersects(rail)  # and the card beside it, not over it
    assert window.rect().contains(card.geometry())
    card.next_button.click()
    assert card.title.text() == "Help"
    help_title = window.menuBar().actionGeometry(window._help_menu.menuAction())
    assert runner.shade.holes == [
        QRect(window.menuBar().mapTo(window, help_title.topLeft()), help_title.size())
    ]  # just "Help" on the menu bar
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
    assert not window.guides.card.isHidden() and window.guides.shade.holes == []
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


def test_help_shows_this_screen_s_guide_and_all_of_them_again(window: CapyWindow) -> None:
    window.show_tool("hosts")
    texts = [a.text() for a in window._help_menu.actions() if a.text()]
    assert texts[:2] == ["&Guide to this screen", "&Show all the guides again"]
    window.commands.show_guide.trigger()
    assert window.guides.running == "hosts"
    assert window.guides.card.title.text() == "Your lists"
    window.guides.card.skip_button.click()
    window.commands.show_all_guides.trigger()
    assert window.prefs["guides"] == []


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


def _key(kind: QEvent.Type = QEvent.Type.KeyPress) -> QKeyEvent:
    return QKeyEvent(kind, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a")


def test_while_a_guide_runs_only_the_card_takes_clicks_and_keys(window: CapyWindow) -> None:
    runner = window.guides
    runner.show(window._home_guide())
    _settle()
    bar = window.statusBar()
    middle = bar.mapTo(window, bar.rect().center())
    assert window.childAt(middle) is runner.shade  # under the shade: no click reaches it
    assert runner.eventFilter(window.hosts.table, _key())  # nor a key
    assert not runner.eventFilter(runner.card.next_button, _key())  # the card's own do
    next_button = runner.card.next_button
    assert window.childAt(next_button.mapTo(window, QPoint(5, 5))) is next_button  # on top
    runner.card.skip_button.click()
    assert runner.shade.isHidden() and not runner.eventFilter(window.hosts.table, _key())


def test_a_step_that_asks_for_a_click_lets_its_control_take_it(window: CapyWindow) -> None:
    button = QPushButton("Try me", window.centralWidget())
    button.move(40, 40)
    button.show()
    guide = Guide("test", lambda: [Step("Click it", "Go on.", lambda: button, click=True)])
    window.guides.show(guide)
    _settle()
    centre = button.mapTo(window, button.rect().center())
    assert window.childAt(centre) is button  # through the shade's hole
    assert not window.guides.eventFilter(button, _key())
    window.guides.stop()
    button.deleteLater()


def test_the_card_is_as_tall_as_its_wrapped_words(window: CapyWindow) -> None:
    long = " ".join(["Every word of this card has to show, the last one too."] * 4)
    window.guides.show(Guide("test", lambda: [Step("Long", long, lambda: window.rail)]))
    _settle()
    card = window.guides.card
    text = card.text
    assert text.height() >= text.heightForWidth(text.width())  # no line cut off
    assert card.geometry().contains(text.geometry().translated(card.pos()))
    window.guides.stop()


def test_a_card_keeps_clear_of_the_panel_it_talks_about() -> None:
    room = QRect(0, 0, 1000, 700)
    spot = QRect(200, 100, 300, 400)  # the table
    details = QRect(520, 0, 480, 700)  # on its right: where the card would go first
    point = guides._card_spot(spot, 300, 150, room, [spot, details])
    card = QRect(point.x(), point.y(), 300, 150)
    assert room.contains(card) and not card.intersects(details) and not card.intersects(spot)


def test_with_no_free_place_the_card_hides_the_least_it_can() -> None:
    room = QRect(0, 0, 1000, 700)
    table = QRect(300, 80, 400, 600)  # what it points at
    details = QRect(720, 0, 280, 700)  # a panel it must keep clear of
    point = guides._card_spot(table, 360, 150, room, [table, details])
    card = QRect(point.x(), point.y(), 360, 150)
    beside = QRect(table.right() + guides.GAP + guides.OUTLINE, table.top(), 360, 150)
    assert room.contains(card)
    assert guides._covered(card, [table, details]) < guides._covered(beside, [table, details])
    assert not card.intersects(details)  # the narrow left side, over a corner of the table


def test_the_hosts_guide_shows_a_sample_pc_that_is_never_saved_or_read(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    hosts = window.hosts
    window.show_tool("hosts")
    doc = hosts.document
    assert doc is not None
    saved = doc.path.read_bytes()
    checked: list[str] = []
    monkeypatch.setattr(hosts, "_refusing_last", lambda targets: checked.extend(targets) or [])
    window.commands.show_guide.trigger()
    _settle()
    assert hosts.sample_shown() and hosts.table.selected_ids() == [SAMPLE_ID]
    sample = hosts.document.hosts.host(SAMPLE_ID)  # type: ignore[union-attr]
    assert sample is not None and sample.address.startswith("192.0.2.") and sample.tags
    assert hosts.nav.tags.topLevelItemCount() >= 1  # its tag, for the Tags card
    hosts.check_hosts([sample], status=True, users=False)
    assert checked == []  # nothing is read from it
    titles = []
    while not window.guides.card.isHidden():
        titles.append(window.guides.card.title.text())
        window.guides.card.next_button.click()
    assert "Tags" in titles and titles[-1] == "View"  # every tool's guide ends on View
    assert not hosts.sample_shown() and hosts.document.hosts.host(SAMPLE_ID) is None  # type: ignore[union-attr]
    assert doc.path.read_bytes() == saved  # the file never had it


def test_the_printers_guide_shows_a_sample_printer_that_is_never_saved_or_read(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    printers = window.tools["printers"]
    assert isinstance(printers, PrintersTool)
    window.show_tool("printers")
    doc = printers.document
    assert doc is not None
    saved = doc.path.read_bytes()
    runs: list[object] = []
    monkeypatch.setattr(printer_tool_module, "PrinterRun", lambda *a, **k: runs.append(a))
    opened: list[object] = []
    monkeypatch.setattr(printer_tool_module.QDesktopServices, "openUrl", opened.append)
    window.commands.show_guide.trigger()
    _settle()
    assert printers.sample_shown() and printers.table.selected_ids() == [SAMPLE_ID]
    sample = printers.document.hosts.host(SAMPLE_ID)  # type: ignore[union-attr]
    assert sample is not None and sample.address.startswith("192.0.2.") and sample.tags
    assert printers.nav.tags.topLevelItemCount() >= 1  # its tag, for the Tags card
    samples = [h for h in printers.document.hosts.hosts if is_sample(h.id)]  # type: ignore[union-attr]
    words = [printers.table._rows[h.id].text(printers.table.STATUS) for h in samples]
    assert words == ["Idle", "Toner low", "Paper jam", "Offline"]  # one per status, made up
    top = printers.table.topLevelItem(0)
    assert top is not None and top.data(0, ROLE_ID) == SAMPLE_ID  # on top of the table
    assert printers.sample_row(window) is not None  # for "Your printers" to outline
    assert len(printers._attention) >= 3  # the rail's count and the strip show them
    printers.check_printers(samples)  # Refresh, the button's or a row's
    printers._auto_refresh()  # Refresh on its own waits until the guide ends
    printers.table.select_ids([h.id for h in samples])
    printers.open_web_pages()  # Web page, a double-click, Enter
    assert runs == [] and opened == []  # nothing ever reaches their addresses
    printers.table.select_ids([SAMPLE_ID])
    titles = []
    while not window.guides.card.isHidden():
        titles.append(window.guides.card.title.text())
        window.guides.card.next_button.click()
    assert titles[:2] == ["Your printer lists", "Tags"] and titles[-1] == "View"
    assert not printers.sample_shown()
    assert printers.document.hosts.host(SAMPLE_ID) is None  # type: ignore[union-attr]
    assert not any(is_sample(k) for k in printers._checked)  # their made-up results go too
    assert not any(is_sample(k) for k in printers._attention)
    assert doc.path.read_bytes() == saved  # the file never had it


def test_the_user_profiles_guide_opens_a_sample_tab_and_closes_it(
    window: CapyWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    profiles = window.tools["profiles"]
    assert isinstance(profiles, ProfilesTool)
    monkeypatch.setattr(profiles, "first_use_pending", lambda: False)
    window.show_tool("profiles")
    window.commands.show_guide.trigger()
    _settle()
    assert window.guides.running == "profiles"
    assert SAMPLE_ID in profiles.tabs.host_keys()  # a tab to point at, never read from a PC
    page = profiles._pages[SAMPLE_ID]
    assert page.scan is not None and len(page.scan.profiles) == 2
    assert profiles.tabs.current() != SAMPLE_ID  # it starts on the Hosts tab
    card = window.guides.card
    while card.title.text() != "The profiles":
        card.next_button.click()
    assert profiles.tabs.current() == SAMPLE_ID  # then shows the sample's own tab, scanned
    card.back_button.click()
    assert profiles.tabs.current() != SAMPLE_ID  # and Back goes back to the Hosts tab
    window.guides.card.skip_button.click()
    assert SAMPLE_ID not in profiles.tabs.host_keys() and SAMPLE_ID not in profiles._kept
    assert window.hosts.document.hosts.host(SAMPLE_ID) is None  # type: ignore[union-attr]


def test_a_guide_shows_hidden_panels_and_puts_its_sample_on_top(window: CapyWindow) -> None:
    hosts = window.hosts
    window.show_tool("hosts")
    tags = hosts._list_commands.show_tags
    if tags.isChecked():
        tags.trigger()  # this person hid the Tags panel
    assert not hosts.nav.tags.isVisibleTo(window)
    window.commands.show_guide.trigger()
    _settle()
    assert hosts.nav.tags.isVisibleTo(window)  # shown for the Tags card
    top = hosts.table.topLevelItem(0)
    assert top is not None and top.data(0, ROLE_ID) == SAMPLE_ID  # first, whatever the order
    card = window.guides.card
    while card.title.text() != "Details":
        card.next_button.click()
    row = hosts.sample_row(window)
    assert row is not None and row in window.guides.shade.holes  # its row outlined too
    card.skip_button.click()
    assert not tags.isChecked() and not hosts.nav.tags.isVisibleTo(window)  # hidden again
