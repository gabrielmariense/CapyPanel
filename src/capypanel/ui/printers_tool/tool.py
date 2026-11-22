import logging
from collections.abc import Callable, Collection, Sequence
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QDialog, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from capypanel.core.hosts.document import OpenList, starter_list
from capypanel.core.hosts.model import NO_GROUP, Group, Host, HostListRuleError
from capypanel.core.i18n import _, ngettext, npgettext, pgettext
from capypanel.core.printers.printer import DOC360, info_of, with_info
from capypanel.core.printers.reading import Device, Problem, Reading, State, Supply, SupplyKind
from capypanel.ui.dialogs import run_modal
from capypanel.ui.groups import ROLE_ID
from capypanel.ui.guides import Guide, Step
from capypanel.ui.hosts import group_path
from capypanel.ui.list_workspace.customize import Part
from capypanel.ui.list_workspace.panels import SAMPLE_ID, is_sample, sample_tag
from capypanel.ui.list_workspace.texts import EmptyTexts, ListTexts
from capypanel.ui.list_workspace.workspace import ListWorkspace
from capypanel.ui.main_window.tool import Shell
from capypanel.ui.menus import shortcut_text
from capypanel.ui.printers_tool import marks, status
from capypanel.ui.printers_tool.actions import create_actions, retranslate_actions
from capypanel.ui.printers_tool.attention import (
    AttentionStrip,
    attention_text,
    notice_text,
    why_text,
)
from capypanel.ui.printers_tool.details import PrinterDetails, PrinterDetailsPanel
from capypanel.ui.printers_tool.dialog import PrinterDialog
from capypanel.ui.printers_tool.import_printers import ImportPrintersDialog
from capypanel.ui.printers_tool.marks import Mark
from capypanel.ui.printers_tool.refresh import (
    V2C,
    V3,
    PrinterRun,
    community,
    doc360_account,
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
    SNMP_VERSION,
    TEXT,
    TONER_VIEW,
    WARN_HERE,
    WARN_NOTIFY,
    PrintersSettings,
    change_doc360_account,
)
from capypanel.ui.printers_tool.status import DEFAULT_REASONS, Cell, Checked, Counted, Reason
from capypanel.ui.printers_tool.table import PrinterTable
from capypanel.ui.printers_tool.toolbar import PrintersToolBar
from capypanel.ui.shortcuts import KeyCommand

log = logging.getLogger(__name__)
WEB_PAGES_AT_ONCE = 10


def web_page(printer: Host) -> QUrl | None:
    target = printer.address or printer.name
    scheme = "http"
    for typed in ("https", "http"):
        if target.lower().startswith(f"{typed}://"):
            scheme, target = typed, target[len(typed) + 3 :]
            break
    if target.count(":") > 1 and not target.startswith("["):
        target = f"[{target}]"
    url = QUrl(f"{scheme}://{target}")
    return url if url.isValid() and url.host() else None


def refresh_words(refresh: QAction) -> str:
    keys = shortcut_text(refresh)
    if not keys:
        return _("Reads the status, toner and page count of every printer shown. Nothing is read "
                 "until you press it.")  # fmt: skip
    return _("Reads the status, toner and page count of every printer shown. Nothing is read "
             "until you press it or {key}.").format(key=keys)  # fmt: skip


class PrintersTool(ListWorkspace):
    TOOL_ID = "printers"
    ICON = "printer"
    HELP_PLACE = "printers/printers/"
    checks_changed = Signal()

    def __init__(self, shell: Shell):
        self.commands = create_actions(None)  # owned by this widget once it exists
        self.table: PrinterTable = PrinterTable()
        self.details: PrinterDetailsPanel = PrinterDetailsPanel()
        self.toolbar: PrintersToolBar = PrintersToolBar(self.commands)
        self._checked: dict[str, Checked] = {}
        self._counted: Counted | None = None
        self.attention_strip = AttentionStrip()
        self._attention: dict[str, Reason] = {}
        self._only_attention = False
        self._before_auto: dict[str, Reason] | None = None
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
        column.insertWidget(1, self.attention_strip)
        self._run: PrinterRun | None = None
        self._progress = QLabel()
        self._stop_button = QToolButton()
        self._stop_button.setText(_("Stop"))
        self._stop_button.clicked.connect(self.stop_checks)
        for widget in (self._progress, self._stop_button):
            widget.hide()
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_refresh)
        self._apply_auto_refresh()
        self.table.set_cells(self._cells)
        self.table.bars, self.table.marks = self.toner_bars(), self.bar_marks()
        self.settings_pages = PrintersSettings(self)
        self._fill_inventory()
        self._connect()
        self.restore_layout()
        self.open_first_list()

    def status_widgets(self) -> list[QWidget]:
        return [self._progress, self._stop_button]

    def _fill_inventory(self) -> None:
        a = self.commands
        inventory = self.toolbar.inventory_menu
        inventory.addActions([a.add_printer, a.add_group, a.manage_groups])
        inventory.addAction(self.sort_groups_action)
        inventory.addSeparator()
        inventory.addAction(a.import_printers)

    def _connect(self) -> None:
        a = self.commands
        a.add_printer.triggered.connect(self.add_item)
        a.import_printers.triggered.connect(self.import_printers)
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
        self.details.refresh_clicked.connect(lambda: self.check_printers(self.selected_items()))
        self.details.web_clicked.connect(self.open_web_pages)
        self.attention_strip.show_clicked.connect(self._toggle_attention)
        self.nav.filter_changed.connect(self._leave_attention)
        self.search.textChanged.connect(self._leave_attention)

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
            not_this_kind_place="printers-not-a-list",
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
        return "printers"

    def only_tags_text(self, shown: int, total: int) -> str:
        return _("Only printers with all of: {tags} · {shown} of {total} shown").format(
            tags="{tags}", shown=shown, total=total
        )

    def no_match_text(self) -> str:
        return _("No printers in this group have all the picked tags.")

    def search_fields(self) -> tuple[list[str], str]:
        table = self.table
        words = (
            (table.ADDRESS, _("address")),
            (table.STATUS, _("status")),
            (table.BRAND, _("brand")),
            (table.MODEL, _("model")),
            (table.SERIAL, _("serial number")),
            (table.ASSET_TAG, _("asset tag")),
            (table.TAGS, _("tags")),
        )
        fields = [_("name")]
        fields += [word for column, word in words if not table.isColumnHidden(column)]
        fields.append(_("notes"))
        return fields, _("Searches every printer in the list (Ctrl+F)")

    def key_commands(self) -> list[KeyCommand]:
        fixed = f"{self.TOOL_ID}.refresh_selected"
        return [
            replace(c, name=lambda: _("Re&fresh printer")) if c.id == fixed else c
            for c in super().key_commands()
        ]

    def retranslate(self) -> None:
        retranslate_actions(self.commands)
        self._stop_button.setText(_("Stop"))
        self.toolbar.retranslate()
        super().retranslate()

    def guide(self) -> Guide:
        bar, table = self.toolbar, self.table

        def status_and_toner() -> QRect | None:
            header = table.header()
            shown = [c for c in (table.STATUS, table.TONER) if not header.isSectionHidden(c)]
            if not shown or not table.isVisible():
                return None
            left = min(header.sectionViewportPosition(c) for c in shown)
            right = max(header.sectionViewportPosition(c) + header.sectionSize(c) for c in shown)
            corner = header.mapTo(self.window(), QPoint(left, 0))
            return QRect(corner, QSize(right - left, header.height() + table.viewport().height()))

        def rail_icon() -> QWidget | None:
            rail = getattr(self.window(), "rail", None)
            return getattr(rail, "buttons", {}).get("printers")

        def attention() -> list[QWidget]:
            strip = self.attention_strip
            found = [w for w in (rail_icon(),) if w is not None]
            return found + ([strip] if strip.isVisibleTo(self) else [])

        def settings(page: str) -> tuple[str, Callable[[], None]]:
            return _("Open Settings"), lambda: self._shell.open_settings(page)

        def steps() -> list[Step]:
            return [
                Step(_("Your printer lists"),
                     _("Pick a list here: the shared one everyone on this PC sees, your "
                       "personal one, or one you added. Click a group below it to see just that "
                       "group's printers."), lambda: self.nav),
                Step(_("Tags"),
                     _("Tags mark printers across groups. The sample printer has one, \"{tag}\". "
                       "Pick one or more to see only the printers that have them.").format(
                         tag=sample_tag()), lambda: self.nav.tags),
                Step(_("Add printers"),
                     _("Inventory › Add printer only needs a name and the address. A Refresh "
                       "reads the toner, and Details shows the brand, model and serial number the "
                       "printer reports, ready to copy in with Use this."),
                     lambda: bar.inventory_button),
                Step(_("Your printers"),
                     _("The list's printers are here. Pick one to see everything about it in "
                       "Details. A right-click on a printer shows what you can do with it, and a "
                       "double-click opens its web page."),
                     lambda: None, lambda: table, keep_clear=lambda: self.details,
                     area=lambda: self.sample_row(self.window())),
                Step(pgettext("printers", "Refresh all"),
                     refresh_words(self.commands.refresh_shown), lambda: bar.refresh_button),
                Step(_("Status and Toner"),
                     _("After a Refresh, the dot shows how each printer is: green is working, "
                       "amber needs attention, red has stopped and grey didn't answer. Toner shows "
                       "the lowest one, in amber once it runs low."),
                     lambda: None, lambda: table, area=status_and_toner),
                Step(_("Printers that need attention"),
                     _("If a Refresh finds printers stopped, offline or low, a red count shows up "
                       "here. A strip above the table lists them, with Show."),
                     attention, lambda: table),
                Step(_("Refresh on its own"),
                     _("CapyPanel can refresh your printers by itself: you pick every 5, 15, 30 "
                       "or 60 minutes in Settings › Printers › Warnings and supplies. It's off "
                       "until you do. Then, by default, a Windows notification tells you when one "
                       "goes offline, jams, runs out of toner or runs low."),
                     lambda: None, lambda: table, action=settings("printer_warnings")),
                Step(_("If nothing shows up"),
                     _("CapyPanel reads printers over SNMP and never changes anything on them. "
                       "Most answer to the community \"public\". If yours use another one, or "
                       "SNMP v3, set it in Settings › Printers › Connecting."),
                     lambda: None, lambda: table, action=settings("printer_connecting")),
            ]  # fmt: skip

        return Guide("printers", steps, docs="printers/checking/", setup=self.show_sample,
                     cleanup=self.hide_sample)  # fmt: skip

    def sample_items(self, group: str) -> list[Host]:
        """The guides' sample printers, one per status, at documentation addresses (192.0.2.x):
        Refresh and Open web page leave every sample out (is_sample)."""
        name, tags, notes = _("PRN-SAMPLE"), (sample_tag(),), _("Shown only while a guide is open.")
        return [
            Host(id=SAMPLE_ID if n == 1 else f"{SAMPLE_ID}-{n}", name=name if n == 1 else
                 f"{name}-{n}", group=group, address=f"192.0.2.{19 + n}", tags=tags, notes=notes)
            for n in range(1, 5)
        ]  # fmt: skip

    def show_sample(self) -> None:
        super().show_sample()
        if not self.sample_shown():
            return
        now = datetime.now()
        toner = SupplyKind.TONER

        def reading(state: State, device: Device, percent: int, jam: bool = False) -> Checked:
            return Checked(now, Reading(
                state=state, device=device, supplies=(Supply("Black Toner", toner, percent),),
                problems=frozenset({Problem.JAMMED}) if jam else frozenset(),
            ))  # fmt: skip

        made = {
            SAMPLE_ID: reading(State.IDLE, Device.RUNNING, 64),
            f"{SAMPLE_ID}-2": reading(State.IDLE, Device.RUNNING, 7),
            f"{SAMPLE_ID}-3": reading(State.OTHER, Device.DOWN, 46, jam=True),
            f"{SAMPLE_ID}-4": Checked(now, offline=True),
        }
        for printer_id, checked in made.items():
            self._checked[printer_id] = checked
            self.table.show_cells(printer_id)
        self._count_attention()
        self._selection_changed()

    def hide_sample(self) -> None:
        for printer_id in [k for k in self._checked if is_sample(k)]:
            del self._checked[printer_id]
        super().hide_sample()
        self._count_attention()

    def restyle(self) -> None:
        super().restyle()
        self.table.refill()
        self.attention_strip.restyle()
        self._selection_changed()

    def add_item_action(self) -> QAction:
        return self.commands.add_printer

    def add_item(self) -> None:
        doc = self._writable()
        if doc is None:
            return
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

    def import_printers(self) -> None:
        doc = self._writable()
        if doc is None:
            return
        dialog = ImportPrintersDialog(self, doc.hosts, self.nav.selected_group_id() or NO_GROUP)
        new = dialog.imported_list() if run_modal(dialog) == QDialog.DialogCode.Accepted else None
        if new is not None and self._commit(new):
            added = dialog.added()
            note = ngettext("Added {n} printer.", "Added {n} printers.", added).format(n=added)
            self._shell.show_message(note, 10_000)

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

    def settings_group(self) -> PrintersSettings:
        return self.settings_pages

    def low_level(self) -> int:
        saved = self.prefs.get("low_level")
        ok = isinstance(saved, int) and not isinstance(saved, bool) and LOWEST <= saved <= HIGHEST
        return saved if ok else status.DEFAULT_LOW  # type: ignore[return-value]

    def _choice[T](self, key: str, allowed: Collection[T], default: T) -> T:
        saved = self.prefs.get(key)
        return saved if saved in allowed else default  # type: ignore[return-value]

    def _change(self, key: str, value: object, current: object) -> bool:
        if value == current:
            return False
        self.prefs[key] = value
        return True

    def set_low_level(self, low: int) -> None:
        if self._change("low_level", low, self.low_level()):
            self.table.marks = self.bar_marks()
            self._show_all_cells()
            self._count_attention()

    def bar_marks(self) -> tuple[Mark, ...]:
        return marks.load(self.prefs, self.low_level())

    def set_bar_marks(self, chosen: tuple[Mark, ...]) -> None:
        marks.save(self.prefs, chosen)
        self.table.marks = self.bar_marks()
        self.table.viewport().update()
        self._selection_changed()

    def snmp_version(self) -> str:
        return self._choice(SNMP_VERSION, (V2C, V3), V2C)

    def set_snmp_version(self, version: str) -> None:
        self._change(SNMP_VERSION, version, self.snmp_version())

    def auto_refresh(self) -> int:
        return self._choice(AUTO_REFRESH, AUTO_EVERY, 0)

    def set_auto_refresh(self, minutes: int) -> None:
        if self._change(AUTO_REFRESH, minutes, self.auto_refresh()):
            self._apply_auto_refresh()

    def works_in_background(self) -> bool:
        return self.auto_refresh() > 0

    def warn_reasons(self) -> frozenset[Reason]:
        return self._reasons(WARN_HERE, DEFAULT_REASONS)

    def notify_reasons(self) -> frozenset[Reason]:
        """Settings' Warnings, Windows notification. Until 0.27 it was one choice: Off, stopped
        or offline (now the defaults), or that and low supplies (now every reason)."""
        old = {NOTIFY_OFF: frozenset[Reason](), NOTIFY_LOW: frozenset(Reason)}
        return self._reasons(WARN_NOTIFY, old.get(str(self.prefs.get(NOTIFY)), DEFAULT_REASONS))

    def _reasons(self, key: str, default: frozenset[Reason]) -> frozenset[Reason]:
        saved = self.prefs.get(key)
        if not isinstance(saved, list):
            return default
        return frozenset(reason for reason in Reason if reason.value in saved)

    def set_warnings(self, here: frozenset[Reason], notify: frozenset[Reason]) -> None:
        def kept(chosen: frozenset[Reason]) -> list[str]:
            return [reason.value for reason in Reason if reason in chosen]

        if self._change(WARN_NOTIFY, kept(notify), kept(self.notify_reasons())):
            self.prefs.pop(NOTIFY, None)
        if self._change(WARN_HERE, kept(here), kept(self.warn_reasons())):
            self._count_attention()

    def _apply_auto_refresh(self) -> None:
        if minutes := self.auto_refresh():
            self._auto_timer.start(minutes * 60_000)
        else:
            self._auto_timer.stop()

    def _auto_refresh(self) -> None:
        doc = self._doc
        if self.sample_shown():
            return
        if self._run is None and doc is not None and doc.hosts.hosts:
            before = self._with_reasons(self.notify_reasons())
            self.check_printers(doc.hosts.hosts, quiet=True)
            if self._run is not None:
                self._before_auto = before

    def _notify_new(self, before: dict[str, Reason]) -> None:
        doc, low = self._doc, self.low_level()
        if doc is None:
            return
        now = self._with_reasons(self.notify_reasons())
        lines = []
        for printer in sorted(doc.hosts.hosts, key=lambda p: p.name.casefold()):
            why = now.get(printer.id)
            checked = self._checked.get(printer.id)
            if why is not None and checked is not None and before.get(printer.id) != why:
                reason = why_text(checked, why, low)
                lines.append(_("{name}: {why}").format(name=printer.name, why=reason))
        if lines:
            self.notify_requested.emit(attention_text(len(lines)), notice_text(lines))

    def toner_bars(self) -> bool:
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
        self._save_prefs()
        self._update_state()

    def export_printers(self) -> None:
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
            checked_at=self._checked_at,
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

    def refresh(self) -> None:
        super().refresh()
        self._count_attention()

    def attention_text(self, n: int) -> str:
        return attention_text(n)

    def attention(self) -> dict[str, Reason]:
        return dict(self._attention)

    def _with_reasons(self, wanted: frozenset[Reason]) -> dict[str, Reason]:
        doc, low = self._doc, self.low_level()
        found: dict[str, Reason] = {}
        for printer in doc.hosts.hosts if doc else ():
            checked = self._checked.get(printer.id)
            if (why := status.attention(checked, low, wanted)) is not None:
                found[printer.id] = why
        return found

    def _count_attention(self) -> None:
        found = self._with_reasons(self.warn_reasons())
        changed = found != self._attention
        self._attention = found
        if self._only_attention and not found:
            self._only_attention = False
            self._show_items()
        elif self._only_attention and changed:
            self._show_items()
        self.attention_strip.show_found(list(found.values()), self._only_attention)
        if changed:
            self.badge_changed.emit(len(found))

    def show_attention(self) -> None:
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

    def activate_selected(self) -> None:
        self.open_web_pages()

    def open_web_pages(self) -> None:
        """The selected printers' web pages in the default browser, at most 10 at once. Only
        the address is handed over: nothing is fetched or signed into here."""
        printers = [p for p in self.selected_items() if not is_sample(p.id)]  # never opened
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

    def matches(self, item: Host, needle: str) -> bool:
        if super().matches(item, needle):
            return True
        table = self.table
        texts = table.row_texts(item)
        texts[table.STATUS] = self._cells(item.id)[0].text
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
                self._counted,
                self._set_doc360_account,
                self.bar_marks(),
                web=web_page(printer) is not None,
                hidden=self.hidden_parts(),
            )
            self.details.show_printer(details, 1, needle=self._needle())
        else:
            self.details.show_printer(None, len(items), summary=self._summary())

    def empty_texts(self) -> EmptyTexts:
        return EmptyTexts(
            _("This list has no printers yet.\nAdd one, or import several at once."),
            _("This list has no printers."),
            _("This group has no printers yet."),
            _("Every printer is in a group."),
            _("No printer matches “{text}”."),
        )

    def import_action(self) -> QAction | None:
        return self.commands.import_printers

    def status_extras(self, doc: OpenList) -> list[str]:
        found = [self._checked[p.id] for p in doc.hosts.hosts if p.id in self._checked]
        if not found:
            return []
        online = sum(1 for checked in found if not checked.offline)
        return [ngettext("{n} online", "{n} online", online).format(n=online)]

    def details_parts(self) -> list[Part]:
        return [
            Part("connection", _("Connection"), _("Address, group, MAC")),
            Part("supplies", _("Supplies"), _("Toner, ink and the rest, with their levels")),
            Part("printer", _("Printer"), _("Brand, model, serial number, firmware")),
            Part("pages", _("Page counters"), _("Total pages and their source")),
            Part("tags", _("Tags"), _("The printer's tags")),
            Part("notes", _("Notes"), _("The printer's notes")),
        ]

    def details_always(self) -> str:
        return _("Always shown: the printer's name and its status.")

    def _summary(self) -> str:
        rows = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        shown = sum(1 for row in rows if row is not None and row.data(0, ROLE_ID))
        if not shown:
            return ""
        return ngettext("{n} printer shown", "{n} printers shown", shown).format(n=shown)

    def update_tool_state(self, writable: bool, selected: int) -> None:
        doc = self._doc
        a = self.commands
        a.add_printer.setEnabled(writable)
        a.import_printers.setEnabled(writable)
        a.export_printers.setEnabled(doc is not None and bool(doc.hosts.hosts))
        for action in (a.open_web_page, a.copy_address):
            action.setEnabled(selected > 0)
        idle = self._run is None
        a.refresh_shown.setEnabled(idle and bool(self.visible_items()))
        a.refresh_selected.setEnabled(idle and selected > 0)

    def copy_action(self, key: str) -> QAction | None:
        return self.commands.copy_address if key == "address" else None

    def fill_item_menu(self, menu: QMenu, items: Sequence[Host]) -> None:
        a = self.commands
        menu.addAction(a.open_web_page)
        menu.setDefaultAction(a.open_web_page)
        menu.addSeparator()
        one = len(items) == 1
        a.refresh_selected.setText(
            _("Re&fresh printer") if one else _("Re&fresh {n} printers").format(n=len(items))
        )
        menu.addAction(a.refresh_selected)
        menu.addSeparator()
        self.add_copy_menu(menu)
        menu.addSeparator()
        if one:
            menu.addAction(a.edit)
        self.add_move_menu(menu, items)
        menu.addAction(a.remove)

    def fill_group_menu(self, menu: QMenu, group: Group) -> None:
        assert self._doc is not None
        printers = list(self._doc.hosts.hosts_in(group.id))
        menu.addSeparator()
        refresh = menu.addAction(_("Re&fresh group"))
        refresh.setEnabled(bool(printers) and self._run is None)
        refresh.triggered.connect(lambda: self.check_printers(printers))

    def check_printers(self, printers: Sequence[Host], *, quiet: bool = False) -> None:
        printers = [p for p in printers if not is_sample(p.id)]  # a guide's samples: never read
        if self._run is not None or not printers:
            return
        secret = community() if self.snmp_version() == V2C else v3_account()
        if secret is None:
            if quiet:
                return
            note = _("Set the SNMP v3 account in Settings › Printers › Connecting first.")
            self._shell.show_message(note, 10_000)
            return
        targets = [(p.id, p.address or p.name) for p in printers]
        counts = any(info_of(p).counter_source == DOC360 for p in printers)
        run = PrinterRun(
            targets, secret, counts=counts, account=doc360_account() if counts else None
        )
        run.found.connect(self._found)
        run.counted.connect(self._doc360_counted)
        run.finished.connect(self._run_finished)
        self._run = run
        self._show_progress()
        self._stop_button.setEnabled(True)
        self._update_state()
        self.checks_changed.emit()
        log.info("Refresh: %d printers", len(targets))
        run.start()

    def working(self) -> bool:
        return self._run is not None

    def stop_checks(self) -> None:
        if self._run is not None:
            self._run.stop()
            self._stop_button.setEnabled(False)

    def _found(self, printer_id: str, checked: Checked) -> None:
        run = self._run
        if run is None:
            return
        run.done += 1
        self._checked[printer_id] = checked
        self.table.show_cells(printer_id)
        self._count_attention()
        if self.table.selected_ids() in ([printer_id], []):
            self._selection_changed()
        self._show_progress()
        self.checks_changed.emit()

    def _set_doc360_account(self) -> None:
        if change_doc360_account(self.details):
            self._shell.show_message(
                _("Doc360 MPS account saved. Refresh fetches the page counts."), 10_000
            )

    def _doc360_counted(self, counted: Counted) -> None:
        if self._run is None:
            return
        self._counted = counted
        self._selection_changed()
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

    def _checked_at(self, printer_id: str) -> tuple[datetime | None, ...]:
        checked = self._checked.get(printer_id)
        return (checked.when if checked else None,) * len(PrintersReport.CHECKED)

    def _report_cells(self, printer_id: str) -> tuple[str, ...]:
        state, toner = self._cells(printer_id)
        checked = self._checked.get(printer_id)
        reading = checked.reading if checked else None
        pages = "" if reading is None or reading.pages is None else str(reading.pages)
        printer = self._doc.hosts.host(printer_id) if self._doc else None
        if printer and info_of(printer).counter_source == DOC360:
            total, error = status.doc360_pages(info_of(printer), reading, self._counted)
            pages = _("Error") if error else "" if total is None else str(total)
            if total is not None and (month := status.older_text(self._counted)):
                pages = _("{pages} (from {month})").format(pages=pages, month=month)
        models = status.toner_models(reading) if reading else ""
        mac, firmware = (reading.mac, reading.firmware) if reading else ("", "")
        said = "" if state.nothing else state.text
        return said, toner.text, models, pages, mac, firmware

    def use_value(self, printer_id: str, key: str, value: str) -> None:
        doc = self._writable()
        printer = doc.hosts.host(printer_id) if doc else None
        if doc is None or printer is None or key not in ("brand", "model", "serial"):
            return
        if key in ("brand", "serial"):
            value = value.upper()
        info = replace(info_of(printer), **{key: value})
        try:
            new = doc.hosts.update_host(with_info(printer, info))
        except HostListRuleError as e:
            self._error(str(e))
            return
        self._commit(new)
