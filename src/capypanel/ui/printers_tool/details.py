"""The printer Details panel: Connection, Printer, Page counters, Tags and Notes."""

from dataclasses import dataclass

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout

from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.printers.printer import DOC360, SNMP, info_of
from capypanel.ui.list_workspace.details import DetailsPanel


@dataclass(frozen=True)
class PrinterDetails:
    printer: Host
    group: str  # its full path


def source_text(source: str) -> str:
    """Where a printer's page counters come from, in words."""
    if source == SNMP:
        return "SNMP"
    if source == DOC360:
        return "Doc360 MPS"
    return _("Unknown ({source})").format(source=source)  # kept as the file has it


class PrinterDetailsPanel(DetailsPanel):
    def show_printer(
        self, details: PrinterDetails | None, selected: int, summary: str = "", needle: str = ""
    ) -> None:
        self.show_item(details, selected, summary, needle)

    def selected_text(self, selected: int) -> str:
        return ngettext("{n} printer selected", "{n} printers selected", selected).format(
            n=selected
        )

    def pick_hint(self) -> str:
        return _("Select a printer to see its details.")

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, PrinterDetails)
        printer, info = shown.printer, info_of(shown.printer)
        name = self.value("name", printer.name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        layout.addWidget(name)
        about = " ".join(p for p in (info.brand, info.model) if p)
        if about:
            layout.addWidget(self.muted(about))

        self.section(layout, _("Connection"))
        self._fields(layout, (("address", _("Address"), printer.address),
                              ("group", _("Group"), shown.group)))  # fmt: skip

        self.section(layout, _("Printer"))
        self._fields(
            layout,
            (
                ("brand", _("Brand"), info.brand),
                ("model", _("Model"), info.model),
                ("serial", _("Serial number"), info.serial),
                ("asset_tag", _("Asset tag"), info.asset_tag),
            ),
        )

        self.section(layout, _("Page counters"))
        self._fields(layout, (("counter_source", _("Source"), source_text(info.counter_source)),))

        self.section(layout, _("Tags"))
        layout.addWidget(self.chips(printer.tags) if printer.tags else self.muted("—"))

        self.section(layout, _("Notes"))
        layout.addWidget(self.notes(printer.notes, needle) if printer.notes else self.muted("—"))

    def _fields(self, layout: QVBoxLayout, fields: tuple[tuple[str, str, str], ...]) -> None:
        for key, label, value in fields:
            layout.addWidget(self.muted(label))
            layout.addWidget(self.value(key, value) if value else self.muted("—"))
