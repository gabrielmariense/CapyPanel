from PySide6.QtWidgets import QDialog, QWidget

from capypanel.core.hosts.bulk import ImportRow, Parsed, Plan
from capypanel.core.i18n import N_, _, ngettext, npgettext
from capypanel.core.printers import bulk
from capypanel.ui.import_hosts import FormatsDialog, ImportDialog, needs_header_text


class ImportPrintersDialog(ImportDialog):
    HELP_PLACE = "printers-import-many-printers-at-once"
    TITLE = N_("Import printers")
    GROUP_LABEL = N_("Printers with no group &go to:")
    PLACEHOLDER = N_("For example:\nname,address,brand\nReception,192.0.2.10,HP")
    EDIT_QUESTION = N_(
        "Editing in the table rewrites the list above as CSV with a header row (name, "
        "address, group, tags, notes and the printers' own columns), so the two always match. "
        "Continue?"
    )
    MORE = (
        ("brand", N_("Brand")),
        ("model", N_("Model")),
        ("serial", N_("Serial number")),
        ("asset_tag", N_("Asset tag")),
        ("counter_source", N_("Page counters")),
    )
    WIDTH = 1300

    def add_text(self, n: int) -> str:
        if not n:
            return _("&Add printers")
        return ngettext("&Add {n} printer", "&Add {n} printers", n).format(n=n)

    def adding_text(self, n: int) -> str:
        return ngettext("{n} printer will be added.", "{n} printers will be added.", n).format(n=n)

    # Printers' own context: pt-BR words them for "impressoras".
    def skipped_text(self, n: int) -> str:
        return npgettext("printers", "{n} skipped.", "{n} skipped.", n).format(n=n)

    def bad_text(self, n: int) -> str:
        return npgettext("printers", "{n} can't be added.", "{n} can't be added.", n).format(n=n)

    def needs_header(self) -> str:
        return needs_header_text(
            _("name, address, group, brand, model, serial number, asset tag, page counters")
        )

    def formats(self) -> QDialog:
        return PrinterFormats(self)

    def read_rows(self, text: str, *, file: bool) -> Parsed:
        return bulk.parse(text, file=file)

    def plan_rows(self, rows: list[ImportRow], group_id: str) -> Plan:
        return bulk.plan(self._hosts, rows, group_id)


class PrinterFormats(FormatsDialog):
    HELP_PLACE = "printers-import-many-printers-at-once"

    def _formats(self) -> list[tuple[str, QWidget]]:
        titles = [_("Name"), _("Address"), _("Group"), _("Brand"), _("Model"), _("Serial number")]
        report_rows = [
            ["Reception", "192.0.2.10", "Clinic A", "HP", "M404", "SAMPLE01"],
            ["Lab", "PRN-LAB", "Clinic A", "RICOH", "SP 3710", "SAMPLE02"],
        ]
        return [
            (
                _("Name and address"),
                self._page(
                    _(
                        "Any name you like, then the printer's IP address or network name. "
                        "Separate them with a comma, or copy two columns from Excel."
                    ),
                    "Reception,192.0.2.10\nLab,PRN-LAB.corp.example.net",
                    [_("Name"), _("Address")],
                    [["Reception", "192.0.2.10"], ["Lab", "PRN-LAB.corp.example.net"]],
                ),
            ),
            (
                _("A Printers Report"),
                self._page(
                    _(
                        "A Report saved with the For Import or All details columns comes back "
                        "as it was, in English or Portuguese. Columns it doesn't use are "
                        "ignored."
                    ),
                    ",".join(titles) + "".join("\n" + ",".join(row) for row in report_rows),
                    titles,
                    report_rows,
                ),
            ),
            (
                _("Windows' printer list"),
                self._page(
                    _(
                        "Windows PowerShell saves a PC's printers to a file with the command "
                        "below (UTF8 keeps accents); add -ComputerName and a print server's name "
                        "for its printers. "
                        "The name and the port come in, and the location and comment go into "
                        "the notes. A port that isn't an address (WSD, USB) comes in to be "
                        "typed here."
                    ),
                    "Get-Printer | Export-Csv printers.csv -Encoding UTF8",
                    typed_title=_("Command"),
                ),
            ),
        ]
