"""Inventory > Export hosts…: pick the hosts and the columns, see every row, then save a CSV
file or copy the rows for Excel. Status and logged-on users come from the last Refresh, which
can be run again from here."""

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QModelIndex, QStandardPaths, Qt, QUrl
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
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.bulk import host_fields, list_separator, write_csv
from capypanel.core.hosts.model import Host, HostList
from capypanel.core.i18n import N_, _, ngettext
from capypanel.ui.groups import TREE_INDENT
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
FULL_BACKUP = ("name", "address", "group", "tags", "notes")  # what Import hosts reads back
PRESETS_KEY, LAST_KEY, FOLDER_KEY = "export_presets", "export_columns", "export_folder"
DEPTH = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class Source:
    """Hosts that can be exported: "Front desk (2 hosts)" in the dropdown, "Front desk" in the
    message once exported."""

    label: str
    name: str
    hosts: tuple[Host, ...]
    depth: int = 0  # a group's level: indented under its parent in the open list only


class ExportDialog(QDialog):
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
        results: Callable[[str], tuple[str, str]],
        refresh: Callable[[Sequence[Host], bool, bool], None],
        stop: Callable[[], None],
        progress: Callable[[], tuple[int, int] | None],
    ) -> None:
        """results: a host's status and users texts ("" when not checked). refresh and stop
        run the main window's Refresh; progress is (done, total) while one runs."""
        super().__init__(parent)
        self.setWindowTitle(_("Export hosts"))
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
        for source in self._sources:
            self.source.addItem(source.label)
            self.source.setItemData(self.source.count() - 1, source.depth, DEPTH)
        self.source.setCurrentIndex(current)
        self.preset = QComboBox()
        self.preset.setPlaceholderText(_("Custom"))  # ticks that match no preset
        self.save_preset = QPushButton(_("&Save as preset…"))
        self.delete_preset = QPushButton(_("&Delete"))
        presets = QHBoxLayout()
        presets.addWidget(self.preset, 1)
        presets.addWidget(self.save_preset)
        presets.addWidget(self.delete_preset)
        top = QFormLayout()
        top.addRow(_("&Hosts:"), self.source)
        preset_label = QLabel(_("&Preset:"))
        preset_label.setBuddy(self.preset)
        top.addRow(preset_label, presets)

        self.boxes: dict[str, QCheckBox] = {}
        sections: list[QGroupBox] = []
        for title, keys in SECTIONS:
            group = QGroupBox(_(title))
            inside = QVBoxLayout(group)
            for key in keys:
                box = QCheckBox(_(TITLES[key]))
                self.boxes[key] = box
                inside.addWidget(box)
            sections.append(group)
        host_box, notes_box, check_box = sections
        notes_box.layout().addStretch(1)  # type: ignore[union-attr]
        host_box.layout().addStretch(1)  # type: ignore[union-attr]
        privacy = hint(_("Includes who was logged on to each PC. Keep the file private."))
        self.unchecked = hint()
        self.refresh_button = QPushButton(_("&Refresh"))
        self.stop_button = QPushButton(_("S&top"))
        self.checking = QLabel()
        run_row = QHBoxLayout()
        run_row.addWidget(self.refresh_button)
        run_row.addWidget(self.stop_button)
        run_row.addWidget(self.checking, 1)
        check_layout = check_box.layout()
        assert isinstance(check_layout, QVBoxLayout)
        check_layout.insertWidget(check_layout.indexOf(self.boxes["users"]) + 1, privacy)
        check_layout.addWidget(self.unchecked)
        check_layout.addLayout(run_row)
        columns = QHBoxLayout()
        columns.addWidget(host_box)
        columns.addWidget(notes_box)
        columns.addWidget(check_box, 2)

        self.preview = QTreeWidget()
        self.preview.setObjectName("grid")
        self.preview.setRootIsDecorated(False)
        self.preview.setUniformRowHeights(True)
        preview_title = QLabel(_("Preview"))
        preview_title.setObjectName("detailsSection")

        # No default button, as in Settings: Enter never saves by surprise.
        self.buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.export_button = self.buttons.addButton(_("&Export…"), role.ActionRole)
        self.copy_button = self.buttons.addButton(_("&Copy"), role.ActionRole)
        self.copy_button.setToolTip(_("Copies every row, to paste into Excel"))
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self.reject)
        self._no_default_buttons()

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(columns)
        layout.addWidget(preview_title)
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.buttons)

        self._fill_presets()
        last = prefs.get(LAST_KEY)
        self._tick(_known(last) if isinstance(last, list) else FULL_BACKUP)
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

    # ---- what's picked ----

    def columns(self) -> list[str]:
        return [key for key, box in self.boxes.items() if box.isChecked()]

    def hosts(self) -> tuple[Host, ...]:
        return self._sources[self.source.currentIndex()].hosts

    def rows(self, between_tags: str = ";") -> list[list[str]]:
        columns = self.columns()
        rows = []
        for host in self.hosts():
            values = host_fields(self._hosts, host, between_tags)
            values["status"], values["users"] = self._results(host.id)
            rows.append([values[key] for key in columns])
        return rows

    def header(self) -> list[str]:
        return [_(TITLES[key]) for key in self.columns()]

    def _tick(self, columns: Sequence[str]) -> None:
        for key, box in self.boxes.items():
            box.blockSignals(True)
            box.setChecked(key in columns)
            box.blockSignals(False)

    # ---- presets: "Full backup", then the user's own ----

    def _presets(self) -> dict[str, list[str]]:
        saved = self._prefs.get(PRESETS_KEY)
        if not isinstance(saved, dict):
            return {}
        return {str(k): _known(v) for k, v in saved.items() if isinstance(v, list)}

    def _fill_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem(_("Full backup"), list(FULL_BACKUP))
        self.preset.setItemData(
            0,
            _("Every host field, in the format Import hosts can read back."),
            Qt.ItemDataRole.ToolTipRole,
        )
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
        if name.casefold() == _("Full backup").casefold():
            QMessageBox.warning(self, _("Save as preset"), _("That name is taken."))
            return
        presets = self._presets()
        presets[name] = self.columns()
        self._prefs[PRESETS_KEY] = presets
        self._save_prefs()
        self._fill_presets()
        self._match_preset()

    def _delete_preset(self) -> None:
        index = self.preset.currentIndex()
        if index <= 0:
            return
        presets = self._presets()
        presets.pop(self.preset.itemText(index), None)
        self._prefs[PRESETS_KEY] = presets
        self._save_prefs()
        self._fill_presets()
        self._match_preset()

    # ---- showing it ----

    def _ticks_changed(self) -> None:
        self._match_preset()
        self._update()

    def _update(self) -> None:
        """The preview, the "not checked" count and which buttons work."""
        self._fill_preview()
        hosts = self.hosts()
        wanted = [key for key in CHECKED if self.boxes[key].isChecked()]
        index = {"status": 0, "users": 1}
        missing = sum(
            1 for h in hosts if any(not self._results(h.id)[index[key]] for key in wanted)
        )
        self.unchecked.setText(
            ngettext(
                "{n} of these hosts wasn't checked yet.",
                "{n} of these hosts weren't checked yet.",
                missing,
            ).format(n=missing)
            if missing
            else ""
        )
        self.unchecked.setVisible(bool(missing))
        running = self._progress()
        if running is not None:
            done, total = running
            self.checking.setText(_("Checking {done} of {total}…").format(done=done, total=total))
        self.checking.setVisible(running is not None)
        self.stop_button.setVisible(running is not None)
        self.refresh_button.setEnabled(running is None and bool(wanted) and bool(hosts))
        self.refresh_button.setToolTip(
            _("Checks these hosts again now")
            if wanted
            else _("Tick Status or Logged-on users to check them")
        )
        can_export = running is None and bool(self.columns()) and bool(hosts)
        self.export_button.setEnabled(can_export)
        self.copy_button.setEnabled(can_export)

    def _fill_preview(self) -> None:
        self.preview.clear()
        self.preview.setColumnCount(max(len(self.columns()), 1))
        self.preview.setHeaderLabels(self.header() or [""])
        for row in self.rows():
            item = QTreeWidgetItem([" ".join(cell.split()) for cell in row])  # one line each
            self.preview.addTopLevelItem(item)
        for column in range(self.preview.columnCount()):
            self.preview.resizeColumnToContents(column)

    def checks_changed(self) -> None:
        """The main window's Refresh moved on: new results, or it started or ended."""
        self._update()

    # ---- Refresh, from here ----

    def _run_refresh(self) -> None:
        status, users = self.boxes["status"].isChecked(), self.boxes["users"].isChecked()
        self._refresh(self.hosts(), status, users)
        self._update()

    # ---- saving or copying ----

    def _remember(self) -> None:
        self._prefs[LAST_KEY] = self.columns()
        self._save_prefs()

    def _copy(self) -> None:
        text = write_csv(self.header(), self.rows(), "\t")  # tabs: Excel pastes them as columns
        QGuiApplication.clipboard().setText(text)
        self._remember()
        source = self._sources[self.source.currentIndex()]
        n = len(source.hosts)
        self.outcome = ngettext(
            "Copied {n} host from {source}.", "Copied {n} hosts from {source}.", n
        ).format(n=n, source=source.name)
        self.accept()

    def _export(self) -> None:
        source = self._sources[self.source.currentIndex()]
        folder = self._prefs.get(FOLDER_KEY)
        if not isinstance(folder, str) or not Path(folder).is_dir():
            documents = QStandardPaths.StandardLocation.DocumentsLocation
            folder = QStandardPaths.writableLocation(documents)
        whole = len(source.hosts) == len(self._hosts.hosts)
        name = self._list_name if whole else f"{self._list_name} - {source.name}"
        name, _filter = QFileDialog.getSaveFileName(
            self,
            _("Export hosts"),
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
                _("Export hosts"),
                _("Couldn't save “{path}”: {error}").format(path=path, error=e),
            )
            return
        self._prefs[FOLDER_KEY] = str(path.parent)
        self._remember()
        n = len(source.hosts)
        self.outcome = ngettext(
            "{n} host exported from {source}.", "{n} hosts exported from {source}.", n
        ).format(n=n, source=source.name)
        self.accept()
        exported_message(self.parentWidget(), self.outcome, path)


def exported_message(parent: QWidget | None, text: str, path: Path) -> None:
    """ "2 hosts exported from Front desk.", with the file, and buttons to open it or its
    folder."""
    box = QMessageBox(QMessageBox.Icon.Information, _("Export hosts"), text, parent=parent)
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


def _known(columns: object) -> list[str]:
    """Saved columns, in the window's order, without ones this version doesn't have."""
    wanted = columns if isinstance(columns, list) else []
    return [key for key in TITLES if key in wanted]


def _file_safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip(" .") or "hosts"
