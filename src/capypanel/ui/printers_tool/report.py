"""The Printers tool's Report: the same window as Hosts', with the printers' columns. Its Last
check box (status and toner) stays greyed out until printers can be checked."""

from PySide6.QtWidgets import QWidget

from capypanel.core.hosts.bulk import host_fields
from capypanel.core.hosts.model import Host
from capypanel.core.i18n import N_, _, ngettext
from capypanel.core.printers.printer import info_of
from capypanel.ui.export_hosts import ExportDialog
from capypanel.ui.printers_tool.details import source_text


class PrintersReport(ExportDialog):
    TITLES = {
        "name": N_("Name"),
        "address": N_("Address"),
        "group": N_("Group"),
        "brand": N_("Brand"),
        "model": N_("Model"),
        "serial": N_("Serial number"),
        "asset_tag": N_("Asset tag"),
        "counter_source": N_("Page counters"),
        "tags": N_("Tags"),
        "notes": N_("Notes"),
        "status": N_("Status"),
        "toner": N_("Toner"),
    }
    SECTIONS = (
        (N_("Printer"), ("name", "address", "group", "brand", "model")),
        (N_("Details"), ("serial", "asset_tag", "counter_source", "tags", "notes")),
        (N_("Last check"), ("status", "toner")),
    )
    CHECKED = ("status", "toner")
    FOR_IMPORT = ("name", "address", "group", "brand", "model", "serial", "asset_tag",
                  "counter_source", "tags", "notes")  # fmt: skip
    PRESET_NAME = N_("All details")
    PRESETS_KEY = "printer_report_presets"
    LAST_KEY = "printer_report_columns"
    FOLDER_KEY = "printer_report_folder"
    ITEMS_LABEL = N_("Pr&inters:")  # &Preset is P

    def __init__(self, parent: QWidget | None, *args: object, **kwargs: object) -> None:
        super().__init__(parent, *args, **kwargs)  # type: ignore[arg-type]
        for key in self.CHECKED:  # nothing to check on printers yet
            self.boxes[key].setEnabled(False)
            self.boxes[key].setChecked(False)
        self.refresh_button.setEnabled(False)

    def fields(self, host: Host, between_tags: str) -> dict[str, str]:
        info = info_of(host)
        return {
            **host_fields(self._hosts, host, between_tags),
            "brand": info.brand,
            "model": info.model,
            "serial": info.serial,
            "asset_tag": info.asset_tag,
            "counter_source": source_text(info.counter_source),
        }

    def checks_note(self) -> str:
        return ""

    def for_import_tip(self) -> str:
        return _("Every column the printers have")

    def unchecked_text(self, n: int) -> str:
        return ""  # nothing can be ticked to check

    def refresh_tip(self, wanted: bool) -> str:
        return _("Nothing to check on printers yet")

    def copied_text(self, n: int, source: str) -> str:
        return ngettext(
            "Copied {n} printer from {source}.", "Copied {n} printers from {source}.", n
        ).format(n=n, source=source)

    def saved_text(self, n: int, source: str) -> str:
        return ngettext(
            "Report saved: {n} printer from {source}.",
            "Report saved: {n} printers from {source}.",
            n,
        ).format(n=n, source=source)
