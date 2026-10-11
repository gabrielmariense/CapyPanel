"""Inventory > Import hosts…: paste a list or open a CSV file, check and edit the preview, then
add. Nothing changes in the host list until "Add N hosts" is clicked."""

import html
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.bulk import ImportRow, Plan, Verdict, parse, plan, to_csv
from capypanel.core.hosts.model import NO_GROUP, HostList
from capypanel.core.i18n import _, ngettext
from capypanel.ui.groups import TreeMenu, fill_group_menu
from capypanel.ui.hosts import group_choices, group_path
from capypanel.ui.icons import STATUS_COLORS, dot_icon
from capypanel.ui.menus import popup, section
from capypanel.ui.themes import engine as themes

# The preview's columns. The dot says what happens to the row; Warning says why.
DOT, NAME, ADDRESS, GROUP, TAGS, NOTES, WARNING = range(7)
EDITABLE = (NAME, ADDRESS, GROUP, TAGS, NOTES)
NOTES_WIDTH = 200  # notes can be long: the column stops here, the tooltip has it all
COLORS = {Verdict.ADD: STATUS_COLORS["online"], Verdict.SKIP: "#d29922", Verdict.BAD: "#d13438"}


class PreviewTable(QTreeWidget):
    """The rows as they'll be imported. The first edit asks once: editing rewrites the pasted
    list as CSV, so the two always say the same thing."""

    def __init__(self, dialog: "ImportDialog") -> None:
        super().__init__()
        self._dialog = dialog
        self.unlocked = False
        self.setObjectName("grid")
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def edit(self, *args: object) -> bool:  # type: ignore[override]
        if len(args) == 3 and not self._may_edit():
            return False
        return super().edit(*args)  # type: ignore[arg-type]

    def _may_edit(self) -> bool:
        if not self.unlocked:
            answer = QMessageBox.question(
                self,
                _("Edit the list here"),
                _(
                    "Editing in the table rewrites the list above as CSV with a header row "
                    "(name, address, group, tags, notes), so the two always match. Continue?"
                ),
            )
            self.unlocked = answer == QMessageBox.StandardButton.Yes
        return self.unlocked


class ImportDialog(QDialog):
    def __init__(self, parent: QWidget | None, host_list: HostList, group_id: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Import hosts"))
        self._hosts = host_list
        self._rows: list[ImportRow] = []
        self._from_file = False  # a file must start with a header row
        self._plan: Plan | None = None
        self._ignored: tuple[str, ...] = ()

        top = QHBoxLayout()
        top.addWidget(QLabel(_("Paste a list below, or")))
        open_file = QPushButton(_("&Open a CSV file…"))
        open_file.setAutoDefault(False)
        open_file.clicked.connect(self._open_file)
        top.addWidget(open_file)
        top.addStretch(1)
        formats = QPushButton(_("&Formats…"))
        formats.setAutoDefault(False)
        formats.clicked.connect(lambda: FormatsDialog(self).exec())
        top.addWidget(formats)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(_("For example:\nname,address\nPC-0142,10.0.0.42"))
        self.text.setFixedHeight(self.fontMetrics().lineSpacing() * 7 + 12)
        self.text.textChanged.connect(self._typed)
        self._parse_timer = QTimer(self)  # waits for a pause in typing
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(250)
        self._parse_timer.timeout.connect(self._parse)

        self.group = QComboBox()
        for choice_id, label in group_choices(host_list):  # "No group" first
            self.group.addItem(label, choice_id)
        self.group.setCurrentIndex(max(self.group.findData(group_id), 0))
        self.group.currentIndexChanged.connect(self._replan)
        form = QFormLayout()
        form.addRow(_("Hosts with no group &go to:"), self.group)

        self.hint = QLabel(
            _("Double-click a cell, or press F2, to change it; the list above follows. "
              "Right-click for more.")
        )  # fmt: skip
        self.hint.setObjectName("hint")
        self.table = PreviewTable(self)
        self.table.setHeaderLabels(
            ["", _("Name"), _("Address"), _("Group"), _("Tags"), _("Notes"), _("Warning")]
        )
        self.table.itemChanged.connect(self._edited)
        self.table.customContextMenuRequested.connect(self._row_menu)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        self.problem.setTextFormat(Qt.TextFormat.RichText)
        self.problem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        holder = QWidget()
        self._views = QStackedLayout(holder)
        self._views.addWidget(self.table)
        self._views.addWidget(self.problem)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.box.accepted.connect(self.accept)
        self.box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.text)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addWidget(holder, 1)
        layout.addWidget(self.summary)
        layout.addWidget(self.box)
        self._parse()
        self.resize(900, 640)

    # ---- what the window holds ----

    def imported_list(self) -> HostList | None:
        """The list with the hosts added; None when nothing would be added."""
        return self._plan.result if self._plan and self._plan.adding else None

    def added(self) -> int:
        return self._plan.adding if self._plan else 0

    def set_text(self, text: str, *, from_file: bool = False) -> None:
        self._from_file = from_file
        self.text.blockSignals(True)
        self.text.setPlainText(text)
        self.text.blockSignals(False)
        self._parse()

    # ---- reading the list ----

    def _typed(self) -> None:
        self._from_file = False  # typed over: plain lines are fine again
        self._parse_timer.start()

    def _open_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Open a CSV file"), "", _("CSV files (*.csv *.txt);;All files (*)")
        )
        if path:
            self.set_text(read_text(Path(path)), from_file=True)

    def _parse(self) -> None:
        self._parse_timer.stop()
        parsed = parse(self.text.toPlainText(), file=self._from_file)
        self._rows = list(parsed.rows)
        self._ignored = parsed.ignored
        if parsed.needs_header:
            self.problem.setText(needs_header_text())
            self._views.setCurrentIndex(1)
        else:
            self._views.setCurrentIndex(0)
        self.hint.setVisible(not parsed.needs_header)  # nothing to edit
        self._replan()

    def _replan(self) -> None:
        self._plan = plan(self._hosts, self._rows, self.group.currentData() or NO_GROUP)
        self._fill()
        self._summarize()

    # ---- the preview ----

    def _fill(self) -> None:
        current = self.table.currentIndex()
        row, column = current.row(), current.column()
        self.table.blockSignals(True)
        self.table.clear()
        items = self._plan.items if self._plan else ()
        new_groups = set(self._plan.new_groups) if self._plan else set()
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for planned in items:
            r = planned.row
            item = QTreeWidgetItem(
                [
                    "",
                    r.name,
                    r.address,
                    " › ".join(planned.group) or _("No group"),
                    "; ".join(r.tags),
                    " ".join(r.notes.split()),
                    planned.reason,
                ]  # fmt: skip
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setIcon(DOT, dot_icon(COLORS[planned.verdict]))
            item.setToolTip(NOTES, r.notes)
            item.setToolTip(WARNING, planned.reason)  # in full, when the column cuts it
            if planned.group in new_groups:
                item.setToolTip(GROUP, _("A new group: the import creates it"))
            if planned.verdict is not Verdict.ADD:
                for column_ in EDITABLE:
                    item.setForeground(column_, muted)
                item.setForeground(WARNING, self._warning_color(planned.verdict))
            self.table.addTopLevelItem(item)
        for column_ in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column_)
        self.table.setColumnWidth(NOTES, min(self.table.columnWidth(NOTES), NOTES_WIDTH))
        self.table.blockSignals(False)
        if 0 <= row < self.table.topLevelItemCount():
            self.table.setCurrentIndex(self.table.model().index(row, max(column, 0)))

    def _warning_color(self, verdict: Verdict) -> QColor:
        """The warning's colour, made readable on the table's background."""
        palette = self.palette()
        return QColor(
            themes.readable_on(
                QColor(COLORS[verdict]),
                palette.color(QPalette.ColorRole.Base).name(),
                palette.color(QPalette.ColorRole.Text).name(),
            )
        )

    def _summarize(self) -> None:
        ok = self.box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok is not None
        adding = self.added()
        ok.setText(
            ngettext("&Add {n} host", "&Add {n} hosts", adding).format(n=adding)
            if adding
            else _("&Add hosts")
        )
        ok.setEnabled(adding > 0)
        if self._plan is None or not self._plan.items:
            self.summary.setText(_("Nothing changes until you click Add."))
            return
        items = self._plan.items
        parts = [
            "<b>"
            + ngettext("{n} host will be added.", "{n} hosts will be added.", adding).format(
                n=adding
            )
            + "</b>"
        ]
        skipped = sum(1 for i in items if i.verdict is Verdict.SKIP)
        bad = sum(1 for i in items if i.verdict is Verdict.BAD)
        if skipped:
            parts.append(ngettext("{n} skipped.", "{n} skipped.", skipped).format(n=skipped))
        if bad:
            parts.append(ngettext("{n} can't be added.", "{n} can't be added.", bad).format(n=bad))
        if self._plan.new_groups:
            names = ", ".join(" › ".join(p) for p in self._plan.new_groups)
            parts.append(
                ngettext("New group: {names}.", "New groups: {names}.", len(self._plan.new_groups))
                .format(names=names)
            )  # fmt: skip
        if self._ignored:
            parts.append(_("Ignored columns: {names}.").format(names=", ".join(self._ignored)))
        parts.append(_("Nothing changes until you click Add."))
        self.summary.setText(" ".join(parts))

    # ---- editing ----

    def _edited(self, item: QTreeWidgetItem, column: int) -> None:
        index = self.table.indexOfTopLevelItem(item)
        if not 0 <= index < len(self._rows):
            return
        text = item.text(column).strip()
        row = self._rows[index]
        if column == NAME:
            row = replace(row, name=text)
        elif column == ADDRESS:
            row = replace(row, address=text)
        elif column == GROUP:
            row = replace(row, group="/".join(p.strip() for p in text.replace("›", "/").split("/")))
        elif column == TAGS:
            row = replace(row, tags=tuple(t.strip() for t in text.replace(",", ";").split(";")
                                          if t.strip()))  # fmt: skip
        elif column == NOTES:
            row = replace(row, notes=text)
        self._rows[index] = row
        self._write_back()

    def _write_back(self) -> None:
        """The table changed: the list above becomes its CSV, and the preview is planned again."""
        self.text.blockSignals(True)
        self.text.setPlainText(to_csv(self._rows))
        self.text.blockSignals(False)
        self._from_file = False
        # After the editor has closed: rebuilding the table under it would end the edit badly.
        QTimer.singleShot(0, self, self._replan)

    def _selected_rows(self) -> list[int]:
        return sorted(self.table.indexOfTopLevelItem(i) for i in self.table.selectedItems())

    def _row_menu(self, position: QPoint) -> None:
        clicked = self.table.itemAt(position)
        menu = QMenu(self)
        if clicked is not None:
            edit = menu.addAction(_("&Edit cell") + "\tF2")
            column = self.table.columnAt(position.x())
            edit.setEnabled(column in EDITABLE)
            edit.triggered.connect(lambda: self.table.editItem(clicked, column))
            if not clicked.isSelected():
                self.table.setCurrentItem(clicked)
            rows = self._selected_rows()
            section(menu, ngettext("Selected row ({n})", "Selected rows ({n})", len(rows))
                    .format(n=len(rows)))  # fmt: skip
            groups = TreeMenu(_("Put in &group"), menu)
            menu.addMenu(groups)
            fill_group_menu(groups, self._hosts, lambda g: self._put_in(rows, g))
            menu.addAction(_("Set &tags…"), lambda: self._set_tags(rows))
            menu.addSeparator()
            menu.addAction(_("&Leave out of the import") + "\tDel", lambda: self._leave_out(rows))
        below = self.table.indexOfTopLevelItem(clicked) if clicked is not None else -1
        menu.addAction(_("Add a &row below"), lambda: self._add_row(below))
        popup(menu, self.table.viewport().mapToGlobal(position))

    def _change(self, rows: list[int], **changes: object) -> None:
        if not self.table.unlocked and not self.table._may_edit():
            return
        for index in rows:
            self._rows[index] = replace(self._rows[index], **changes)  # type: ignore[arg-type]
        self._write_back()

    def _put_in(self, rows: list[int], group_id: str) -> None:
        self._change(rows, group="/".join(group_path(self._hosts, group_id).split(" › ")))

    def _set_tags(self, rows: list[int]) -> None:
        text, ok = QInputDialog.getText(
            self, _("Set tags"), _("Tags for the selected rows, separated by ;")
        )
        if ok:
            tags = tuple(t.strip() for t in text.replace(",", ";").split(";") if t.strip())
            self._change(rows, tags=tags)

    def _leave_out(self, rows: list[int]) -> None:
        if not self.table.unlocked and not self.table._may_edit():
            return
        for index in reversed(rows):
            del self._rows[index]
        self._write_back()

    def _add_row(self, below: int) -> None:
        if not self.table.unlocked and not self.table._may_edit():
            return
        at = below + 1 if below >= 0 else len(self._rows)
        self._rows.insert(at, ImportRow(""))
        self._write_back()
        # Once the table is rebuilt, type the new row's name.
        QTimer.singleShot(0, self, lambda: self._start_typing(at))

    def _start_typing(self, at: int) -> None:
        item = self.table.topLevelItem(at)
        if item is not None:
            self.table.setCurrentItem(item, NAME)
            self.table.editItem(item, NAME)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self.table.hasFocus():
            rows = self._selected_rows()
            if rows:
                self._leave_out(rows)
                return
        super().keyPressEvent(event)


def needs_header_text() -> str:
    """What a list without a header row needs, one point a line."""
    header = "<b>" + html.escape(_("name, address, group, tags, notes")) + "</b>"
    lines = [
        "<b>" + html.escape(_("This list needs a header row.")) + "</b>",
        html.escape(_("Start it with {header}, in any order.")).replace("{header}", header),
        html.escape(_("Or give just a name and an address on each line.")),
    ]
    return "<br><br>".join(lines)


def read_text(path: Path) -> str:
    """A CSV file's text: UTF-8 (with or without a BOM), or Windows' own encoding, which Excel
    still uses for CSV in many languages."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---- Formats… ----


class FormatsDialog(QDialog):
    """The formats the import reads, one page each: as a list, and as a table."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Formats CapyPanel can import"))
        self._pages = QStackedLayout()
        picker = QHBoxLayout()
        self.buttons = QButtonGroup(self)
        for index, (title, page) in enumerate(self._formats()):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setAutoDefault(False)
            self.buttons.addButton(button, index)
            picker.addWidget(button)
            self._pages.addWidget(page)
        picker.addStretch(1)
        self.buttons.idClicked.connect(self._pages.setCurrentIndex)
        first = self.buttons.button(0)
        if first is not None:
            first.setChecked(True)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(picker)
        layout.addLayout(self._pages)
        layout.addWidget(box)
        self.setMinimumWidth(640)

    def _formats(self) -> list[tuple[str, QWidget]]:
        csv_example = (
            "name,address,group,tags,notes\n"
            "Reception 01,PC-0142,Headquarters/Front desk,kiosk;2nd floor,USB printer\n"
            "Lab 07,10.20.30.47,Branch office,,"
        )
        csv_rows = [
            ["Reception 01", "PC-0142", "Headquarters/Front desk", "kiosk;2nd floor"]
            + ["USB printer"],
            ["Lab 07", "10.20.30.47", "Branch office", "", ""],
        ]
        return [
            (
                _("Hostnames"),
                self._page(
                    _(
                        "One computer per line, by the name it has on the network (its "
                        "hostname), like PC-0142. CapyPanel connects to each by that name, so it "
                        "must be the computer's real name, not a description like “Reception "
                        "desk”: that needs an address next to it (see Name and address)."
                    ),
                    "PC-0142\nPC-0143\nLAB-07",
                ),
            ),
            (
                _("Name and address"),
                self._page(
                    _(
                        "A name and an address on each line, with a comma between them, or a "
                        "tab, as Excel copies two columns. The name can be anything you like; "
                        "the address is the computer's network name or IP address."
                    ),
                    "Reception 01,PC-0142.corp.example.net\nLab 07,10.20.30.47",
                    [_("Name"), _("Address")],
                    [["Reception 01", "PC-0142.corp.example.net"], ["Lab 07", "10.20.30.47"]],
                ),
            ),
            (
                _("CSV with headers"),
                self._page(
                    _(
                        "The first line must name the columns: name, address, group, tags and "
                        "notes, in any order, in English or Portuguese; other columns are "
                        "ignored. A group is a path with / between its levels; tags are "
                        "separated by ;. A CSV file always needs this header row. CSV export "
                        "writes this format, so an exported list can be imported back."
                    ),
                    csv_example,
                    ["name", "address", "group", "tags", "notes"],
                    csv_rows,
                ),
            ),
        ]

    def _page(
        self,
        about: str,
        typed: str,
        header: list[str] | None = None,
        rows: list[list[str]] | None = None,
    ) -> QWidget:
        """A format: what it is, as a list, and (when it has columns) as a table."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 6, 0, 0)
        text = QLabel(about)
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addWidget(self._heading(_("List")))
        listed = QPlainTextEdit(typed)
        listed.setReadOnly(True)
        listed.setFont(QFont("Consolas"))
        listed.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        listed.setFixedHeight(listed.fontMetrics().lineSpacing() * (typed.count("\n") + 1) + 26)
        layout.addWidget(listed)
        if header and rows:
            layout.addWidget(self._heading(_("Table")))
            table = QTreeWidget()
            table.setObjectName("grid")
            table.setRootIsDecorated(False)
            table.setHeaderLabels(header)
            for row in rows:
                table.addTopLevelItem(QTreeWidgetItem(row))
            for column in range(len(header)):
                table.resizeColumnToContents(column)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setFixedHeight(
                table.header().sizeHint().height()
                + sum(table.sizeHintForRow(i) for i in range(len(rows)))
                + 8
            )
            layout.addWidget(table)
        layout.addStretch(1)
        return page

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("detailsSection")
        return label
