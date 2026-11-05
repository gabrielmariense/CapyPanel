"""Printers whose page counters come from Doc360 MPS: the Refresh job, Details, the Report and
the account in Settings. Doc360 itself is faked here; tests/core/printers/test_doc360.py
covers the portal's pages."""

from dataclasses import replace
from datetime import datetime

import pytest
from PySide6.QtWidgets import QDialog, QLabel, QPushButton
from test_printer_status import _checked, _wait, lab, printers  # noqa: F401  (fixtures)

from capypanel.core.hosts.model import Host
from capypanel.core.printers import doc360, reading, snmp
from capypanel.core.printers.doc360 import Account, Counter
from capypanel.core.printers.printer import DOC360, PrinterInfo, info_of, with_info
from capypanel.core.printers.reading import State
from capypanel.ui.printers_tool import refresh, status
from capypanel.ui.printers_tool import settings as settings_module
from capypanel.ui.printers_tool import tool as tool_module
from capypanel.ui.printers_tool.status import Counted
from capypanel.ui.printers_tool.tool import PrintersTool

WHEN = datetime(2026, 11, 4, 14, 32)
ACCOUNT = Account("SAMPLE-PARTNER", "EXAMPLE\\user", "sample-password")


def _from_doc360(tool: PrintersTool, serial: str = "SAMPLE0001") -> Host:
    doc = tool.document
    assert doc is not None
    lab_printer = next(h for h in doc.hosts.hosts if h.name == "3F-LAB-01")
    info = replace(info_of(lab_printer), counter_source=DOC360, serial=serial)
    tool._commit(doc.hosts.update_host(with_info(lab_printer, info)))
    found = doc.hosts.host(lab_printer.id)
    assert found is not None
    return found


def _labels(tool: PrintersTool) -> list[str]:
    return [w.text() for w in tool.details.findChildren(QLabel)]


def test_details_and_the_report_show_doc360_s_total(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers._checked[printer.id] = _checked(state=State.IDLE, pages=1_604_394)
    printers._counted = Counted(WHEN, {"sample0001": Counter(20_500, 15_000, 5_500)})
    printers.table.select_ids([printer.id])
    labels = _labels(printers)
    assert "20,500" in labels or "20.500" in labels
    assert not any("1,604,394" in text for text in labels)  # the printer's own isn't the source
    [source] = [t for t in labels if t.startswith("Doc360 MPS · fetched")]
    [total] = [w for w in printers.details.findChildren(QLabel) if w.text() in ("20,500", "20.500")]
    assert "Doc360 reads printers on its own schedule" in total.toolTip()
    assert printers._report_cells(printer.id)[3] == "20500"  # plain digits
    assert source


def test_before_a_refresh_doc360_s_total_is_empty(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers.table.select_ids([printer.id])
    assert "Doc360 MPS" in _labels(printers)
    assert printers._report_cells(printer.id)[3] == ""


@pytest.mark.parametrize(
    ("serial", "counted", "why"),
    [
        ("SAMPLE0002", Counted(WHEN, {"sample0001": Counter(1, 1, 0)}),
         "Doc360 MPS doesn't list serial SAMPLE0002."),
        ("SAMPLE0001", Counted(WHEN, {"sample0001": Counter(None, 1, 0)}),
         "Doc360 MPS has no total for this printer."),
        ("SAMPLE0001", Counted(WHEN, error="Doc360 MPS didn't answer."),
         "Doc360 MPS didn't answer."),
    ],
)  # fmt: skip
def test_why_doc360_has_no_total(
    printers: PrintersTool,  # noqa: F811
    serial: str,
    counted: Counted,
    why: str,
) -> None:
    printer = _from_doc360(printers, serial)
    printers._counted = counted
    printers.table.select_ids([printer.id])
    assert f"Error: {why}" in _labels(printers)
    assert printers._report_cells(printer.id)[3] == "Error"


def test_doc360_matches_the_printer_s_own_serial_when_the_list_has_none() -> None:
    no_serial = PrinterInfo(counter_source=DOC360)
    counted = Counted(WHEN, {"sample0099": Counter(7, 7, 0)})
    read = _checked(serial="SAMPLE0099").reading
    assert status.doc360_pages(no_serial, read, counted) == (7, "")
    assert "Add the printer's serial number" in status.doc360_pages(no_serial, None, counted)[1]


def test_refresh_fetches_doc360_once_beside_the_printers(
    printers: PrintersTool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _from_doc360(printers)
    asked: list[Account] = []

    def fake_counters(account: Account) -> dict[str, Counter]:
        asked.append(account)
        return {"sample0001": Counter(20_500, 15_000, 5_500)}

    def no_answer(*_args: object, **_kw: object) -> reading.Reading:
        raise snmp.NoAnswer("192.0.2.99")

    monkeypatch.setattr(doc360, "read_counters", fake_counters)
    monkeypatch.setattr(reading, "read", no_answer)
    monkeypatch.setattr(tool_module, "doc360_account", lambda: ACCOUNT)
    printers.commands.refresh_shown.trigger()
    _wait(printers)
    assert asked == [ACCOUNT]  # one login for every Doc360 printer
    assert printers._counted is not None
    assert status.doc360_pages(info_of(printer), None, printers._counted) == (20_500, "")


def test_refresh_says_when_the_doc360_account_is_missing(
    printers: PrintersTool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    printer = _from_doc360(printers)

    def must_not_run(_account: Account) -> dict[str, Counter]:
        raise AssertionError("no account: Doc360 isn't asked")

    def no_answer(*_args: object, **_kw: object) -> reading.Reading:
        raise snmp.NoAnswer("192.0.2.99")

    monkeypatch.setattr(doc360, "read_counters", must_not_run)
    monkeypatch.setattr(reading, "read", no_answer)
    printers.commands.refresh_shown.trigger()
    _wait(printers)
    printers.table.select_ids([printer.id])
    assert "Error: No Doc360 MPS account is set." in _labels(printers)

    # A button under it opens the account's window straight from Details.
    [button] = [b for b in printers.details.findChildren(QPushButton)
                if b.objectName() == "doc360Account"]  # fmt: skip
    assert button.text() == "Set the account…"
    opened: list[QDialog] = []

    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, settings_module.Doc360AccountDialog)
        opened.append(dialog)
        dialog.partner.setText(ACCOUNT.partner)
        dialog.user.setText(ACCOUNT.user)
        dialog.password.setText(ACCOUNT.password)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", fill)
    button.click()
    assert len(opened) == 1 and refresh.doc360_account() == ACCOUNT
    assert "Doc360 MPS account saved" in printers._shell.messages[-1]  # type: ignore[attr-defined]


def test_a_refused_login_offers_to_change_the_account(printers: PrintersTool) -> None:  # noqa: F811
    printer = _from_doc360(printers)
    printers._counted = Counted(WHEN, error="Doc360 MPS refused the login.", account=status.REFUSED)
    printers.table.select_ids([printer.id])
    assert "Error: Doc360 MPS refused the login." in _labels(printers)
    [button] = [b for b in printers.details.findChildren(QPushButton)
                if b.objectName() == "doc360Account"]  # fmt: skip
    assert button.text() == "Change the account…"
    printers._counted = Counted(WHEN, error="Doc360 MPS didn't answer.")
    printers.table.select_ids([])
    printers.table.select_ids([printer.id])
    buttons = printers.details.findChildren(QPushButton)
    assert not [b for b in buttons if b.objectName() == "doc360Account" and b.isVisibleTo(printers.details)]  # fmt: skip  # noqa: E501


def test_no_doc360_printer_no_doc360_login(
    printers: PrintersTool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def must_not_run(_account: Account) -> dict[str, Counter]:
        raise AssertionError("no Doc360 printer: Doc360 isn't asked")

    def no_answer(*_args: object, **_kw: object) -> reading.Reading:
        raise snmp.NoAnswer("192.0.2.99")

    monkeypatch.setattr(doc360, "read_counters", must_not_run)
    monkeypatch.setattr(reading, "read", no_answer)
    printers.commands.refresh_shown.trigger()
    _wait(printers)
    assert printers._counted is None


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (doc360.Refused("x"), "refused the login"),
        (doc360.NoAnswer("x"), "didn't answer"),
        (doc360.Changed("x"), "pages changed"),
        (doc360.Doc360Error("x"), "answered with an error"),
        (RuntimeError("bug"), "RuntimeError"),
    ],
)
def test_count_never_raises(monkeypatch: pytest.MonkeyPatch, error: Exception, words: str) -> None:
    def fail(_account: Account) -> dict[str, Counter]:
        raise error

    monkeypatch.setattr(doc360, "read_counters", fail)
    found = refresh.count(ACCOUNT)
    assert words in found.error and not found.counters


def test_settings_keeps_the_doc360_account_in_the_vault_only(
    printers: PrintersTool,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = printers.settings_group()
    group.build()
    page = group.general
    assert page.doc360_row.description.text().startswith("Not set.")

    def fill(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, settings_module.Doc360AccountDialog)
        assert dialog.problem.text() == "Type the partner, as on Doc360's login page."
        dialog.partner.setText("SAMPLE-PARTNER")
        dialog.user.setText("EXAMPLE\\user")
        assert not dialog.save_button.isEnabled()
        assert dialog.problem.text() == "Type the password."
        dialog.password.setText("sample-password")
        assert dialog.save_button.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", fill)
    page.doc360_button.click()
    assert refresh.doc360_account() == ACCOUNT
    assert page.doc360_row.description.text() == (
        "Partner SAMPLE-PARTNER, user EXAMPLE\\user. Kept in Windows Credential Manager."
    )
    assert "sample-password" not in str(printers.prefs)

    def keep(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, settings_module.Doc360AccountDialog)
        assert dialog.password.text() == ""  # a kept password isn't shown
        assert dialog.save_button.isEnabled()
        dialog.user.setText("EXAMPLE\\other")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", keep)
    page.doc360_button.click()
    assert refresh.doc360_account() == replace(ACCOUNT, user="EXAMPLE\\other")

    def empty(dialog: QDialog) -> QDialog.DialogCode:
        assert isinstance(dialog, settings_module.Doc360AccountDialog)
        dialog.user.clear()
        assert dialog.problem.text() == "Save forgets the saved account."
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(settings_module, "run_modal", empty)
    page.doc360_button.click()
    assert refresh.doc360_account() is None
    assert page.doc360_row.description.text().startswith("Not set.")
