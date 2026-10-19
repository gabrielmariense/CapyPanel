"""Adding and editing a printer: what the host dialog asks (name, address, group, tags, notes),
plus the printer's own details."""

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.model import MAX_ADDRESS, NO_GROUP, Host, HostList
from capypanel.core.i18n import _
from capypanel.core.printers.printer import COUNTER_SOURCES, PrinterInfo, info_of
from capypanel.ui.hosts import MAX_NAME, TagEdit, group_choices
from capypanel.ui.printers_tool.details import source_text

MAX_FIELD = 100  # brand, model, serial number, asset tag
COMMON_BRANDS = ("BROTHER", "CANON", "EPSON", "HP", "KYOCERA", "LEXMARK", "RICOH", "SAMSUNG",
                 "XEROX", "ZEBRA")  # fmt: skip


@dataclass(frozen=True)
class PrinterValues:
    name: str
    address: str
    group: str
    tags: tuple[str, ...]
    notes: str
    info: PrinterInfo


class PrinterDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        printers: HostList,
        printer: Host | None = None,
        default_group: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Edit printer") if printer else _("Add printer"))
        info = info_of(printer) if printer else PrinterInfo()
        self._extra = info.extra  # values this version can't read, kept as they are

        self.name = QLineEdit(printer.name if printer else "")
        self.name.setMaxLength(MAX_NAME)
        self.address = QLineEdit(printer.address if printer else "")
        self.address.setMaxLength(MAX_ADDRESS)
        self.address.setPlaceholderText(_("IP address or network name"))
        self.group = QComboBox()
        for group_id, label in group_choices(printers):
            self.group.addItem(label, group_id)
        wanted = printer.group if printer else (default_group or NO_GROUP)
        self.group.setCurrentIndex(max(self.group.findData(wanted), 0))
        self.tags = TagEdit(known=printers.all_tags())
        self.tags.set_tags(printer.tags if printer else ())
        # Brands are typed in capitals, so one brand never shows up twice in the table.
        self.brand = QComboBox()
        self.brand.setEditable(True)
        known = {info_of(h).brand for h in printers.hosts}
        self.brand.addItems(sorted({b.upper() for b in (*COMMON_BRANDS, *known) if b}))
        self.brand.setCurrentText(info.brand)
        line = self.brand.lineEdit()
        if line is not None:
            line.setMaxLength(MAX_FIELD)
        self.model = QLineEdit(info.model)
        self.serial = QLineEdit(info.serial)
        self.asset_tag = QLineEdit(info.asset_tag)
        for field in (self.model, self.serial, self.asset_tag):
            field.setMaxLength(MAX_FIELD)
        self.source = QComboBox()
        sources: list[str] = list(COUNTER_SOURCES)
        if info.counter_source not in sources:
            sources.append(info.counter_source)  # kept as the file has it
        for source in sources:
            self.source.addItem(source_text(source), source)
        self.source.setCurrentIndex(sources.index(info.counter_source))
        self.notes = QPlainTextEdit(printer.notes if printer else "")
        self.notes.setTabChangesFocus(True)

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("&Group:"), self.group)
        tags_label = QLabel(_("&Tags:"))
        tags_label.setBuddy(self.tags.input)  # Alt+T goes to the text box inside the field
        form.addRow(tags_label, self.tags)
        form.addRow(_("&Brand:"), self.brand)
        form.addRow(_("&Model:"), self.model)
        form.addRow(_("&Serial number:"), self.serial)
        form.addRow(_("Ass&et tag:"), self.asset_tag)
        form.addRow(_("Page &counters:"), self.source)
        form.addRow(_("N&otes:"), self.notes)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.name.textChanged.connect(self._update_ok)
        self._update_ok()
        self.resize(460, self.sizeHint().height())

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.name.text().strip()) and self.group.count() > 0)

    def values(self) -> PrinterValues:
        info = PrinterInfo(
            brand=self.brand.currentText().strip().upper(),
            model=self.model.text().strip(),
            serial=self.serial.text().strip().upper(),
            asset_tag=self.asset_tag.text().strip(),
            counter_source=str(self.source.currentData()),
            extra=self._extra,
        )
        return PrinterValues(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            group=str(self.group.currentData()),
            tags=self.tags.tags(),
            notes=self.notes.toPlainText().strip(),
            info=info,
        )
