from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from capypanel.core.hosts.model import Host, HostList
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.sessions import Session
from capypanel.core.remote.status import Status
from capypanel.ui.hosts_tool.details import HostDetails, HostDetailsPanel
from capypanel.ui.hosts_tool.host_state import Facts
from capypanel.ui.list_workspace.details import breakable, marked
from capypanel.ui.themes import engine as themes


def _details(
    tags: tuple[str, ...] = (),
    notes: str = "",
    status: tuple[Status, datetime] | None = None,
    users: tuple[list[Session] | tuple[()] | None, RemoteError | None, datetime] | None = None,
) -> HostDetails:
    hl, group = HostList().add_group("Front desk")
    address = "PC-0142.corp.example.net"
    hl, host = hl.add_host("Reception 01", group.id, address=address, tags=tags, notes=notes)
    return HostDetails(host, "Headquarters › Front desk", "Remote Desktop", status, users)


def _texts(pane: HostDetailsPanel) -> list[str]:
    return [label.text() for label in pane.findChildren(QLabel) if label.isVisibleTo(pane)]


def _click(widget: QLabel) -> None:
    point = QPointF(5, 5)
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        event = QMouseEvent(
            kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )  # fmt: skip
        QApplication.sendEvent(widget, event)


def test_every_section_shows_even_when_empty(qapp: QApplication) -> None:
    pane = HostDetailsPanel()
    pane.show_host(_details(), 1)
    texts = _texts(pane)
    for heading in ("Connection", "Logged on", "Tags", "Notes"):
        assert heading in texts
    assert "Not checked" in texts and texts.count("—") == 2
    assert pane.profile_button.value_text() == "Remote Desktop"


def test_logged_on_users_active_first_with_the_check_time(qapp: QApplication) -> None:
    now = datetime.now()
    sessions = [
        Session("mlopez", "EXAMPLE", "rdp", "disconnected", now - timedelta(hours=2), "LAPTOP-07"),
        Session("jsmith", "EXAMPLE", "console", "active", now),
    ]
    pane = HostDetailsPanel()
    pane.show_host(_details(users=(sessions, None, now)), 1)
    assert pane.shown_value("users") == "EXAMPLE\\jsmith\nEXAMPLE\\mlopez"
    assert any(t.startswith("Logged on (2) · ") for t in _texts(pane))
    assert {"Active", "Disconnected"} <= set(_texts(pane))


def test_logged_on_says_nobody_or_why_the_check_failed(qapp: QApplication) -> None:
    now = datetime.now()
    pane = HostDetailsPanel()
    pane.show_host(_details(users=((), None, now)), 1)
    assert "No one logged on" in _texts(pane)
    pane.show_host(_details(users=(None, RemoteError(Reason.UNREACHABLE), now)), 1)
    assert "Unreachable" in _texts(pane)


def test_the_status_line_says_when_it_was_checked(qapp: QApplication) -> None:
    pane = HostDetailsPanel()
    pane.show_host(_details(), 1)
    assert "Not checked: use Refresh" in _texts(pane)
    pane.show_host(_details(status=(Status.ONLINE, datetime.now())), 1)
    assert any(t.startswith("Online · checked ") for t in _texts(pane))


def test_a_click_copies_a_value_and_the_window_is_told(qapp: QApplication) -> None:
    pane = HostDetailsPanel()
    told: list[str] = []
    pane.copied.connect(told.append)
    pane.show_host(_details(tags=("kiosk", "2nd floor")), 1)
    _click(pane._values["tags"][1])
    assert QGuiApplication.clipboard().text() == "2nd floor" and told == ["2nd floor"]
    _click(pane._values["name"][0])
    assert QGuiApplication.clipboard().text() == "Reception 01"


def test_notes_wrap_and_mark_the_search(qapp: QApplication) -> None:
    notes = "Reboot after updates.\nThen REBOOT the kiosk app."
    assert marked(notes, "reboot").count("<span") == 2
    assert "<br>" in marked(notes, "")
    pane = HostDetailsPanel()
    pane.show_host(_details(notes=notes), 1, needle="reboot")
    assert pane.shown_value("notes") == notes


def test_a_long_address_never_widens_the_pane(qapp: QApplication) -> None:
    address = "kiosk-12-lobby-north-wing.branch-office.corp.example.internal"
    assert breakable(address) != address
    assert breakable("PC-0142") == "PC-0142"


def test_the_same_item_drawn_again_keeps_its_scroll_position(qapp: QApplication) -> None:
    pane = HostDetailsPanel()
    pane.resize(260, 160)
    pane.show()
    shown = _details(notes="\n".join(f"line {n}" for n in range(40)))
    pane.show_host(shown, 1)
    qapp.processEvents()
    bar = pane._scroll.verticalScrollBar()  # pyright: ignore[reportPrivateUsage]
    bar.setValue(bar.maximum())
    pane.show_host(shown, 1)
    qapp.processEvents()
    assert bar.value() == bar.maximum() > 0
    other = HostDetails(Host(id="other", name="Other", group=""), "", "")
    pane.show_host(other, 1)
    qapp.processEvents()
    assert bar.value() == 0
    pane.close()


def test_a_pc_that_did_not_answer_says_so_once(qapp: QApplication) -> None:
    now = datetime.now()
    gone = RemoteError(Reason.UNREACHABLE)
    facts = Facts(now, reading=False, quick_error=gone, pc_error=gone)
    why = "Not reached: the PC didn't answer"
    pane = HostDetailsPanel()
    pane.show_host(replace(_details(users=(None, gone, now)), facts=facts), 1)
    texts = _texts(pane)
    assert texts.count(why) == 1 and "Unreachable" in texts and "Last restart" not in texts
    offline = _details(status=(Status.OFFLINE, now), users=(None, gone, now))
    pane.show_host(replace(offline, facts=facts), 1)
    texts = _texts(pane)
    assert any(t.startswith("Offline · checked ") for t in texts)
    assert why not in texts and "Unreachable" not in texts
    assert texts.count("—") == 4
    half = Facts(now, reading=False, restarted=now, pc_error=TimeoutError())
    pane.show_host(replace(_details(status=(Status.ONLINE, now)), facts=half), 1)
    texts = _texts(pane)
    assert "Last restart" in texts and "Model" in texts
    assert texts.count("Couldn't read: it took too long to answer") == 5


def _apart(one: QColor, other: QColor) -> int:
    return sum(abs(a - b) for a, b in ((one.red(), other.red()), (one.green(), other.green()),
                                       (one.blue(), other.blue())))  # fmt: skip


def _ink(button: QToolButton) -> tuple[list[tuple[int, int]], dict[int, list[int]], QImage]:
    image = button.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    image.setDevicePixelRatio(1)
    back = QColor(image.pixel(3, image.height() - 4))
    rows: dict[int, list[int]] = {}
    for x in range(3, image.width() - 3):
        for y in range(button.iconSize().height() + 4, image.height() - 2):
            if _apart(QColor(image.pixel(x, y)), back) > 90:
                rows.setdefault(x, []).append(y)
    columns = sorted(rows)
    runs, start = [], columns[0]
    for left, right in zip(columns, columns[1:], strict=False):
        if right - left > 2:
            runs.append((start, left))
            start = right
    return [*runs, (start, columns[-1])], rows, image


@pytest.mark.usefixtures("default_theme_after")
@pytest.mark.parametrize("theme", [themes.DEFAULT_THEME, themes.BUILTIN[3]], ids=lambda t: t.id)
def test_users_and_power_draw_their_chevron_beside_the_word_in_its_colour(
    qapp: QApplication, theme: themes.Theme
) -> None:
    themes.apply(theme)
    pane = HostDetailsPanel()
    pane.show_host(_details(), 1)
    power, users = pane.buttons["power"], pane.buttons["users"]
    assert (power.text(), power.isEnabled(), users.text(), users.isEnabled()) == (
        "Power", True, "Users", False,
    )  # fmt: skip
    amber = QColor(themes.status_color("attention"))
    grey = users.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert grey != amber
    for button, color in ((power, amber), (users, grey)):
        runs, rows, image = _ink(button)
        word, mark = (runs[0][0], runs[-2][1]), runs[-1]
        # The test platform draws each letter as a box, with more room after it than a letter.
        assert 3 <= mark[0] - word[1] <= 12 and mark[1] - mark[0] <= 10
        assert abs((word[0] + mark[1]) / 2 - image.width() / 2) <= 3
        word_rows = [y for x in range(word[0], word[1] + 1) for y in rows.get(x, [])]
        mark_rows = [y for x in range(mark[0], mark[1] + 1) for y in rows[x]]
        middle = (min(word_rows) + max(word_rows)) / 2
        assert abs((min(mark_rows) + max(mark_rows)) / 2 - middle) <= 2
        tip = QColor(image.pixel((mark[0] + mark[1]) // 2, max(mark_rows)))
        assert _apart(tip, color) <= 60
