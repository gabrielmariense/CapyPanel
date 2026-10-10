from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from capypanel.core.hosts.model import HostList
from capypanel.core.remote.sessions import Reason, Session, SessionsError
from capypanel.core.remote.status import Status
from capypanel.ui.main_window.details import DetailsPane, HostDetails, breakable, marked


def _details(
    tags: tuple[str, ...] = (),
    notes: str = "",
    status: tuple[Status, datetime] | None = None,
    users: tuple[list[Session] | tuple[()] | None, SessionsError | None, datetime] | None = None,
) -> HostDetails:
    hl, group = HostList().add_group("Front desk")
    address = "PC-0142.corp.example.net"
    hl, host = hl.add_host("Reception 01", group.id, address=address, tags=tags, notes=notes)
    return HostDetails(host, "Headquarters › Front desk", "Remote Desktop", status, users)


def _texts(pane: DetailsPane) -> list[str]:
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
    pane = DetailsPane()
    pane.show_host(_details(), 1)
    texts = _texts(pane)
    for heading in ("Connection", "Logged on", "Tags", "Notes"):
        assert heading in texts  # the layout never changes from host to host
    assert "Not checked" in texts and texts.count("—") == 2  # no tags, no notes
    assert pane.shown_value("profile") == "Remote Desktop"


def test_logged_on_users_active_first_with_the_check_time(qapp: QApplication) -> None:
    now = datetime.now()
    sessions = [
        Session("mlopez", "EXAMPLE", "rdp", "disconnected", now - timedelta(hours=2), "LAPTOP-07"),
        Session("jsmith", "EXAMPLE", "console", "active", now),
    ]
    pane = DetailsPane()
    pane.show_host(_details(users=(sessions, None, now)), 1)
    assert pane.shown_value("users") == "EXAMPLE\\jsmith\nEXAMPLE\\mlopez"
    assert any(t.startswith("Logged on (2) · ") for t in _texts(pane))
    assert {"Active", "Disconnected"} <= set(_texts(pane))


def test_logged_on_says_nobody_or_why_the_check_failed(qapp: QApplication) -> None:
    now = datetime.now()
    pane = DetailsPane()
    pane.show_host(_details(users=((), None, now)), 1)
    assert "No one logged on" in _texts(pane)
    pane.show_host(_details(users=(None, SessionsError(Reason.UNREACHABLE), now)), 1)
    assert "Unreachable" in _texts(pane)


def test_the_status_line_says_when_it_was_checked(qapp: QApplication) -> None:
    pane = DetailsPane()
    pane.show_host(_details(), 1)
    assert "Not checked: use Refresh" in _texts(pane)
    pane.show_host(_details(status=(Status.ONLINE, datetime.now())), 1)
    assert any(t.startswith("Online · checked ") for t in _texts(pane))


def test_a_click_copies_a_value_and_the_window_is_told(qapp: QApplication) -> None:
    pane = DetailsPane()
    told: list[str] = []
    pane.copied.connect(told.append)
    pane.show_host(_details(tags=("kiosk", "2nd floor")), 1)
    _click(pane._values["tags"][1])
    assert QGuiApplication.clipboard().text() == "2nd floor" and told == ["2nd floor"]


def test_notes_wrap_and_mark_the_search(qapp: QApplication) -> None:
    notes = "Reboot after updates.\nThen REBOOT the kiosk app."
    assert marked(notes, "reboot").count("<span") == 2  # every match, in any case
    assert "<br>" in marked(notes, "")  # line breaks kept
    pane = DetailsPane()
    pane.show_host(_details(notes=notes), 1, needle="reboot")
    assert pane.shown_value("notes") == notes  # copied as typed, without the marks


def test_a_long_address_never_widens_the_pane(qapp: QApplication) -> None:
    address = "kiosk-12-lobby-north-wing.branch-office.corp.example.internal"
    assert breakable(address) != address  # it may wrap at any character
    assert breakable("PC-0142") == "PC-0142"  # short words are left alone
