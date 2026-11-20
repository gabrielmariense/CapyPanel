"""Printers' help (0.30): the ? in each of its own windows, and "What does this mean?" on its
warnings and errors, each at its own part or line of the docs. The shared part, the button, the
link and the boxes, is tests/ui/test_help_links.py; the docs' side, every place on its page in
both languages, is tests/docs/test_help_places.py."""

from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox
from test_printer_doc360 import _from_doc360
from test_printer_status import _checked, lab, printers  # noqa: F401  (fixtures)

from capypanel.core.hosts import listfile
from capypanel.core.hosts.model import HostList
from capypanel.core.printers import doc360
from capypanel.core.printers.doc360 import Account, Counter
from capypanel.core.printers.printer import PrinterInfo
from capypanel.core.printers.reading import State
from capypanel.ui import dialogs, help_links
from capypanel.ui.help_links import HelpLink
from capypanel.ui.printers_tool import attention, refresh, status
from capypanel.ui.printers_tool import settings as settings_module
from capypanel.ui.printers_tool.dialog import PrinterDialog
from capypanel.ui.printers_tool.import_printers import ImportPrintersDialog, PrinterFormats
from capypanel.ui.printers_tool.report import PrintersReport
from capypanel.ui.printers_tool.status import Checked, Counted, Reason
from capypanel.ui.printers_tool.tool import PrintersTool

WHEN = datetime(2026, 11, 4, 14, 32)
ACCOUNT = Account("SAMPLE-PARTNER", "EXAMPLE\\user", "sample-password")


def _place_of(window: QDialog) -> str:
    place = window.help_button.place()  # type: ignore[attr-defined]
    help_links.url(place)  # a place not in the list raises here, never as a dead link
    return place


def test_each_printers_window_opens_its_own_part(
    qapp: QApplication,
    printers: PrintersTool,  # noqa: F811
) -> None:
    doc = printers.document
    assert doc is not None
    windows = {
        "printers-add-a-printer": PrinterDialog(None, doc.hosts),
        "printers-checking-set-the-snmp-account": settings_module.CommunityDialog(None),
        "printers-checking-get-page-counts-from-doc360-mps": (
            settings_module.Doc360AccountDialog(None, None)
        ),
        "printers-checking-see-how-much-toner-is-left": settings_module.BarMarksDialog(None, ()),
    }
    v3 = settings_module.V3AccountDialog(None, None)
    assert _place_of(v3) == "printers-checking-set-the-snmp-account"
    for place, window in windows.items():
        assert _place_of(window) == place


def test_the_tool_and_the_windows_it_shares_with_hosts_open_printers_parts(
    printers: PrintersTool,  # noqa: F811
) -> None:
    assert printers.help_place() == "printers/printers/"  # the page's top: F1 and the rail's ?
    import_part = "printers-import-many-printers-at-once"
    assert ImportPrintersDialog.HELP_PLACE == PrinterFormats.HELP_PLACE == import_part
    assert PrintersReport.HELP_PLACE == "printers-export-printers-to-a-spreadsheet"
    for place in (printers.help_place(), import_part, PrintersReport.HELP_PLACE):
        help_links.url(place)


def test_the_question_mark_comes_first_in_the_button_row(qapp: QApplication) -> None:
    window = settings_module.Doc360AccountDialog(None, None)
    window.show()
    qapp.processEvents()
    assert window.help_button.x() < window.save_button.x()
    window.close()


@pytest.mark.parametrize(
    ("checked", "place"),
    [
        (None, ""),
        (Checked(WHEN, offline=True), "printer-offline"),
        (Checked(WHEN, refused="auth"), "printer-refused"),
        (Checked(WHEN, error="bad"), "printer-unreadable"),
        (_checked(state=State.IDLE), ""),  # read: nothing to explain
    ],
)
def test_a_printer_that_didn_t_answer_links_its_line(checked: Checked | None, place: str) -> None:
    assert status.status_place(checked) == place
    if place:
        help_links.url(place)


@pytest.mark.parametrize(
    ("raised", "place"),
    [
        (doc360.Refused("no"), "doc360-login-refused"),
        (doc360.NoAnswer("no"), "doc360-no-answer"),
        (doc360.Changed("no"), "doc360-pages-changed"),
        (doc360.Doc360Error("HTTP 500"), "doc360-error-answer"),
    ],
)
def test_each_doc360_error_has_its_line(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, place: str
) -> None:
    def fail(_account: Account) -> None:
        raise raised

    monkeypatch.setattr(doc360, "read_counters", fail)
    counted = refresh.count(ACCOUNT)
    assert (counted.place, bool(counted.error)) == (place, True)
    help_links.url(place)
    assert refresh.count(None).place == "doc360-no-account"


@pytest.mark.parametrize(
    ("serial", "counters", "place"),
    [
        ("", {"sample0001": Counter(1, 1, 0)}, "doc360-serial-missing"),
        ("SAMPLE0002", {"sample0001": Counter(1, 1, 0)}, "doc360-serial-not-listed"),
        ("SAMPLE0001", {"sample0001": Counter(None, 1, 0)}, "doc360-no-total"),
        ("SAMPLE0001", {"sample0001": Counter(7, 7, 0)}, ""),  # a total: no error
    ],
)
def test_each_reason_doc360_has_no_total_has_its_line(
    serial: str, counters: dict[str, Counter], place: str
) -> None:
    info = PrinterInfo(serial=serial)
    assert status.doc360_place(info, None, Counted(WHEN, counters)) == place
    if place:
        help_links.url(place)


def _links(tool: PrintersTool) -> list[str]:
    return [link._place for link in tool.details.findChildren(HelpLink) if not link.isHidden()]


def test_details_links_a_refused_printer_and_a_doc360_error(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers._checked[printer.id] = Checked(WHEN, refused="auth")
    printers._counted = Counted(WHEN, error="Doc360 MPS didn't answer.", place="doc360-no-answer")
    printers.table.select_ids([printer.id])
    assert _links(printers) == ["printer-refused", "doc360-no-answer"]


def test_details_links_counts_from_an_older_month(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers._checked[printer.id] = _checked(state=State.IDLE)
    printers._counted = Counted(WHEN, {"sample0001": Counter(20_500, 0, 0)}, older=(2026, 10))
    printers.table.select_ids([printer.id])
    assert _links(printers) == ["doc360-month-not-counted"]


def test_a_printer_that_was_read_gets_no_link(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers._checked[printer.id] = _checked(state=State.IDLE)
    printers._counted = Counted(WHEN, {"sample0001": Counter(20_500, 0, 0)})
    printers.table.select_ids([printer.id])
    assert _links(printers) == []


def test_the_warnings_strip_links_the_warnings_part(qapp: QApplication) -> None:
    strip = attention.AttentionStrip()
    strip.show_found([Reason.OFFLINE], only_them=False)
    text = strip._text.text()  # the link reads straight after the message, inside its text
    assert text.startswith("<b>1 printer</b> needs attention")
    assert "What does this mean?" in text and attention.HELP_PLACE in text


def test_credential_manager_s_refusal_links_its_line(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)

    def refused() -> None:
        raise OSError("Access is denied.")

    assert not settings_module._kept_by_windows(None, "SNMP v3 account", refused)  # type: ignore[arg-type]
    [box] = shown
    assert box.text() == (
        "Couldn't save the change in Windows Credential Manager: Access is denied.\n\n"
        "Nothing was changed."
    )
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    assert label is not None and "printers-credential-not-saved" in label.toolTip()


def test_a_host_list_opened_in_printers_links_its_line(
    printers: PrintersTool,  # noqa: F811
    tmp_path: Path,
    help_boxes: list[tuple[str, str]],
) -> None:
    path = tmp_path / "hosts.json"
    listfile.save(path, HostList().add_group("Lab")[0], expected=None, kind="hosts")
    assert not printers.open_list(path)
    assert help_boxes == [(f"“{path}” isn't a printer list.", "printers-not-a-list")]
    help_links.url("printers-not-a-list")
