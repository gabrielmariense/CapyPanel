"""The Printers tool's part of Settings: Startup, Refresh (the SNMP community string and the low
supply level) and Printer lists."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import credstore
from capypanel.core.hosts import locations
from capypanel.core.i18n import N_, _
from capypanel.ui.dialogs import run_modal
from capypanel.ui.notes import notes
from capypanel.ui.printers_tool import refresh
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import (
    ListsGeneralPage,
    ListsPage,
    Page,
    Section,
    SettingRow,
    add_rows,
)

if TYPE_CHECKING:
    from capypanel.ui.printers_tool.tool import PrintersTool

MAX_COMMUNITY = 255
LOWEST, HIGHEST = 1, 50  # the low supply level's range, in %


class CommunityDialog(QDialog):
    """The SNMP community string's own small window: Save keeps it in Windows Credential
    Manager. An empty one goes back to "public"."""

    def __init__(self, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("SNMP community string"))
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(10)
        column.addWidget(
            notes(
                _("The read-only community string your printers answer to. Most use "
                  "\"public\". It's kept in Windows Credential Manager.")
            )
        )  # fmt: skip
        self.field = QLineEdit()
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setMaxLength(MAX_COMMUNITY)
        column.addWidget(self.field)
        self.show_box = QCheckBox(_("&Show"))
        self.show_box.toggled.connect(
            lambda on: self.field.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        column.addWidget(self.show_box)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = QPushButton(_("&Save"))
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        column.addLayout(buttons)
        self.resize(420, self.sizeHint().height())


class PrintersPage(ListsGeneralPage):
    """Startup, then Refresh: the community string behind Change…, and the low supply level."""

    def __init__(self, *, low: int, community_set: bool, **lists: object) -> None:
        super().__init__(**lists)  # type: ignore[arg-type]
        section = Section(_("Refresh"))
        self.change_button = QPushButton(_("Change…"))
        self.change_button.setAutoDefault(False)
        self.community_row = SettingRow(
            _("SNMP &community string"), self._community_text(community_set), self.change_button
        )
        self.low_level = QSpinBox()
        self.low_level.setRange(LOWEST, HIGHEST)
        self.low_level.setValue(low)
        self.low_level.setSuffix(_(" %"))
        self.low_level.valueChanged.connect(self.changed)
        add_rows(
            section.content,
            self.community_row,
            SettingRow(
                _("&Low supply level"),
                _("A toner, ink, drum or box at or below this shows as low."),
                self.low_level,
            ),
        )
        self.add_section(section)

    def show_community(self, community_set: bool) -> None:
        self.community_row.description.setText(self._community_text(community_set))

    @staticmethod
    def _community_text(community_set: bool) -> str:
        if community_set:
            return _("Set. Kept in Windows Credential Manager, never in a file.")
        return _('Not set: printers are asked with "public".')


class PrintersSettings(SettingsGroup):
    LABEL = N_("Printers")
    TITLES = (N_("General"), N_("Printer lists"))

    general: PrintersPage
    lists: ListsPage

    def __init__(self, tool: "PrintersTool") -> None:
        self._tool = tool
        self._building = False  # pages report changes while they're filled
        self._chosen: Path | None = None  # the list picked in Printer lists, across a rebuild

    def build(self) -> list[tuple[str, Page]]:
        tool, prefs, doc = self._tool, self._tool.prefs, self._tool.document
        self._building = True
        texts = tool.list_texts()
        self.general = PrintersPage(
            low=tool.low_level(),
            community_set=community_is_set(),
            texts=texts,
            start_list=prefs.get(locations.START_KEY, locations.START_LAST),
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            added=locations.added_lists(prefs),
            start_view=tool.start_view(),
            host_list=doc.hosts if doc else None,
        )
        self.lists = ListsPage(
            texts=texts,
            default_list=tool.default_list,
            personal_list=tool.personal_list,
            document=doc,
            added=locations.added_lists(prefs),
            found=tool.found_lists(hidden=True),
            hidden=locations.hidden_lists(prefs),
        )
        for page in (self.general, self.lists):
            page.changed.connect(self._changed)
        self.general.change_button.clicked.connect(self._change_community)
        self.lists.view.open_requested.connect(self._open)
        self._building = False
        return [("printers", self.general), ("printer_lists", self.lists)]

    def before_rebuild(self) -> None:
        self._chosen = self.lists.chosen()

    def after_rebuild(self) -> None:
        if self._chosen is not None:
            self.lists.view.select(self._chosen)

    def _changed(self) -> None:
        if not self._building:
            self._tool.apply_list_prefs(
                self.general.start_choice(),
                self.general.show_first_choice(),
                self.lists.added(),
                self.lists.hidden(),
            )
            self._tool.set_low_level(self.general.low_level.value())
            self._tool.prefs_applied()

    def _change_community(self) -> None:
        dialog = CommunityDialog(self.general.window())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        secret = dialog.field.text().strip()
        try:
            if secret:
                credstore.save(refresh.COMMUNITY, secret)
            else:
                credstore.forget(refresh.COMMUNITY)
        except (OSError, ValueError) as e:
            QMessageBox.warning(
                self.general,
                _("SNMP community string"),
                _("Windows didn't keep it: {error}").format(error=e),
            )
            return
        self.general.show_community(bool(secret))

    def _open(self, path: Path) -> None:
        """A list opened from Printer lists: Settings then shows it as the open one."""
        self._tool.open_list(path)
        doc = self._tool.document
        self.lists.view.list_opened(doc)
        self.general.list_opened(self._tool.start_view(), doc.hosts if doc else None)


def community_is_set() -> bool:
    try:
        return credstore.load(refresh.COMMUNITY) is not None
    except OSError:
        return False
