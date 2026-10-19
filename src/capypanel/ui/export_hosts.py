"""The toolbar's Report: pick the items and the columns, see every row, then save a CSV
file or copy the rows for Excel. The checks' columns (for hosts: status and logged-on users) come
from the last Refresh, which can be run again from here.

ExportDialog is the Hosts tool's Report. Another tool's Report subclasses it and overrides its
columns (TITLES, SECTIONS, CHECKED, FOR_IMPORT), where its choices are kept, and its texts."""

import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.bulk import host_fields, list_separator, write_csv
from capypanel.core.hosts.model import Host, HostList
from capypanel.core.i18n import N_, _, ngettext
from capypanel.ui.groups import TREE_INDENT
from capypanel.ui.hosts import confirm
from capypanel.ui.notes import hint

# Each column, the group its checkbox is in, and its title (also the file's header row, which
# Import hosts reads back in English or Portuguese).
TITLES = {
    "name": N_("Name"),
    "address": N_("Address"),
    "group": N_("Group"),
    "tags": N_("Tags"),
    "notes": N_("Notes"),
    "status": N_("Status"),
    "users": N_("Logged-on users"),
}
SECTIONS = (
    (N_("Host"), ("name", "address", "group")),
    (N_("Tags and notes"), ("tags", "notes")),
    (N_("Last check"), ("status", "users")),
)
CHECKED = ("status", "users")  # from the last Refresh, kept in memory only
FOR_IMPORT = ("name", "address", "group", "tags", "notes")  # what Import hosts reads back
PRESETS_KEY, LAST_KEY, FOLDER_KEY = "export_presets", "export_columns", "export_folder"
DEPTH = Qt.ItemDataRole.UserRole + 1
WIDEST = 240  # px: the preview's widest column


@dataclass(frozen=True)
class Source:
    """Hosts that can be exported: "Front desk (2 hosts)" in the dropdown, "Front desk" in the
    message once exported."""

    label: str
    name: str
    hosts: tuple[Host, ...]
    depth: int = 0  # a group's level: indented under its parent in the open list only


class ExportDialog(QDialog):
    # What this Report lists. SECTIONS are boxes of ticks, one row each; with CHECKED, the last
    # box holds the checks from Refresh, stacked, with the run buttons under them.
    TITLES: Mapping[str, str] = TITLES
    SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = SECTIONS
    CHECKED: tuple[str, ...] = CHECKED
    FOR_IMPORT: tuple[str, ...] = FOR_IMPORT
    PRESETS_KEY, LAST_KEY, FOLDER_KEY = PRESETS_KEY, LAST_KEY, FOLDER_KEY  # its own choices
    ITEMS_LABEL = N_("&Hosts:")

    def __init__(
        self,
        parent: QWidget | None,
        host_list: HostList,
        sources: Sequence[Source],
        current: int,
        *,
        list_name: str,
        prefs: dict[str, object],
        save_prefs: Callable[[], None],
        results: Callable[[str], tuple[str, ...]],
        refresh: Callable[..., None],
        stop: Callable[[], None],
        progress: Callable[[], tuple[int, int] | None],
    ) -> None:
        """results: an item's texts for the CHECKED columns, in order ("" when not checked).
        refresh(items, *wanted) and stop run the tool's Refresh, one flag per CHECKED column;
        progress is (done, total) while one runs."""
        super().__init__(parent)
        self.setWindowTitle(_("Report"))
        self._hosts = host_list
        self._sources = list(sources)
        self._list_name = list_name
        self._prefs, self._save_prefs = prefs, save_prefs
        self._results, self._refresh, self._stop, self._progress = (
            results, refresh, stop, progress
        )  # fmt: skip
        self.outcome = ""  # for the status bar: what was exported or copied

        self.source = QComboBox()
        self.source.setItemDelegate(_Indented(self.source))
        self.source.setMaxVisibleItems(15)  # a long list of groups scrolls
        for source in self._sources:
            self.source.addItem(source.label)
            self.source.setItemData(self.source.count() - 1, source.depth, DEPTH)
        self.source.setCurrentIndex(current)  # what the window shows now
        self.preset = QComboBox()
        self.preset.setPlaceholderText(_("Custom"))  # ticks that match no preset
        self.save_preset = QPushButton(_("&Save as preset…"))
        self.delete_preset = QPushButton(_("&Delete"))
        presets = QHBoxLayout()
        presets.addWidget(self.preset, 1)
        presets.addWidget(self.save_preset)
        presets.addWidget(self.delete_preset)
        top = QFormLayout()
        top.addRow(_(self.ITEMS_LABEL), self.source)
        preset_label = QLabel(_("&Preset:"))
        preset_label.setBuddy(self.preset)
        top.addRow(preset_label, presets)

        self.boxes: dict[str, QCheckBox] = {}
        rows: list[QGroupBox] = []
        checks: QGroupBox | None = None
        for index, (title, keys) in enumerate(self.SECTIONS):
            group = QGroupBox(_(title))
            stacked = bool(self.CHECKED) and index == len(self.SECTIONS) - 1
            inside = QVBoxLayout(group) if stacked else QHBoxLayout(group)
            for key in keys:
                box = QCheckBox(_(self.TITLES[key]))
                self.boxes[key] = box
                inside.addWidget(box)
            if stacked:
                checks = group
            else:
                inside.addStretch(1)
                rows.append(group)
        self.unchecked = hint()
        self.refresh_button = QPushButton(_("&Refresh"))
        self.stop_button = QPushButton(_("S&top"))
        self.checking = QLabel()
        left = QVBoxLayout()
        for group in rows:
            left.addWidget(group)
        columns = QHBoxLayout()
        columns.addLayout(left, 1)
        if checks is not None:
            run_row = QHBoxLayout()
            run_row.addWidget(self.refresh_button)
            run_row.addWidget(self.stop_button)
            run_row.addWidget(self.checking, 1)
            check_layout = checks.layout()
            assert isinstance(check_layout, QVBoxLayout)
            note = self.checks_note()
            if note:  # under the ticks it's about
                check_layout.addWidget(hint(note))
            check_layout.addWidget(self.unchecked)
            check_layout.addLayout(run_row)
            columns.addWidget(checks, 1)
        else:  # nothing to check: no Refresh here
            for widget in (self.unchecked, self.refresh_button, self.stop_button, self.checking):
                widget.setParent(self)
                widget.hide()

        self.preview = QTreeWidget()
        self.preview.setObjectName("grid")
        self.preview.setRootIsDecorated(False)
        self.preview.setUniformRowHeights(True)
        self.preview.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keeps a path's both ends
        preview_title = QLabel(_("Preview"))
        preview_title.setObjectName("detailsSection")

        # No default button, as in Settings: Enter never saves by surprise.
        self.buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.export_button = self.buttons.addButton(_("&Export…"), role.ActionRole)
        self.copy_button = self.buttons.addButton(_("&Copy"), role.ActionRole)
        self.copy_button.setToolTip(_("Copies every row, to paste into Excel"))
        # Close: nothing to cancel, every choice here is kept as soon as it's made.
        self.buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self._no_default_buttons()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(columns)
        layout.addWidget(preview_title)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.buttons)

        self._fill_presets()
        last = prefs.get(self.LAST_KEY)
        self._tick(self._known(last) if isinstance(last, list) else self.FOR_IMPORT)
        self.source.currentIndexChanged.connect(self._update)
        self.preset.activated.connect(self._preset_picked)
        self.save_preset.clicked.connect(self._save_as_preset)
        self.delete_preset.clicked.connect(self._delete_preset)
        for box in self.boxes.values():
            box.toggled.connect(self._ticks_changed)
        self.refresh_button.clicked.connect(self._run_refresh)
        self.stop_button.clicked.connect(self._stop)
        self.export_button.clicked.connect(self._export)
        self.copy_button.clicked.connect(self._copy)
        self._ticks_changed()
        self.resize(720, 600)

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._no_default_buttons()  # a dialog makes one default as it shows

    # ---- what a tool's Report changes ----

    def fields(self, host: Host, between_tags: str) -> dict[str, str]:
        """An item's own values, by column key (the checks' come from `results`)."""
        return host_fields(self._hosts, host, between_tags)

    def checks_note(self) -> str:
        return _("Includes who was logged on to each PC. Keep the file private.")

    def for_import_tip(self) -> str:
        return _("The hosts' own fields, which Import hosts reads back: to move hosts to a list.")

    def unchecked_text(self, n: int) -> str:
        return ngettext(
            "{n} of these hosts wasn't checked yet.", "{n} of these hosts weren't checked yet.", n
        ).format(n=n)

    def refresh_tip(self, wanted: bool) -> str:
        return (
            _("Checks these hosts again now")
            if wanted
            else _("Tick Status or Logged-on users to check them")
        )

    def copied_text(self, n: int, source: str) -> str:
        return ngettext(
            "Copied {n} host from {source}.", "Copied {n} hosts from {source}.", n
        ).format(n=n, source=source)

    def saved_text(self, n: int, source: str) -> str:
        return ngettext(
            "Report saved: {n} host from {source}.", "Report saved: {n} hosts from {source}.", n
        ).format(n=n, source=source)

    # ---- what's picked ----

    def columns(self) -> list[str]:
        return [key for key, box in self.boxes.items() if box.isChecked()]

    def hosts(self) -> tuple[Host, ...]:
        return self._sources[self.source.currentIndex()].hosts

    def rows(self, between_tags: str = ";") -> list[list[str]]:
        columns = self.columns()
        rows = []
        for host in self.hosts():
            values = self.fields(host, between_tags)
            values.update(zip(self.CHECKED, self._results(host.id), strict=True))
            rows.append([values[key] for key in columns])
        return rows

    def header(self) -> list[str]:
        return [_(self.TITLES[key]) for key in self.columns()]

    def _tick(self, columns: Sequence[str]) -> None:
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(key in columns)
            box.blockSignals(False)

    def _known(self, columns: object) -> list[str]:
        """Saved columns, in the window's order, without ones this version doesn't have."""
        wanted = columns if isinstance(columns, list) else []
        return [key for key in self.TITLES if key in wanted]

    # ---- presets: "For Import", then the user's own ----

    def _presets(self) -> dict[str, list[str]]:
        saved = self._prefs.get(self.PRESETS_KEY)
        if not isinstance(saved, dict):
            return {}
        return {str(k): self._known(v) for k, v in saved.items() if isinstance(v, list)}

    def _fill_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem(_("For Import"), list(self.FOR_IMPORT))
        self.preset.setItemData(0, self.for_import_tip(), Qt.ItemDataRole.ToolTipRole)
        for name, columns in sorted(self._presets().items(), key=lambda p: p[0].casefold()):
            self.preset.addItem(name, columns)
        self.preset.blockSignals(False)

    def _preset_picked(self, index: int) -> None:
        self._tick(self.preset.itemData(index))
        self._ticks_changed()

    def _match_preset(self) -> None:
        """Shows the preset the ticks match, or "Custom"."""
        columns = self.columns()
        found = next(
            (i for i in range(self.preset.count()) if self.preset.itemData(i) == columns), -1
        )
        self.preset.setCurrentIndex(found)
        self.delete_preset.setEnabled(found > 0)  # the built-in one stays

    def _save_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, _("Save as preset"), _("Preset name:"))
        name = name.strip()
        if not ok or not name:
            return
        if name.casefold() == _("For Import").casefold():
            QMessageBox.warning(self, _("Save as preset"), _("That name is taken."))
            return
        presets = self._presets()
        # The same name, whatever its case: replacing it is asked first, Cancel the default.
        same = next((p for p in presets if p.casefold() == name.casefold()), None)
        if same is not None:
            question = _("A preset named “{name}” already exists. Replace it?").format(name=same)
            if not confirm(self, _("Save as preset"), question, _("Replace")):
                return
            presets.pop(same)
        presets[name] = self.columns()
        self._prefs[self.PRESETS_KEY] = presets
        self._save_prefs()
        self._fill_presets()
        self._match_preset()

    def _delete_preset(self) -> None:
        index = self.preset.currentIndex()
        if index <= 0:
            return
        presets = self._presets()
        presets.pop(self.preset.itemText(index), None)
        self._prefs[self.PRESETS_KEY] = presets
        self._save_prefs()
        self._fill_presets()
        self._match_preset()

    # ---- showing it ----

    def _ticks_changed(self) -> None:
        self._match_preset()
        self._update()
        self._remember()

    def _update(self) -> None:
        """The preview, the "not checked" count and which buttons work."""
        self._fill_preview()
        hosts = self.hosts()
        running = self._progress()
        if self.CHECKED:
            wanted = [key for key in self.CHECKED if self.boxes[key].isChecked()]
            place = {key: i for i, key in enumerate(self.CHECKED)}
            missing = sum(
                1 for h in hosts if any(not self._results(h.id)[place[key]] for key in wanted)
            )
            self.unchecked.setText(self.unchecked_text(missing) if missing else "")
            self.unchecked.setVisible(bool(missing))
            if running is not None:
                done, total = running
                text = _("Checking {done} of {total}…").format(done=done, total=total)
                self.checking.setText(text)
            self.checking.setVisible(running is not None)
            self.stop_button.setVisible(running is not None)
            self.refresh_button.setEnabled(running is None and bool(wanted) and bool(hosts))
            self.refresh_button.setToolTip(self.refresh_tip(bool(wanted)))
        can_export = running is None and bool(self.columns()) and bool(hosts)
        self.export_button.setEnabled(can_export)
        self.copy_button.setEnabled(can_export)

    def _fill_preview(self) -> None:
        self.preview.clear()
        self.preview.setColumnCount(max(len(self.columns()), 1))
        self.preview.setHeaderLabels(self.header() or [""])
        for row in self.rows():
            item = QTreeWidgetItem([" ".join(cell.split()) for cell in row])  # one line each
            for column, cell in enumerate(row):
                item.setToolTip(column, cell)  # in full, when the column cuts it
            self.preview.addTopLevelItem(item)
        for column in range(self.preview.columnCount()):
            self.preview.resizeColumnToContents(column)
            # A long group path or note is cut in the middle, so the other columns stay in view.
            self.preview.setColumnWidth(column, min(self.preview.columnWidth(column), WIDEST))

    def checks_changed(self) -> None:
        """The main window's Refresh moved on: new results, or it started or ended."""
        self._update()

    # ---- Refresh, from here ----

    def _run_refresh(self) -> None:
        self._refresh(self.hosts(), *(self.boxes[key].isChecked() for key in self.CHECKED))
        self._update()

    # ---- saving or copying ----

    def _remember(self) -> None:
        """The columns, kept at once: closing never loses them. The hosts follow what the main
        window shows each time."""
        self._prefs[self.LAST_KEY] = self.columns()
        self._save_prefs()

    def _copy(self) -> None:
        text = write_csv(self.header(), self.rows(), "\t")  # tabs: Excel pastes them as columns
        QGuiApplication.clipboard().setText(text)
        source = self._sources[self.source.currentIndex()]
        self.outcome = self.copied_text(len(source.hosts), source.name)
        # The window stays open, to copy other hosts or save a file next.
        button = self.copy_button
        QToolTip.showText(button.mapToGlobal(QPoint(0, button.height())), self.outcome, button)

    def _export(self) -> None:
        source = self._sources[self.source.currentIndex()]
        folder = self._prefs.get(self.FOLDER_KEY)
        if not isinstance(folder, str) or not Path(folder).is_dir():
            documents = QStandardPaths.StandardLocation.DocumentsLocation
            folder = QStandardPaths.writableLocation(documents)
        whole = len(source.hosts) == len(self._hosts.hosts)
        name = self._list_name if whole else f"{self._list_name} - {source.name}"
        name, _filter = QFileDialog.getSaveFileName(
            self,
            _("Report"),
            str(Path(folder) / f"{_file_safe(name)}.csv"),
            _("CSV files (*.csv)"),
        )
        if not name:
            return
        path = Path(name)
        delimiter = list_separator()  # what this PC's Excel splits columns on
        between_tags = "," if delimiter == ";" else ";"
        text = write_csv(self.header(), self.rows(between_tags), delimiter)
        try:
            path.write_text(text, encoding="utf-8-sig")  # the BOM: Excel reads accents right
        except OSError as e:
            QMessageBox.warning(
                self,
                _("Report"),
                _("Couldn't save “{path}”: {error}").format(path=path, error=e),
            )
            return
        self._prefs[self.FOLDER_KEY] = str(path.parent)
        self._remember()
        self.outcome = self.saved_text(len(source.hosts), source.name)
        self.accept()
        exported_message(self.parentWidget(), self.outcome, path)


def exported_message(parent: QWidget | None, text: str, path: Path) -> None:
    """ "Report saved: 2 hosts from Front desk.", with the file, and buttons to open it or its
    folder."""
    box = QMessageBox(QMessageBox.Icon.Information, _("Report"), text, parent=parent)
    box.setInformativeText(str(path))
    for label in box.findChildren(QLabel, "qt_msgbox_informativelabel"):
        label.setWordWrap(False)  # a path breaks badly: the box widens instead
    open_file = box.addButton(_("Open &file"), QMessageBox.ButtonRole.ActionRole)
    open_folder = box.addButton(_("Open f&older"), QMessageBox.ButtonRole.ActionRole)
    box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Close))  # Enter just closes
    box.exec()
    if box.clickedButton() is open_file:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    elif box.clickedButton() is open_folder:
        # Explorer opens the folder with the file picked.
        subprocess.Popen(["explorer", f"/select,{path}"])  # noqa: S603, S607


class _Indented(QStyledItemDelegate):
    """The dropdown's open list: each group indented under the group it's in."""

    def initStyleOption(self, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # type: ignore[override]
        super().initStyleOption(option, index)
        option.text = TREE_INDENT * int(index.data(DEPTH) or 0) + option.text  # type: ignore[attr-defined]


def _file_safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "hosts"
