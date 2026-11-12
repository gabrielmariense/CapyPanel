"""The printer Details panel: its status and two buttons (Refresh, Web page), then Connection,
Supplies, Printer, Page counters, Tags and Notes, each a part that can be hidden. Labels sit
beside their values, as in Hosts. What the last Refresh read sits beside what the list says,
never over it: a value the printer reports differently shows under the list's own, with "Use
this"."""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QLocale, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from capypanel.core import i18n
from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext, pgettext
from capypanel.core.printers.printer import DOC360, SNMP, info_of
from capypanel.core.printers.reading import Supply
from capypanel.ui.checks import clock_text
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.details import DetailsPanel, breakable
from capypanel.ui.printers_tool import marks as bar_marks
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.printers_tool.meter import HEIGHT, ROOM, draw_meter
from capypanel.ui.printers_tool.status import Checked, Counted, amber, grey


@dataclass(frozen=True)
class PrinterDetails:
    printer: Host
    group: str  # its full path
    checked: Checked | None = None  # its last Refresh
    low: int = status.DEFAULT_LOW
    use: Callable[[str, str], None] | None = None  # "Use this": (field, value); None: read-only
    counted: Counted | None = None  # the last Refresh's Doc360 MPS counters
    set_doc360: Callable[[], None] | None = None  # opens the Doc360 MPS account's window
    marks: tuple[Mark, ...] = ()  # the bars' marks; () is just the low level's
    web: bool = True  # it has a web page to open
    hidden: frozenset[str] = frozenset()  # the parts this person chose not to see


def source_text(source: str) -> str:
    """Where a printer's page counters come from, in words."""
    if source == SNMP:
        return "SNMP"
    if source == DOC360:
        return "Doc360 MPS"
    return _("Unknown ({source})").format(source=source)  # kept as the file has it


class Meter(QWidget):
    """A supply's level as a bar, with its marks."""

    def __init__(self, supply: Supply, marks: tuple[Mark, ...]) -> None:
        super().__init__()
        self.supply, self.marks = supply, marks
        self.setFixedHeight(HEIGHT + 2 * ROOM)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        text = self.palette().color(QPalette.ColorRole.Text)
        bar = QRectF(0, ROOM, self.width(), HEIGHT)
        draw_meter(painter, bar, self.supply, self.marks, text)
        painter.end()


def button_words() -> dict[str, str]:
    """The buttons' short words (nine letters at most), as on Hosts' Details buttons."""
    return {"refresh": pgettext("button", "Refresh"), "web": pgettext("button", "Web page")}


class PrinterDetailsPanel(DetailsPanel):
    refresh_clicked = Signal()  # Refresh: this printer
    web_clicked = Signal()  # Web page: this printer's

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

    def item_id(self, shown: object) -> str:
        return shown.printer.id if isinstance(shown, PrinterDetails) else ""

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, PrinterDetails)
        printer, info, hidden = shown.printer, info_of(shown.printer), shown.hidden
        self._heading(layout, shown)
        layout.addSpacing(6)
        layout.addWidget(self._button_grid(shown))

        reading = shown.checked.reading if shown.checked else None
        mac, firmware = (reading.mac, reading.firmware) if reading else ("", "")
        if "connection" not in hidden:
            self.section(layout, _("Connection"))
            self._fields(layout, (("address", _("Address"), printer.address),
                                  ("group", _("Group"), shown.group),
                                  ("mac", _("MAC address"), mac)))  # fmt: skip

        if "supplies" not in hidden:
            self._supplies(layout, shown)

        if "printer" not in hidden:  # brand and model are said here, once
            self.section(layout, _("Printer"))
            grid = self._grid(layout)
            for key, label, value, read in (
                ("brand", _("Brand"), info.brand, reading.brand if reading else ""),
                ("model", _("Model"), info.model, reading.model if reading else ""),
                ("serial", _("Serial number"), info.serial, reading.serial if reading else ""),
            ):
                self._row(grid, key, label, value)
                if read and read.casefold() != value.strip().casefold():
                    grid.addWidget(self._printer_says(key, read, shown.use), grid.rowCount(), 1)
            self._row(grid, "asset_tag", _("Asset tag"), info.asset_tag)
            self._row(grid, "firmware", _("Firmware"), firmware)

        if "pages" not in hidden:
            self._page_counters(layout, shown)

        if "tags" not in hidden:
            self.section(layout, _("Tags"))
            layout.addWidget(self.chips(printer.tags) if printer.tags else self.muted("—"))

        if "notes" not in hidden:
            self.section(layout, _("Notes"))
            layout.addWidget(
                self.notes(printer.notes, needle) if printer.notes else self.muted("—")
            )
        self.hidden_line(layout, len(hidden))

    def _button_grid(self, shown: PrinterDetails) -> QWidget:
        """Hosts' grid of worded buttons, with Printers' fixed row: Refresh, Web page."""
        widget = QWidget()
        column = QVBoxLayout(widget)
        column.setContentsMargins(0, 0, 0, 0)
        text = self.palette().color(QPalette.ColorRole.Text)
        words = button_words()
        refresh = self.word_button("refresh", text, words["refresh"], _("Refresh printer"))
        refresh.clicked.connect(self.refresh_clicked)
        web = self.word_button("world", text, words["web"], _("Open web page"))
        web.clicked.connect(self.web_clicked)
        web.setEnabled(shown.web)
        self.buttons = {"refresh": refresh, "web": web}
        column.addLayout(self.button_rows([refresh, web], self._button_width()))
        return widget

    def _button_width(self) -> int:
        return self.grid_width(list(button_words().values()))

    def minimum_width(self) -> int:
        return self.grid_minimum(self._button_width())

    def _page_counters(self, layout: QVBoxLayout, shown: PrinterDetails) -> None:
        """Total pages from the printer itself, or from Doc360 MPS with when it was fetched
        (never the printer's own counter then: it isn't the source)."""
        self.section(layout, _("Page counters"))
        info, checked = info_of(shown.printer), shown.checked
        reading = checked.reading if checked else None
        pages, error, tip = reading.pages if reading else None, "", ""
        source = source_text(info.counter_source)
        if info.counter_source == DOC360:
            pages, error = status.doc360_pages(info, reading, shown.counted)
            if shown.counted is not None:
                when = clock_text(shown.counted.when)
                source = _("{source} · fetched {when}").format(source=source, when=when)
                tip = status.doc360_tip(shown.counted)
        total = QLocale(i18n.language()).toString(pages) if pages is not None else ""
        if error:
            total = _("Error: {why}").format(why=error)
        grid = self._grid(layout)
        for key, label, value in (("pages", _("Total pages"), total),
                                  ("counter_source", _("Source"), source)):  # fmt: skip
            self._row(grid, key, label, value).setToolTip(tip)
        if error and shown.counted and shown.counted.account:
            self._account_button(layout, shown)
        if pages is not None and (month := status.older_text(shown.counted)):
            warning = QLabel(
                _("⚠ From {month}: Doc360 MPS has no counts for this month yet. Check the "
                  "portal before using this number.").format(month=month)
            )  # fmt: skip
            warning.setObjectName("doc360Older")
            warning.setWordWrap(True)
            warning.setStyleSheet(f"color: {amber()};")
            layout.addWidget(warning)

    def _account_button(self, layout: QVBoxLayout, shown: PrinterDetails) -> None:
        """Under a missing or refused Doc360 login: its window, straight from here."""
        if shown.set_doc360 is None:
            return
        missing = shown.counted is not None and shown.counted.account == status.NO_ACCOUNT
        button = QPushButton(_("Set the account…") if missing else _("Change the account…"))
        button.setObjectName("doc360Account")
        button.setAutoDefault(False)
        button.clicked.connect(shown.set_doc360)
        row = QHBoxLayout()
        row.setContentsMargins(0, 4, 0, 0)
        row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

    def _heading(self, layout: QVBoxLayout, shown: PrinterDetails) -> None:
        """Like Hosts': a status dot by the name, then "status · checked 14:32"."""
        row = QHBoxLayout()
        row.setSpacing(4)
        name = self.value("name", shown.printer.name)
        font = QFont(name.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.25)
        name.setFont(font)
        cell = status.status(shown.checked, shown.low)
        line = QFontMetrics(font).height()
        size = round(line * 0.5)
        dot = QLabel()
        dot.setPixmap(dot_icon(cell.color or grey(), size).pixmap(size, size))
        dot.setFixedHeight(line + 4)  # centred on the name's first line, even when it wraps
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(name, 1)
        layout.addLayout(row)
        if shown.checked is None:
            words = _("Not checked: use Refresh")
        else:
            words = _("{status} · checked {when}").format(
                status=cell.said(), when=clock_text(shown.checked.when)
            )
        under = self.muted(words)
        under.setToolTip(status.plain_tip(cell.tip))
        layout.addWidget(under)
        reading = shown.checked.reading if shown.checked else None
        for message in reading.messages if reading else ():  # the printer's own words, in full
            said = QLabel(breakable(message))
            said.setTextFormat(Qt.TextFormat.PlainText)  # what a printer sends is never markup
            said.setWordWrap(True)
            layout.addWidget(said)

    def _supplies(self, layout: QVBoxLayout, shown: PrinterDetails) -> None:
        self.section(layout, _("Supplies"))
        checked = shown.checked
        if checked is None:
            layout.addWidget(self.muted(_("Not checked: use Refresh")))
            return
        if checked.reading is None:
            layout.addWidget(self.muted("—"))
            return
        marks = shown.marks or (Mark(shown.low, low=True),)
        if not checked.reading.supplies:
            layout.addWidget(self.muted(_("The printer doesn't report its supplies.")))
            return
        for supply in checked.reading.supplies:
            top = QHBoxLayout()
            top.setSpacing(6)
            name = self.muted(supply.name)
            name.setTextFormat(Qt.TextFormat.PlainText)  # the printer's own words
            top.addWidget(name, 1)
            if not status.reports_level(supply):  # an empty bar would only look like 0 %
                layout.addLayout(top)
                layout.addWidget(self.muted(status.no_level_text()))
                layout.addSpacing(2)
                continue
            level = QLabel(status.level_text(supply))
            if status.is_low(supply, shown.low):
                words = _("{level} · Low") if not supply.receptacle else _("{level} · Nearly full")
                level.setText(words.format(level=status.level_text(supply)))
                level.setStyleSheet(f"color: {amber()}; font-weight: 600;")
            top.addWidget(level)
            layout.addLayout(top)
            layout.addWidget(Meter(supply, marks))
            layout.addSpacing(2)
        layout.addWidget(self.muted(bar_marks.hint(marks)))

    def _printer_says(self, key: str, value: str, use: Callable[[str, str], None] | None) -> QLabel:
        """What the printer reports instead of the list's value; "Use this" copies it over."""
        words = _("The printer says {value}").format(value=f"<b>{escape(value)}</b>")
        if use is not None:
            link = self.palette().color(QPalette.ColorRole.Link).name()
            words += f" · <a href='use' style='color:{link}'>{escape(_('Use this'))}</a>"
        label = QLabel(f"⚠ {words}")
        label.setObjectName(f"printerSays_{key}")
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {amber()};")
        if use is not None:
            label.linkActivated.connect(lambda _link: use(key, value))
        return label

    def _fields(self, layout: QVBoxLayout, fields: tuple[tuple[str, str, str], ...]) -> None:
        grid = self._grid(layout)
        for key, label, value in fields:
            self._row(grid, key, label, value)

    @staticmethod
    def _grid(layout: QVBoxLayout) -> QGridLayout:
        """Hosts' label-and-value grid: a label on the left, its value on the same line, every
        value at the same x."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return grid

    def _row(self, grid: QGridLayout, key: str, label: str, value: str) -> QWidget:
        """One label and its value (a dash when there's none), on the grid's next line."""
        row = grid.rowCount() if grid.count() else 0
        name = QLabel(label)  # never wraps: the column is as wide as its widest label
        name.setObjectName("hint")
        shown = self.value(key, value) if value else self.muted("—")
        grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(shown, row, 1, Qt.AlignmentFlag.AlignVCenter)
        return shown
