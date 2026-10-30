"""The printer Details panel: its status, Connection, Supplies, Printer, Page counters, Tags and
Notes. What the last Refresh read sits beside what the list says, never over it: a value the
printer reports differently shows under the list's own, with "Use this"."""

from collections.abc import Callable
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from capypanel.core import i18n
from capypanel.core.hosts.model import Host
from capypanel.core.i18n import _, ngettext
from capypanel.core.printers.printer import DOC360, SNMP, info_of
from capypanel.core.printers.reading import Supply
from capypanel.ui.checks import clock_text
from capypanel.ui.icons import dot_icon
from capypanel.ui.list_workspace.details import DetailsPanel, breakable
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.meter import HEIGHT, draw_meter
from capypanel.ui.printers_tool.status import AMBER, GREY, Checked


@dataclass(frozen=True)
class PrinterDetails:
    printer: Host
    group: str  # its full path
    checked: Checked | None = None  # its last Refresh
    low: int = status.DEFAULT_LOW
    use: Callable[[str, str], None] | None = None  # "Use this": (field, value); None: read-only


def source_text(source: str) -> str:
    """Where a printer's page counters come from, in words."""
    if source == SNMP:
        return "SNMP"
    if source == DOC360:
        return "Doc360 MPS"
    return _("Unknown ({source})").format(source=source)  # kept as the file has it


class Meter(QWidget):
    """A supply's level as a bar, with a tick at the low level."""

    def __init__(self, supply: Supply, low: int) -> None:
        super().__init__()
        self.supply, self.low = supply, low
        self.setFixedHeight(8)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        text = self.palette().color(QPalette.ColorRole.Text)
        draw_meter(painter, QRectF(0, 1, self.width(), HEIGHT), self.supply, self.low, text)
        painter.end()


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

    def item_id(self, shown: object) -> str:
        return shown.printer.id if isinstance(shown, PrinterDetails) else ""

    def build_page(self, layout: QVBoxLayout, shown: object, needle: str) -> None:
        assert isinstance(shown, PrinterDetails)
        printer, info = shown.printer, info_of(shown.printer)
        self._heading(layout, shown)
        about = " ".join(p for p in (info.brand, info.model) if p)
        if about:
            layout.addWidget(self.muted(about))

        self.section(layout, _("Connection"))
        self._fields(layout, (("address", _("Address"), printer.address),
                              ("group", _("Group"), shown.group)))  # fmt: skip

        self._supplies(layout, shown)

        reading = shown.checked.reading if shown.checked else None
        self.section(layout, _("Printer"))
        for key, label, value, read in (
            ("brand", _("Brand"), info.brand, reading.brand if reading else ""),
            ("model", _("Model"), info.model, reading.model if reading else ""),
            ("serial", _("Serial number"), info.serial, reading.serial if reading else ""),
        ):
            self._fields(layout, ((key, label, value),))
            if read and read.casefold() != value.strip().casefold():
                layout.addWidget(self._printer_says(key, read, shown.use))
        self._fields(layout, (("asset_tag", _("Asset tag"), info.asset_tag),))

        self.section(layout, _("Page counters"))
        pages = reading.pages if reading else None
        total = QLocale(i18n.language()).toString(pages) if pages is not None else ""
        source = source_text(info.counter_source)
        self._fields(layout, (("pages", _("Total pages"), total),
                              ("counter_source", _("Source"), source)))  # fmt: skip

        self.section(layout, _("Tags"))
        layout.addWidget(self.chips(printer.tags) if printer.tags else self.muted("—"))

        self.section(layout, _("Notes"))
        layout.addWidget(self.notes(printer.notes, needle) if printer.notes else self.muted("—"))

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
        dot.setPixmap(dot_icon(cell.color or GREY, size).pixmap(size, size))
        dot.setFixedHeight(line + 4)  # centred on the name's first line, even when it wraps
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(name, 1)
        layout.addLayout(row)
        if shown.checked is None:
            words = _("Not checked: use Refresh")
        else:
            words = _("{status} · checked {when}").format(
                status=cell.text, when=clock_text(shown.checked.when)
            )
        under = self.muted(words)
        under.setToolTip(cell.tip)
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
        if not checked.reading.supplies:
            layout.addWidget(self.muted(_("The printer doesn't report its supplies.")))
            return
        for supply in checked.reading.supplies:
            top = QHBoxLayout()
            top.setSpacing(6)
            top.addWidget(self.muted(supply.name), 1)
            level = QLabel(status.level_text(supply))
            if status.is_low(supply, shown.low):
                words = _("{level} · Low") if not supply.receptacle else _("{level} · Nearly full")
                level.setText(words.format(level=status.level_text(supply)))
                level.setStyleSheet(f"color: {AMBER}; font-weight: 600;")
            top.addWidget(level)
            layout.addLayout(top)
            layout.addWidget(Meter(supply, shown.low))
            layout.addSpacing(2)
        layout.addWidget(self.muted(_("The tick is the low level, {low} %.").format(low=shown.low)))

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
        label.setStyleSheet(f"color: {AMBER};")
        if use is not None:
            label.linkActivated.connect(lambda _link: use(key, value))
        return label

    def _fields(self, layout: QVBoxLayout, fields: tuple[tuple[str, str, str], ...]) -> None:
        for key, label, value in fields:
            layout.addWidget(self.muted(label))
            layout.addWidget(self.value(key, value) if value else self.muted("—"))
