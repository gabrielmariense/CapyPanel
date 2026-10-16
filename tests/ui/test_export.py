from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from capypanel.core import settings
from capypanel.core.hosts import listfile
from capypanel.core.hosts.bulk import parse
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.ui import export_hosts
from capypanel.ui.export_hosts import FULL_BACKUP, ExportDialog
from capypanel.ui.import_hosts import read_text
from capypanel.ui.main_window.window import MainWindow


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> Iterator[MainWindow]:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    hl, hq = HostList().add_group("Headquarters")
    hl, _ = hl.add_group("Front desk", parent=hq.id)
    hl, _ = hl.add_host("HQ-01", hq.id, address="10.0.0.1", tags=["kiosk", "2nd floor"])
    hl, _ = hl.add_host("LOOSE-1", NO_GROUP, notes="spare")
    office = tmp_path / "office.json"
    listfile.save(office, hl, expected=None)
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1})
    win.open_list(office)
    yield win
    win.close()


def _run(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, use: Callable[[ExportDialog], None]
) -> None:
    """Opens Inventory > Export hosts… and does `use` with the window instead of a person."""

    def run(dialog: ExportDialog) -> int:
        use(dialog)
        return 0

    monkeypatch.setattr(ExportDialog, "exec", run)
    window.commands.export_hosts.trigger()


def test_it_opens_on_what_is_shown_with_every_row_in_the_preview(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window.nav.select_group(NO_GROUP)
    seen: list[object] = []

    def look(d: ExportDialog) -> None:
        sources = [d.source.itemText(i).strip() for i in range(d.source.count())]
        assert sources == [
            "All hosts (2 hosts)", "No group (1 host)", "Headquarters (1 host)",
            "Front desk (0 hosts)", "Tag: 2nd floor (1 host)", "Tag: kiosk (1 host)",
        ]  # fmt: skip
        seen.append(d.source.currentText())
        assert d.columns() == list(FULL_BACKUP) and d.preset.currentText() == "Full backup"
        d.source.setCurrentIndex(0)
        assert d.preview.topLevelItemCount() == 2  # every row, not a sample
        assert d.rows()[0] == ["HQ-01", "10.0.0.1", "Headquarters", "kiosk;2nd floor", ""]

    _run(window, monkeypatch, look)
    assert seen == ["No group (1 host)"]


def test_columns_come_in_groups_and_a_custom_pick_can_be_a_preset(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        export_hosts.QInputDialog, "getText", lambda *_a, **_k: ("Walk-round", True)
    )

    def pick(d: ExportDialog) -> None:
        titles = [g.title() for g in d.findChildren(export_hosts.QGroupBox)]
        assert titles == ["Host", "Tags and notes", "Last check"]
        for key, box in d.boxes.items():
            box.setChecked(key in ("name", "users"))
        assert d.preset.currentIndex() == -1 and d.preset.placeholderText() == "Custom"
        assert d.header() == ["Name", "Logged-on users"]
        assert d.unchecked.text() == "2 of these hosts weren't checked yet."
        assert d.refresh_button.isEnabled()  # users ticked: they can be checked from here
        d.save_preset.click()
        assert d.preset.currentText() == "Walk-round" and d.delete_preset.isEnabled()

    _run(window, monkeypatch, pick)
    assert window._prefs["export_presets"] == {"Walk-round": ["name", "users"]}

    def again(d: ExportDialog) -> None:
        assert d.columns() == ["name", "users"]  # the last choice
        assert d.preset.currentText() == "Walk-round"
        d.boxes["users"].setChecked(False)
        d.boxes["status"].setChecked(False)
        assert not d.refresh_button.isEnabled()  # nothing from the last check is ticked
        assert d.refresh_button.toolTip() == "Tick Status or Logged-on users to check them"

    _run(window, monkeypatch, again)


def test_refresh_runs_on_the_hosts_being_exported_and_holds_export(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[list[str], bool, bool]] = []
    monkeypatch.setattr(
        MainWindow,
        "check_hosts",
        lambda _self, hosts, *, status, users: asked.append(
            ([h.name for h in hosts], status, users)
        ),
    )
    window.nav.select_group(NO_GROUP)

    def refresh(d: ExportDialog) -> None:
        d.boxes["status"].setChecked(True)
        d.refresh_button.click()
        assert asked == [(["LOOSE-1"], True, False)]  # only the ticked check, only these hosts
        d._progress = lambda: (0, 1)  # as while the main window's Refresh runs
        d.checks_changed()
        assert not d.export_button.isEnabled() and not d.copy_button.isEnabled()
        assert d.stop_button.isVisibleTo(d) and d.checking.text() == "Checking 0 of 1…"

    _run(window, monkeypatch, refresh)


def test_export_saves_csv_that_imports_back_and_says_where(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "out" / "office.csv"
    target.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_a, **_k: (str(target), ""))
    told: list[str] = []
    monkeypatch.setattr(export_hosts, "exported_message", lambda _p, text, _path: told.append(text))
    _run(window, monkeypatch, lambda d: d.export_button.click())
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")  # a BOM, for Excel's accents
    rows = parse(read_text(target)).rows
    assert {r.name for r in rows} == {"HQ-01", "LOOSE-1"}
    hq = next(r for r in rows if r.name == "HQ-01")
    assert hq.group == "Headquarters" and hq.tags == ("kiosk", "2nd floor")
    assert told == ["2 hosts exported from All hosts."]
    assert window.statusBar().currentMessage() == "2 hosts exported from All hosts."


def test_copy_puts_every_row_on_the_clipboard_for_excel(
    window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(window, monkeypatch, lambda d: d.copy_button.click())
    lines = QApplication.clipboard().text().splitlines()
    assert lines[0] == "Name\tAddress\tGroup\tTags\tNotes"  # tabs: Excel splits them
    assert len(lines) == 3
    assert window.statusBar().currentMessage() == "Copied 2 hosts from All hosts."
