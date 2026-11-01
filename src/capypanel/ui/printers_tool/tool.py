"""The Printers tool: the list workspace with printers, each with its brand, model, serial number,
asset tag and where its page counters come from, plus opening their web pages and Refresh, which
reads each printer's status, supplies and page counter over SNMP."""

import logging
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from capypanel.core.hosts.document import starter_list
from capypanel.core.hosts.model import Host, HostListRuleError
from capypanel.core.i18n import _, ngettext, npgettext
from capypanel.core.printers.printer import info_of, with_info
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.hosts import group_path
from capypanel.ui.list_workspace.texts import ListTexts
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.printers_tool import status
from capypanel.ui.printers_tool.actions import create_actions, retranslate_actions
from capypanel.ui.printers_tool.attention import (
    AttentionStrip,
    attention_text,
    notice_text,
    why_text,
)
from capypanel.ui.printers_tool.details import PrinterDetails, PrinterDetailsPanel
from capypanel.ui.printers_tool.dialog import PrinterDialog
from capypanel.ui.printers_tool.refresh import (
    V2C,
    V3,
    PrinterRun,
    community,
    kept_logins,
    v3_account,
)
from capypanel.ui.printers_tool.report import PrintersReport
from capypanel.ui.printers_tool.settings import (
    AUTO_EVERY,
    AUTO_REFRESH,
    BARS,
    HIGHEST,
    LOWEST,
    NOTIFY,
    NOTIFY_LOW,
    NOTIFY_OFF,
    NOTIFY_STOPS,
    SNMP_VERSION,
    TEXT,
    TONER_VIEW,
    PrintersSettings,
)
from capypanel.ui.printers_tool.status import Attention, Cell, Checked
from capypanel.ui.printers_tool.table import PrinterTable
from capypanel.ui.printers_tool.toolbar import PrintersToolBar
from capypanel.ui.saved_credentials import KeptLogin

log = logging.getLogger(__name__)
WEB_PAGES_AT_ONCE = 10  # more selected open only the first ones: a browser tab each


def web_page(printer: Host) -> QUrl | None:
    """The printer's web page on its address (or its name): https when the address starts with
    https://, else http. None when that can't be one."""
    target = printer.address or printer.name
    scheme = "http"
    for typed in ("https", "http"):
        if target.lower().startswith(f"{typed}://"):
            scheme, target = typed, target[len(typed) + 3 :]
            break
    if target.count(":") > 1 and not target.startswith("["):  # an IPv6 address
        target = f"[{target}]"
    url = QUrl(f"{scheme}://{target}")
    return url if url.isValid() and url.host() else None


class PrintersTool(ListWorkspace):
    TOOL_ID = "printers"
    ICON = "printer"
    checks_changed = Signal()  # a Refresh started, found something, or ended

    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: PrinterTable = PrinterTable()
        self.details: PrinterDetailsPanel = PrinterDetailsPanel()
        self.toolbar: PrintersToolBar = PrintersToolBar(self.commands)
        self._checked: dict[str, Checked] = {}  # each printer's last Refresh, in memory only
        self.attention_strip = AttentionStrip()
        self._attention: dict[str, Attention] = {}  # the open list's printers that need it
        self._only_attention = False  # the strip's Show: the table lists just those
        self._before_auto: dict[str, Attention] | None = None  # while a Refresh on its own runs
        super().__init__(
            shell,
            commands=self.commands,
            toolbar=self.toolbar,
            table=self.table,
            details=self.details,
        )
        for action in vars(self.commands).values():
            action.setParent(self)
        column = self.items_pane.layout()
        assert isinstance(column, QVBoxLayout)
        column.insertWidget(1, self.attention_strip)  # right under the search box
        self._run: PrinterRun | None = None
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.setText(_("Stop"))
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
        self._auto_timer = QTimer(self)  # Settings: Refresh on its own, if switched on
        self._auto_timer.timeout.connect(self._auto_refresh)
        self._apply_auto_refresh()
        self.table.set_cells(self._cells)
        self.table.bars, self.table.low = self.toner_bars(), self.low_level()
        self.settings_pages = PrintersSettings(self)  # its part of Settings
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self.open_startup_list()
        self.refresh()

    def status_widgets(self) -> list[QWidget]:
        """Shown on the right of the status bar: a Refresh's progress and Stop."""
        return [self._progress, self._stop_button]

    def _fill_inventory(self) -> None:
        a = self.commands
        self.toolbar.inventory_menu.addActions([a.add_printer, a.add_group, a.manage_groups])

    def _connect(self) -> None:
        a = self.commands
        a.add_printer.triggered.connect(self.add_item)
        a.export_printers.triggered.connect(self.export_printers)
        # Not in any menu bar menu, so their shortcuts (Ctrl+Shift+C, Ctrl+N, F5) live here:
        # toolbar menus only take keys while they're open.
        self.addActions([a.copy_address, a.add_printer, a.refresh_shown])
        a.refresh_shown.triggered.connect(lambda: self.check_printers(self.visible_items()))
        a.refresh_selected.triggered.connect(lambda: self.check_printers(self.selected_items()))
        # Enter opens web pages only from the printer table, so it never fires while typing.
        a.open_web_page.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.table.addAction(a.open_web_page)
        a.open_web_page.triggered.connect(self.open_web_pages)
        a.copy_address.triggered.connect(self._copy_address)
        self.attention_strip.show_clicked.connect(self._toggle_attention)
        # Picking a group or a tag, or searching, means browsing again: every printer.
        self.nav.filter_changed.connect(self._leave_attention)
        self.search.textChanged.connect(self._leave_attention)

    # ---- texts ----

    def tool_name(self) -> str:
        return _("Printers")

    def menu_name(self) -> str:
        return _("&Printers")

    def list_texts(self) -> ListTexts:
        return ListTexts(
            kind=self.TOOL_ID,
            everything=_("All printers"),
            lists=_("Printer lists"),
            new=_("New printer list"),
            add=_("Add a printer list"),
            open=_("Open a printer list"),
            remove=_("Remove printer list"),
            manage=_("&Manage printer lists…"),
            no_list=_("No printer list is open."),
            choose_first=_("Open a printer list to choose what it shows first."),
            not_this_kind=_("“{path}” isn't a printer list."),
            file_filter=_("Printer lists (*.json);;All files (*)"),
        )

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

    def selected_text(self, n: int) -> str:
        return npgettext("printers", "{n} selected", "{n} selected", n).format(n=n)

    def found_text(self, n: int) -> str:
        return npgettext("printers", "{n} found", "{n} found", n).format(n=n)

    def counted_text(self, name: str, n: int) -> str:
        return ngettext("{name} ({n} printer)", "{name} ({n} printers)", n).format(name=name, n=n)

    def selected_source_texts(self) -> tuple[str, str]:
        return _("Selected printers"), _("the selected printers")

    def lists_page(self) -> str:
        return "printer_lists"

    def only_tags_text(self, shown: int, total: int) -> str:
        return _("Only printers with all of: {tags} · {shown} of {total} shown").format(
            tags="{tags}", shown=shown, total=total
        )

    def no_match_text(self) -> str:
        return _("No printers in this group have all the picked tags.")

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
        self._stop_button.setText(_("Stop"))
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

    # ---- settings ----

    def settings_group(self) -> PrintersSettings:
        return self.settings_pages

    def low_level(self) -> int:
        """The low supply level from Settings, in %."""
        saved = self.prefs.get("low_level")
        ok = isinstance(saved, int) and not isinstance(saved, bool) and LOWEST <= saved <= HIGHEST
        return saved if ok else status.DEFAULT_LOW  # type: ignore[return-value]

    def set_low_level(self, low: int) -> None:
        if low != self.low_level():
            self.prefs["low_level"] = low
            self.table.low = low
            self._show_all_cells()
            self._count_attention()

    def snmp_version(self) -> str:
        """Settings' SNMP version: V2C (the default) or V3."""
        return V3 if self.prefs.get(SNMP_VERSION) == V3 else V2C

    def set_snmp_version(self, version: str) -> None:
        if version != self.snmp_version():
            self.prefs[SNMP_VERSION] = version

    def auto_refresh(self) -> int:
        """Settings' Refresh on its own: minutes between two, 0 when it's off (the default)."""
        saved = self.prefs.get(AUTO_REFRESH)
        return saved if saved in AUTO_EVERY else 0  # type: ignore[return-value]

    def set_auto_refresh(self, minutes: int) -> None:
        if minutes != self.auto_refresh():
            self.prefs[AUTO_REFRESH] = minutes
            self._apply_auto_refresh()

    def works_in_background(self) -> bool:
        return self.auto_refresh() > 0

    def kept_logins(self) -> list[KeptLogin]:
        return kept_logins()

    def notify_choice(self) -> str:
        """Settings' Windows notification: NOTIFY_OFF, NOTIFY_STOPS (the default) or NOTIFY_LOW."""
        saved = self.prefs.get(NOTIFY)
        return saved if saved in (NOTIFY_OFF, NOTIFY_STOPS, NOTIFY_LOW) else NOTIFY_STOPS  # type: ignore[return-value]

    def set_notify_choice(self, choice: str) -> None:
        if choice != self.notify_choice():
            self.prefs[NOTIFY] = choice

    def _apply_auto_refresh(self) -> None:
        if minutes := self.auto_refresh():
            self._auto_timer.start(minutes * 60_000)
        else:
            self._auto_timer.stop()

    def _auto_refresh(self) -> None:
        """Every printer in the open list, not only the ones shown: warnings count them all.
        Skipped while a Refresh runs, and quietly when there's no SNMP v3 account yet."""
        doc = self._doc
        if self._run is None and doc is not None and doc.hosts.hosts:
            before = dict(self._attention)
            self.check_printers(doc.hosts.hosts, quiet=True)
            if self._run is not None:
                self._before_auto = before

    def _notify_new(self, before: dict[str, Attention]) -> None:
        """One notification for the printers that need attention now and didn't before (or
        for another reason), as Settings asks."""
        wanted = {
            NOTIFY_OFF: (),
            NOTIFY_STOPS: (Attention.STOPPED, Attention.OFFLINE),
            NOTIFY_LOW: tuple(Attention),
        }[self.notify_choice()]
        doc, low = self._doc, self.low_level()
        if doc is None or not wanted:
            return
        lines = []
        for printer in sorted(doc.hosts.hosts, key=lambda p: p.name.casefold()):
            why = self._attention.get(printer.id)
            checked = self._checked.get(printer.id)
            if why in wanted and checked is not None and before.get(printer.id) != why:
                assert why is not None
                reason = why_text(checked, why, low)
                lines.append(_("{name}: {why}").format(name=printer.name, why=reason))
        if lines:
            self.notify_requested.emit(attention_text(len(lines)), notice_text(lines))

    def toner_bars(self) -> bool:
        """Settings' Toner column choice: a bar (True) or text, the default."""
        return self.prefs.get(TONER_VIEW) == BARS

    def set_toner_bars(self, bars: bool) -> None:
        if bars != self.toner_bars():
            self.prefs[TONER_VIEW] = BARS if bars else TEXT
            self.table.bars = bars
            self._show_all_cells()

    def _show_all_cells(self) -> None:
        for printer_id in self._checked:
            self.table.show_cells(printer_id)
        self._selection_changed()

    def prefs_applied(self) -> None:
        """A choice made in Settings was kept: save it, and show the list's new name."""
        self._save_prefs()
        self._update_state()

    # ---- Report ----

    def export_printers(self) -> None:
        """The toolbar's Report: pick printers and columns, then save a CSV file or copy the
        rows. Works on read-only lists too: it changes nothing."""
        doc = self._doc
        if doc is None or not doc.hosts.hosts:
            return
        sources, current = self.report_sources(doc.hosts)
        dialog = PrintersReport(
            self,
            doc.hosts,
            sources,
            current,
            list_name=doc.path.stem,
            prefs=self.prefs,
            save_prefs=self._save_prefs,
            results=self._report_cells,
            # Status, Toner and Total pages come from one read: any box ticked reads them all.
            refresh=lambda printers, *wanted: (
                self.check_printers(printers) if any(wanted) else None
            ),
            stop=self.stop_checks,
            progress=lambda: (self._run.done, self._run.total) if self._run else None,
        )
        self.checks_changed.connect(dialog.checks_changed)
        try:
            run_modal(dialog)
        finally:
            self.checks_changed.disconnect(dialog.checks_changed)
        if dialog.outcome:
            self._shell.show_message(dialog.outcome, 10_000)

    # ---- warnings: the rail's count and the strip ----

    def refresh(self) -> None:
        super().refresh()
        self._count_attention()  # another list, or printers added or removed

    def attention_text(self, n: int) -> str:
        return attention_text(n)

    def attention(self) -> dict[str, Attention]:
        """The open list's printers that need attention, by id, from their last Refresh."""
        return dict(self._attention)

    def _count_attention(self) -> None:
        doc, low = self._doc, self.low_level()
        found: dict[str, Attention] = {}
        for printer in doc.hosts.hosts if doc else ():
            if (why := status.attention(self._checked.get(printer.id), low)) is not None:
                found[printer.id] = why
        changed = found != self._attention
        self._attention = found
        if self._only_attention and not found:
            self._only_attention = False  # nothing left to list: back to every printer
            self._show_items()
        elif self._only_attention and changed:
            self._show_items()
        self.attention_strip.show_found(list(found.values()), self._only_attention)
        if changed:
            self.badge_changed.emit(len(found))

    def show_attention(self) -> None:
        """Only the printers that need attention, out of the whole list: no search, group or
        tags left picked to hide some of them."""
        if not self._attention:
            return
        self._clear_search()
        self.nav.show_view("all", "")
        self.nav.clear_tags()
        self._only_attention = True
        self._show_items()
        self.attention_strip.show_found(list(self._attention.values()), True)

    def _toggle_attention(self) -> None:
        if self._only_attention:
            self._leave_attention()
        else:
            self.show_attention()

    def _leave_attention(self) -> None:
        if self._only_attention:
            self._only_attention = False
            self._show_items()
            self.attention_strip.show_found(list(self._attention.values()), False)

    def fill_table(self, items: Sequence[Host]) -> None:
        super().fill_table(self._narrowed(items))

    def visible_items(self) -> tuple[Host, ...]:
        return tuple(self._narrowed(super().visible_items()))

    def _narrowed(self, items: Sequence[Host]) -> Sequence[Host]:
        if not self._only_attention:
            return items
        return [p for p in items if p.id in self._attention]

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
            details = PrinterDetails(
                printer,
                group_path(self._doc.hosts, printer.group),
                self._checked.get(printer.id),
                self.low_level(),
                (lambda key, value: self.use_value(printer.id, key, value))
                if self._writable() is not None
                else None,
            )
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
        idle = self._run is None
        a.refresh_shown.setEnabled(idle and bool(self.visible_items()))  # read-only lists too
        a.refresh_selected.setEnabled(idle and selected > 0)

    # ---- right-click menus ----

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None  # keeps Ctrl+Shift+C

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        a = self.commands
        # Use first, then copy, then managing the printer: edit, move, remove.
        menu.addAction(a.open_web_page)
        menu.setDefaultAction(a.open_web_page)  # bold: what double-click and Enter do
        menu.addSeparator()
        menu.addAction(a.refresh_selected)
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)

    # ---- Refresh: status, supplies and page counter ----

    def check_printers(self, printers: Sequence[Host], *, quiet: bool = False) -> None:
        """One SNMP read per printer, a few at a time; a printer with no address uses its name."""
        if self._run is not None or not printers:
            return
        secret = community() if self.snmp_version() == V2C else v3_account()
        if secret is None:
            if quiet:
                return
            note = _("Set the SNMP v3 account in Settings › Printers › Refresh first.")
            self._shell.show_message(note, 10_000)
            return
        targets = [(p.id, p.address or p.name) for p in printers]
        run = PrinterRun(targets, secret)
        run.found.connect(self._found)
        run.finished.connect(self._run_finished)
        self._run = run
        self._show_progress()
        self._stop_button.setEnabled(True)
        self._update_state()
        self.checks_changed.emit()
        log.info("Refresh: %d printers", len(targets))
        run.start()

    def stop_checks(self) -> None:
        if self._run is not None:
            self._run.stop()
            self._stop_button.setEnabled(False)  # printers already being read still finish

    def _found(self, printer_id: str, checked: Checked) -> None:
        run = self._run
        if run is None:
            return
        run.done += 1
        self._checked[printer_id] = checked
        self.table.show_cells(printer_id)
        self._count_attention()
        if self.table.selected_ids() in ([printer_id], []):  # its details, or the summary
            self._selection_changed()
        self._show_progress()
        self.checks_changed.emit()

    def _show_progress(self) -> None:
        run = self._run
        if run is not None:
            self._progress.setText(
                _("Checking {done} of {total}…").format(done=run.done, total=run.total)
            )
        self._progress.setVisible(run is not None)
        self._stop_button.setVisible(run is not None)

    def _run_finished(self) -> None:
        run = self._run
        if run is None:
            return
        self._run = None
        before, self._before_auto = self._before_auto, None
        self._show_progress()
        self._update_state()
        self.checks_changed.emit()
        if before is not None and not run.stopped:
            self._notify_new(before)
        if run.stopped and run.done < run.total:
            left = run.total - run.done
            note = ngettext(
                "Stopped: {n} printer wasn't checked.",
                "Stopped: {n} printers weren't checked.",
                left,
            )
            self._shell.show_message(note.format(n=left), 10_000)
        else:
            self._shell.show_message(
                ngettext("Checked {n} printer.", "Checked {n} printers.", run.done).format(
                    n=run.done
                ),
                5000,
            )

    def _cells(self, printer_id: str) -> tuple[Cell, Cell]:
        checked, low = self._checked.get(printer_id), self.low_level()
        return status.status(checked, low), status.toner(checked, low)

    def _report_cells(self, printer_id: str) -> tuple[str, ...]:
        """The Report's Last check columns, in PrintersReport.CHECKED's order."""
        state, toner = self._cells(printer_id)
        checked = self._checked.get(printer_id)
        reading = checked.reading if checked else None
        pages = "" if reading is None or reading.pages is None else str(reading.pages)  # digits
        printer = self._doc.hosts.host(printer_id) if self._doc else None
        if printer and status.counter_error(info_of(printer).counter_source):
            pages = _("Error")  # Details says why
        models = status.toner_models(reading) if reading else ""
        mac, firmware = (reading.mac, reading.firmware) if reading else ("", "")
        return state.text, toner.text, models, pages, mac, firmware

    def use_value(self, printer_id: str, key: str, value: str) -> None:
        """Details' "Use this": the value the printer reports replaces the list's."""
        doc = self._writable()
        printer = doc.hosts.host(printer_id) if doc else None
        if doc is None or printer is None or key not in ("brand", "model", "serial"):
            return
        if key in ("brand", "serial"):
            value = value.upper()  # as the printer dialog keeps them
        info = replace(info_of(printer), **{key: value})
        try:
            new = doc.hosts.update_host(with_info(printer, info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        self._commit(new)
