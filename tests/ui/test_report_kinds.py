from PySide6.QtWidgets import QApplication, QGroupBox

from capypanel.core.hosts.model import NO_GROUP, Host, HostList
from capypanel.core.i18n import N_
from capypanel.ui.export_hosts import ExportDialog, Source


class SerialReport(ExportDialog):
    """A tool's own Report: its columns, nothing to check, its choices kept apart."""

    TITLES = {"name": N_("Name"), "serial": N_("Serial number")}
    SECTIONS = ((N_("Printer"), ("name", "serial")),)
    CHECKED = ()
    FOR_IMPORT = ("name",)
    PRESETS_KEY, LAST_KEY, FOLDER_KEY = "test_presets", "test_columns", "test_folder"

    def fields(self, host: Host, between_tags: str) -> dict[str, str]:
        return {"name": host.name, "serial": "SAMPLE1"}


def test_a_tool_s_own_report_has_its_columns_and_no_refresh(qapp: QApplication) -> None:
    printers, _host = HostList().add_host("P1", NO_GROUP)
    prefs: dict[str, object] = {}
    dialog = SerialReport(
        None,
        printers,
        [Source("All (1)", "All", printers.hosts)],
        0,
        list_name="office",
        prefs=prefs,
        save_prefs=lambda: None,
        results=lambda _id: (),
        refresh=lambda *_a: None,
        stop=lambda: None,
        progress=lambda: None,
    )
    assert [g.title() for g in dialog.findChildren(QGroupBox)] == ["Printer"]  # no Last check
    assert dialog.refresh_button.isHidden()  # nothing to check: no Refresh here
    assert dialog.columns() == ["name"]  # starts on its own For Import
    dialog.boxes["serial"].setChecked(True)
    assert dialog.header() == ["Name", "Serial number"]
    assert dialog.rows() == [["P1", "SAMPLE1"]]
    assert prefs["test_columns"] == ["name", "serial"] and "export_columns" not in prefs
    dialog.deleteLater()
