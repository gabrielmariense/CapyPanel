"""The toolbar's Report: pick the items and the columns, see every row, then save a CSV
file or copy the rows for Excel. The checks' columns (for hosts: status and logged-on users) come
from the last Refresh, which can be run again from here.

ExportDialog is the Hosts tool's Report. Another tool's Report subclasses it and overrides its
columns (TITLES, SECTIONS, CHECKED, FOR_IMPORT), where its choices are kept, and its texts."""

import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QModelIndex, QPoint, QStandardPaths, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QPalette,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
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
from capypanel.ui import spacing
from capypanel.ui.checks import clock_text
from capypanel.ui.groups import TREE_INDENT
from capypanel.ui.hosts import confirm
from capypanel.ui.icons import tabler_icon
from capypanel.ui.list_workspace.panels import sorted_by
from capypanel.ui.notes import hint
from capypanel.ui.tables import fit_menu

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
SAYS_NOT_CHECKED = frozenset({"status"})  # empty in the file, "Not checked" in the preview
FOR_IMPORT = ("name", "address", "group", "tags", "notes")  # what Import hosts reads back
PRESETS_KEY, LAST_KEY, FOLDER_KEY = "export_presets", "export_columns", "export_folder"
DEPTH = Qt.ItemDataRole.UserRole + 1
WIDEST = 240  # px: the preview's widest column
TICK_HEIGHT, TICK_SPACING = 22, 2  # px: one tick per line, the same height in every box


@dataclass(frozen=True)
class Source:
    """Hosts that can be exported: "Front desk (2 hosts)" in the dropdown, "Front desk" in the
    message once exported."""

    label: str
    name: str
    hosts: tuple[Host, ...]
    depth: int = 0  # a group's level: indented under its parent in the open list only


class ExportDialog(QDialog):
    # What this Report lists. SECTIONS are boxes of ticks, one row each, one under the other;
    # with CHECKED, the last box holds the checks from Refresh, with Refresh at its row's end.
    TITLES: Mapping[str, str] = TITLES
    SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = SECTIONS
    CHECKED: tuple[str, ...] = CHECKED
    SAYS_NOT_CHECKED: frozenset[str] = SAYS_NOT_CHECKED
    FOR_IMPORT: tuple[str, ...] = FOR_IMPORT
    PRESETS_KEY, LAST_KEY, FOLDER_KEY = PRESETS_KEY, LAST_KEY, FOLDER_KEY  # its own choices
    ITEMS_LABEL = N_("&Hosts:")
    PRESET_NAME = N_("For Import")  # the built-in preset, with the FOR_IMPORT columns

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
        checked_at: Callable[[str], Sequence[datetime | None]] | None = None,
    ) -> None:
        """results: an item's texts for the CHECKED columns, in order ("" when not checked);
        checked_at: when each was read (None when not). refresh(items, *wanted) and stop run the
        tool's Refresh, one flag per CHECKED column; progress is (done, total) while one runs."""
        super().__init__(parent)
        self.setWindowTitle(_("Report"))
        self._hosts = host_list
        self._sources = list(sources)
        self._list_name = list_name
        self._prefs, self._save_prefs = prefs, save_prefs
        self._results, self._refresh, self._stop, self._progress = (
            results, refresh, stop, progress
        )  # fmt: skip
        self._checked_at = checked_at
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

        # Three boxes side by side, equal widths and heights (the tallest sets it): one tick per
        # line at a fixed height, so the ticks line up inside and across the boxes. Each title
        # has All · None. With CHECKED, the last box is the checks from Refresh: its time and
        # Refresh (Stop while one runs) on its title line, and under its ticks the names note
        # (while that tick is on), how many weren't checked yet and the progress. A window too
        # narrow for three puts that box under the other two, full width.
        self.boxes: dict[str, QCheckBox] = {}
        self._section_boxes: list[QFrame] = []
        self.checks_box: QLabel | None = None
        self.checks_time = hint()
        self.checks_title = ""
        self.note = hint(self.checks_note())
        self.unchecked = hint()
        self.checking = hint()
        color = self.palette().color(QPalette.ColorRole.Text)
        # Refresh is a plain button at the foot of Last check, saying how many it reads; Stop
        # takes its place while a check runs. Exportar stays the window's one main button.
        self.refresh_button = _plain_button("refresh", color)
        self.stop_button = _plain_button("x", color)
        self.stop_button.setText(" " + _("Stop"))
        self.stop_button.hide()  # only while a check runs
        for index, (title, keys) in enumerate(self.SECTIONS):
            frame = QFrame()
            frame.setObjectName("reportBox")
            inside = QVBoxLayout(frame)
            inside.setContentsMargins(
                spacing.PANEL, spacing.CONTROLS, spacing.PANEL, spacing.CONTROLS
            )
            inside.setSpacing(TICK_SPACING)
            name = QLabel(_(title))
            name.setObjectName("rowName")
            both = QLabel(f'<a href="all">{escape(_("All"))}</a> · '
                          f'<a href="none">{escape(_("None"))}</a>')  # fmt: skip
            both.setObjectName("hint")
            both.setTextFormat(Qt.TextFormat.RichText)
            both.linkActivated.connect(lambda href, ks=keys: self._tick_section(ks, href == "all"))
            head = QHBoxLayout()
            head.setSpacing(spacing.CONTROLS)
            head.addWidget(name)
            head.addStretch(1)
            checks = bool(self.CHECKED) and index == len(self.SECTIONS) - 1
            if checks:
                self.checks_box = name
                self.checks_title = _(title)
                head.addWidget(self.checks_time)
            inside.addLayout(head)
            inside.addWidget(both)  # under the title, small: the boxes stay narrow enough
            for key in keys:
                box = QCheckBox(_(self.TITLES[key]))
                box.setFixedHeight(TICK_HEIGHT)
                self.boxes[key] = box
                inside.addWidget(box)
            if checks:
                for widget in (self.note, self.unchecked, self.checking):
                    inside.addWidget(widget)
            inside.addStretch(1)
            if checks:  # at the box's foot, lined up with the other boxes' ends: it never jumps
                buttons = QHBoxLayout()
                buttons.setContentsMargins(0, spacing.ICON, 0, 0)
                buttons.addWidget(self.refresh_button)
                buttons.addWidget(self.stop_button)
                buttons.addStretch(1)  # its own width, as every other button
                inside.addLayout(buttons)
            self._section_boxes.append(frame)
        if self.checks_box is None:  # nothing to check: no Refresh here
            parts = (self.unchecked, self.refresh_button, self.stop_button, self.checking,
                     self.checks_time, self.note)  # fmt: skip
            for widget in parts:
                widget.setParent(self)
                widget.hide()
        if not self.note.text():
            self.note.hide()
        self._sections = QGridLayout()
        self._sections.setHorizontalSpacing(spacing.CONTROLS)
        self._sections.setVerticalSpacing(spacing.CONTROLS)
        self._side_by_side: bool | None = None
        self._place_sections(True)

        self.preview = QTreeWidget()
        self.preview.setObjectName("grid")
        self.preview.setRootIsDecorated(False)
        self.preview.setUniformRowHeights(True)
        self.preview.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keeps a path's both ends
        fit_menu(self.preview)
        # A click on a column's title sorts the rows by it, A–Z then Z–A, as in the main table;
        # until then they're in the main table's order. Copy and Export use the same order.
        self._sort: tuple[str, bool] | None = None  # (column key, Z–A)
        self.preview.header().setSectionsClickable(True)
        self.preview.header().sectionClicked.connect(self._sort_by)
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
        layout.addLayout(self._sections)
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
        self.resize(780, 620)

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)

    def _place_sections(self, side_by_side: bool) -> None:
        """The boxes in one row; or, with checks and too little room, the checks box under the
        others at full width."""
        if side_by_side == self._side_by_side:
            return
        self._side_by_side = side_by_side
        boxes = self._section_boxes
        for frame in boxes:
            self._sections.removeWidget(frame)
        under = not side_by_side and self.checks_box is not None and len(boxes) > 1
        top = boxes[:-1] if under else boxes
        for column, frame in enumerate(top):
            self._sections.addWidget(frame, 0, column)
        if under:
            self._sections.addWidget(boxes[-1], 1, 0, 1, len(top))
        for column in range(len(boxes)):
            self._sections.setColumnStretch(column, 1 if column < len(top) else 0)

    def _fits_side_by_side(self) -> bool:
        layout = self.layout()
        margins = layout.contentsMargins() if layout is not None else None
        room = self.width() - (margins.left() + margins.right() if margins else 0)
        spacing = self._sections.horizontalSpacing() * (len(self._section_boxes) - 1)
        widest = max((f.minimumSizeHint().width() for f in self._section_boxes), default=0)
        return widest * len(self._section_boxes) + spacing <= room

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_sections(self._fits_side_by_side())

    def _tick_section(self, keys: Sequence[str], on: bool) -> None:
        """A box's All or None: its ticks at once, then one update."""
        for key in keys:
            box = self.boxes[key]
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)
        self._ticks_changed()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._no_default_buttons()  # a dialog makes one default as it shows

    # ---- what a tool's Report changes ----

    NOTE_UNDER = "users"  # the tick checks_note is about: shown while it's ticked

    def fields(self, host: Host, between_tags: str) -> dict[str, str]:
        """An item's own values, by column key (the checks' come from `results`)."""
        return host_fields(self._hosts, host, between_tags)

    def checks_note(self) -> str:
        return _("People's names: keep the file private.")

    def for_import_tip(self) -> str:
        return _("The hosts' own fields, which Import hosts reads back: to move hosts to a list.")

    def unchecked_text(self, n: int) -> str:
        return ngettext(
            "{n} of these hosts wasn't checked yet.", "{n} of these hosts weren't checked yet.", n
        ).format(n=n)

    def refresh_tip(self, wanted: bool) -> str:
        return (
            _("Reads what's ticked in this box again")
            if wanted
            else _("Tick Status or Logged-on users to refresh them")
        )

    def refresh_text(self, n: int) -> str:
        """The button's words: one verb, then how many it reads (the right-click's words)."""
        if n == 1:
            return _("Refresh host")
        if not n:
            return _("Refresh")
        return ngettext("Refresh {n} host", "Refresh {n} hosts", n).format(n=n)

    def nothing_to_refresh(self) -> str:
        return _("No hosts to refresh")

    def left_out_text(self, n: int) -> str:
        return ngettext(
            "{n} with no address is left out", "{n} with no address are left out", n
        ).format(n=n)

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

    def rows(self, between_tags: str = ";", *, on_screen: bool = False) -> list[list[str]]:
        """The picked items' cells, in the preview's order. A Status not read yet is an empty
        cell in a file or a copy; `on_screen` (the preview) says "Not checked" there, as the
        main table does. Either way it sorts last."""
        columns = self.columns()
        rows = []
        for host in self.hosts():
            values = self.fields(host, between_tags)
            values.update(zip(self.CHECKED, self._results(host.id), strict=True))
            rows.append((host, [values[key] for key in columns]))
        if self._sort is not None and self._sort[0] in columns:
            key, descending = self._sort
            at = columns.index(key)
            rows = sorted_by(rows, lambda r: r[0].name, lambda r: r[1][at], descending)
        blank = [i for i, key in enumerate(columns) if key in self.SAYS_NOT_CHECKED]
        if on_screen and blank:
            words = _("Not checked")
            return [
                [words if i in blank and not cell else cell for i, cell in enumerate(cells)]
                for _host, cells in rows
            ]
        return [cells for _host, cells in rows]

    def _sort_by(self, index: int) -> None:
        """A click on a column title: A–Z, or Z–A when it's already sorted A–Z by it."""
        columns = self.columns()
        if not 0 <= index < len(columns):
            return
        key = columns[index]
        descending = self._sort == (key, False)
        self._sort = (key, descending)
        self._fill_preview()

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

    # ---- presets: the built-in one ("For Import"), then the user's own ----

    def _presets(self) -> dict[str, list[str]]:
        saved = self._prefs.get(self.PRESETS_KEY)
        if not isinstance(saved, dict):
            return {}
        return {str(k): self._known(v) for k, v in saved.items() if isinstance(v, list)}

    def _fill_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem(_(self.PRESET_NAME), list(self.FOR_IMPORT))
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
        if name.casefold() == _(self.PRESET_NAME).casefold():
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
            if under := self.boxes.get(self.NOTE_UNDER):
                self.note.setVisible(bool(self.note.text()) and under.isChecked())
            self._title_time(hosts, [place[key] for key in wanted])
            if running is not None:
                done, total = running
                text = _("Refreshing {done} of {total}…").format(done=done, total=total)
                self.checking.setText(text)
            self.checking.setVisible(running is not None)
            self.stop_button.setVisible(running is not None)
            self.refresh_button.setVisible(running is None)
            reached = sum(1 for h in hosts if h.connect_address)
            self.refresh_button.setText(" " + self.refresh_text(reached))
            self.refresh_button.setEnabled(running is None and bool(wanted) and bool(reached))
            if not reached:
                tip = self.nothing_to_refresh()
            else:
                tip = self.refresh_tip(bool(wanted))
                if wanted and reached < len(hosts):
                    tip += "\n" + self.left_out_text(len(hosts) - reached)
            self.refresh_button.setToolTip(tip)
        can_export = running is None and bool(self.columns()) and bool(hosts)
        self.export_button.setEnabled(can_export)
        self.copy_button.setEnabled(can_export)

    def _title_time(self, hosts: Sequence[Host], at: Sequence[int]) -> None:
        """Last check's time: the newest read of the ticked checks among these items (a date
        too when it isn't today); none when none was read."""
        if self.checks_box is None:
            return
        times = (
            [t for h in hosts for i, t in enumerate(self._checked_at(h.id)) if i in at and t]
            if self._checked_at is not None
            else []
        )
        self.checks_time.setText(clock_text(max(times)) if times else "")
        self.checks_time.setVisible(bool(times))

    def _fill_preview(self) -> None:
        self.preview.clear()
        self.preview.setColumnCount(max(len(self.columns()), 1))
        self.preview.setHeaderLabels(self.header() or [""])
        header, columns = self.preview.header(), self.columns()
        sorted_by = self._sort is not None and self._sort[0] in columns
        header.setSortIndicatorShown(sorted_by)
        if self._sort is not None and sorted_by:
            order = Qt.SortOrder.DescendingOrder if self._sort[1] else Qt.SortOrder.AscendingOrder
            header.setSortIndicator(columns.index(self._sort[0]), order)
        for row in self.rows(on_screen=True):
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


def _plain_button(icon: str, color: QColor) -> QPushButton:
    """Refresh or Stop at Last check's foot: a plain button with its icon and words."""
    button = QPushButton()
    button.setAutoDefault(False)  # Enter never refreshes by surprise
    button.setIcon(tabler_icon(icon, color, 16))
    return button
