"""The Printers tool: the list workspace with printers, each with its brand, model, serial number,
asset tag and where its page counters come from, plus opening their web pages."""

import logging
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QMenu

from capypanel.core.hosts.document import starter_list
from capypanel.core.hosts.model import Host, HostListRuleError
from capypanel.core.i18n import _, ngettext
from capypanel.core.printers.printer import with_info
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.hosts import group_path
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.printers_tool.actions import create_actions, retranslate_actions
from capypanel.ui.printers_tool.details import PrinterDetails, PrinterDetailsPanel
from capypanel.ui.printers_tool.dialog import PrinterDialog
from capypanel.ui.printers_tool.table import PrinterTable
from capypanel.ui.printers_tool.toolbar import PrintersToolBar

log = logging.getLogger(__name__)
WEB_PAGES_AT_ONCE = 10  # more selected open only the first ones: a browser tab each


def web_page(printer: Host) -> QUrl | None:
    """The printer's web page: http on its address (or its name). None when that can't be one."""
    target = printer.address or printer.name
    if target.count(":") > 1 and not target.startswith("["):  # an IPv6 address
        target = f"[{target}]"
    url = QUrl(f"http://{target}")
    return url if url.isValid() and url.host() else None


class PrintersTool(ListWorkspace):
    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: PrinterTable = PrinterTable()
        self.details: PrinterDetailsPanel = PrinterDetailsPanel()
        self.toolbar: PrintersToolBar = PrintersToolBar(self.commands)
        super().__init__(
            shell,
            commands=self.commands,
            toolbar=self.toolbar,
            table=self.table,
            details=self.details,
        )
        for action in vars(self.commands).values():
            action.setParent(self)
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self.open_startup_list()
        self.refresh()

    def _fill_inventory(self) -> None:
        a = self.commands
        self.toolbar.inventory_menu.addActions([a.add_printer, a.add_group, a.manage_groups])

    def _connect(self) -> None:
        a = self.commands
        a.add_printer.triggered.connect(self.add_item)
        # Not in any menu bar menu, so their shortcuts (Ctrl+Shift+C, Ctrl+N) live here:
        # toolbar menus only take keys while they're open.
        self.addActions([a.copy_address, a.add_printer])
        # Enter opens web pages only from the printer table, so it never fires while typing.
        a.open_web_page.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.open_web_page)
        a.open_web_page.triggered.connect(self.open_web_pages)
        a.copy_address.triggered.connect(self._copy_address)

    # ---- texts ----

    def all_items_text(self) -> str:
        return _("All printers")

    def items_text(self, n: int) -> str:
        return ngettext("{n} printer", "{n} printers", n).format(n=n)

    def remove_items_text(self, items: Sequence[Host]) -> tuple[str, str]:
        if len(items) == 1:
            text = _("Remove “{name}” from the list?").format(name=items[0].name)
        else:
            text = ngettext(
                "Remove {n} printer from the list?",
                "Remove {n} printers from the list?",
                len(items),
            ).format(n=len(items))
        return _("Remove printers"), text

    def no_list_text(self) -> str:
        return _("No printer list is open.")

    def open_list_title(self) -> str:
        return _("Open a printer list")

    def manage_lists_text(self) -> str:
        return _("&Manage printer lists…")

    def search_fields(self) -> tuple[list[str], str]:
        """Every column that shows, and the notes (which have no column)."""
        table = self.table
        # Each a lower-case word in the list "Search name, address, brand, model, tags, notes".
        words = (
            (table.ADDRESS, _("address")),
            (table.BRAND, _("brand")),
            (table.MODEL, _("model")),
            (table.SERIAL, _("serial number")),
            (table.ASSET_TAG, _("asset tag")),
            (table.TAGS, _("tags")),
        )
        fields = [_("name")]
        fields += [word for column, word in words if not table.isColumnHidden(column)]
        fields.append(_("notes"))  # no column, so always searched
        return fields, _("Searches every printer in the list (Ctrl+F)")

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self.toolbar.retranslate()
        super().retranslate()

    # ---- adding and editing printers ----

    def add_item_action(self) -> QAction:
        return self.commands.add_printer

    def add_item(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        # An empty list gets its first group; one with printers is never started over.
        base = doc.hosts if doc.hosts.groups or doc.hosts.hosts else starter_list()
        dialog = PrinterDialog(self, base, default_group=self.nav.selected_group_id())
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        try:
            added, printer = base.add_host(
                values.name,
                values.group,
                address=values.address,
                tags=values.tags,
                notes=values.notes,
            )
            new = added.update_host(with_info(printer, values.info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        if self._commit(new):
            self.table.select_ids([printer.id])

    def edit_item(self, item: Host) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = PrinterDialog(self, doc.hosts, item)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        edited = replace(
            item,
            name=values.name,
            address=values.address,
            group=values.group,
            tags=values.tags,
            notes=values.notes,
        )
        try:
            new = doc.hosts.update_host(with_info(edited, values.info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        self._commit(new)

    # ---- web pages ----

    def activate_selected(self) -> None:
        self.open_web_pages()

    def open_web_pages(self) -> None:
        """The selected printers' web pages in the default browser, at most 10 at once. Only
        the address is handed over: nothing is fetched or signed into here."""
        printers = self.selected_items()
        if not printers:
            return
        pages = [(p, web_page(p)) for p in printers[:WEB_PAGES_AT_ONCE]]
        opened = 0
        for printer, url in pages:
            if url is not None and QDesktopServices.openUrl(url):
                opened += 1
            else:
                log.warning("Couldn't open the web page of %s (%r)", printer.name, printer.target)
        notes = [ngettext("Opened {n} web page.", "Opened {n} web pages.", opened).format(n=opened)]
        if len(printers) > WEB_PAGES_AT_ONCE:
            notes.append(_("Only the first {n} open at once.").format(n=WEB_PAGES_AT_ONCE))
        if failed := len(pages) - opened:
            notes.append(
                ngettext(
                    "{n} couldn't be opened: check its address.",
                    "{n} couldn't be opened: check their addresses.",
                    failed,
                ).format(n=failed)
            )
        self._shell.show_message(" ".join(notes), 10_000 if len(notes) > 1 else 5000)

    def _copy_address(self) -> None:
        printers = self.selected_items()
        if printers:
            QGuiApplication.clipboard().setText("\n".join(p.target for p in printers))

    # ---- showing ----

    def matches(self, item: Host, needle: str) -> bool:
        """The name and notes, plus every column that shows: only what can be seen."""
        if super().matches(item, needle):
            return True
        table = self.table
        texts = table.row_texts(item)
        return any(
            needle in texts[column].casefold()
            for column in range(1, len(table.COLUMNS))
            if not table.isColumnHidden(column)
        )

    def show_details(self, items: Sequence[Host]) -> None:
        if len(items) == 1 and self._doc is not None:
            printer = items[0]
            details = PrinterDetails(printer, group_path(self._doc.hosts, printer.group))
            self.details.show_printer(details, 1, needle=self._needle())
        else:
            self.details.show_printer(None, len(items), summary=self._summary())

    def _summary(self) -> str:
        """With nothing selected, the Details panel counts the printers shown."""
        rows = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        shown = sum(1 for row in rows if row is not None and row.data(0, ROLE_ID))
        if not shown:
            return ""
        return ngettext("{n} printer shown", "{n} printers shown", shown).format(n=shown)

    def update_tool_state(self, writable: bool, selected: int) -> None:
        doc = self._doc
        a = self.commands
        a.add_printer.setEnabled(writable)
        a.export_printers.setEnabled(doc is not None and bool(doc.hosts.hosts))  # read-only too
        for action in (a.open_web_page, a.copy_address):
            action.setEnabled(selected > 0)  # read-only lists can still open them

    # ---- right-click menus ----

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None  # keeps Ctrl+Shift+C

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        a = self.commands
        # Use first, then copy, then managing the printer: edit, move, remove.
        menu.addAction(a.open_web_page)
        menu.setDefaultAction(a.open_web_page)  # bold: what double-click and Enter do
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)
