"""The Settings window: a list of pages on the left, Save and Close at the bottom.
Nothing applies until Save, except the language, which switches as soon as it's picked (the
window follows). The main window applies the choices handed over by `saved`. Close, and leaving
the Connections page, ask first when something isn't saved."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from capypanel.core import i18n, settings
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.locations import same_path
from capypanel.core.hosts.model import HostList
from capypanel.core.i18n import _
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.profiles import ProfileError
from capypanel.ui.notes import hint
from capypanel.ui.settings.connections import ConnectionChanges, ConnectionsPage, apply
from capypanel.ui.settings.pages import (
    FilesPage,
    GeneralPage,
    HostListsPage,
    HostsPage,
    Page,
    Section,
)
from capypanel.ui.themes import engine as themes

# The pages' titles, as the pages set them, and the groups' labels: the page list is sized for the
# longest in any language. The app's pages first, then each tool's.
PAGE_TITLES = ("General", "Files", "General", "Host lists", "Connections")
GROUPS = (("CapyPanel", ("general", "files")), ("Hosts", ("hosts", "host_lists", "connections")))
SEARCH_FROM = 3  # letters typed before the search shows its results


@dataclass(frozen=True)
class SettingsChoices:
    start_list: str  # see locations.START_KEY
    host_list: Path
    rewritten: bool  # the chosen list's file was written from Settings, so reopen it
    theme_id: str
    language: str
    hidden_lists: list[Path]  # lists in a lists folder removed from Host lists
    connections: ConnectionChanges
    added_lists: list[Path]  # the lists in Host lists, besides the default and personal
    auto_status: tuple[bool, int] = (False, 5)  # check Status by itself, every N minutes
    start_view: tuple[str, str] | None = None  # the open list's (show, group) first


class SettingsDialog(QDialog):
    saved = Signal(object)  # SettingsChoices, on Save
    language_picked = Signal(str)  # applied at once, not on Save
    theme_picked = Signal(str)  # the same

    def __init__(
        self,
        parent: QWidget | None,
        *,
        paths: settings.Paths,
        start_list: object,
        default_list: Path,
        personal_list: Path,
        document: OpenList | None,
        added: list[Path],
        hidden: list[Path] | None = None,
        registry: themes.Registry,
        found: list[Path] | None = None,
        catalogs: Catalogs,
        auto_status: tuple[bool, int] = (False, 5),
        start_view: tuple[str, str] | None = None,
        host_list: HostList | None = None,
    ) -> None:
        super().__init__(parent)
        self._host_list = host_list
        self._paths = paths
        self._default_list = default_list
        self._personal_list = personal_list
        self._hidden = hidden or []
        self._document = document
        self._found = found or []
        self._registry = registry
        self._catalogs = catalogs
        self._saved_state: tuple[object, ...] | None = None
        # Contents replaced on a language switch stay alive, hidden: deleting a window part
        # holding a list can crash Qt after a theme switch (see DECISIONS, code cleanup).
        self._old: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._build(start_list, added, auto_status, themes.current().id, start_view=start_view)
        self.resize(780, 540)
        self._saved_state = self._state()
        self._update_save()

    def _build(
        self,
        start_list: object,
        added: list[Path],
        auto_status: tuple[bool, int],
        theme_id: str,
        chosen: Path | None = None,
        written: tuple[Path, ...] = (),
        start_view: tuple[str, str] | None = None,
    ) -> None:
        """The pages and buttons, in the current language, showing the values given."""
        self._building = True  # pages report changes while they're filled
        self.setWindowTitle(_("Settings"))
        self.general = GeneralPage(
            language=i18n.language(), registry=self._registry, theme_id=theme_id
        )
        self.files = FilesPage(self._paths)
        self.hosts = HostsPage(
            start_list=start_list,
            default_list=self._default_list,
            personal_list=self._personal_list,
            added=added,
            auto_status=auto_status,
            start_view=start_view,
            host_list=self._host_list,
        )
        self.host_lists = HostListsPage(
            default_list=self._default_list,
            personal_list=self._personal_list,
            document=self._document,
            hidden=self._hidden,
            added=added,
            found=self._found,
        )
        if chosen is not None:
            self.host_lists.view.select(chosen)
        self.host_lists.view.written.extend(written)
        self.connections = ConnectionsPage(self._catalogs, self._document)
        self.pages: dict[str, Page] = {
            "general": self.general,
            "files": self.files,
            "hosts": self.hosts,
            "host_lists": self.host_lists,
            "connections": self.connections,
        }
        self.general.language.currentIndexChanged.connect(self._language_changed)
        self.general.theme.currentIndexChanged.connect(
            lambda: self.theme_picked.emit(self.general.theme_id())
        )

        self.page_list = QListWidget()
        self.page_list.setObjectName("pageList")
        # No setUniformItemSizes: it caches a row height measured before the theme reaches the
        # list, and the rows then overlap (13 px rows for 27 px of text).
        self.stack = QStackedWidget()
        # Each group: its label (not a page), then its pages. _rows maps rows to page ids.
        self._rows: list[str | None] = []
        for group, ids in GROUPS:
            label = QListWidgetItem(_(group))
            label.setFlags(Qt.ItemFlag.NoItemFlags)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            self.page_list.addItem(label)
            self._rows.append(None)
            for page_id in ids:
                self.page_list.addItem("   " + self.pages[page_id].title)
                self._rows.append(page_id)
        for page in self.pages.values():
            self.stack.addWidget(_scrolling(page))  # long pages scroll
            page.changed.connect(self._update_save)
        # Search results: the matching sections of every page, lent here while searching.
        self._results = Page(_("Search"))
        self.stack.addWidget(_scrolling(self._results))
        self._lent: list[tuple[QVBoxLayout, int, QWidget]] = []  # where each came from
        self._result_labels: list[QLabel] = []
        # Wide enough for the longest page name in any language, so the list never cuts it and
        # keeps its width when the language changes.
        metrics = self.page_list.fontMetrics()
        longest = max(
            metrics.horizontalAdvance("   " + title)
            for message in (*PAGE_TITLES, *(group for group, _ids in GROUPS))
            for title in i18n.in_every_language(message)
        )
        self.page_list.setFixedWidth(longest + 64)
        self.page_list.currentRowChanged.connect(self._page_picked)
        self.page_list.setCurrentRow(self.row_of("general"))

        # Save keeps the window open; Close asks first when something isn't saved. Neither is
        # a default button: Enter never saves or closes by surprise.
        self.buttons = QDialogButtonBox()
        role = QDialogButtonBox.ButtonRole
        self.save_button = self.buttons.addButton(_("&Save"), role.ActionRole)
        self.close_button = self.buttons.addButton(_("Close"), role.RejectRole)
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        content = QWidget()
        columns = QHBoxLayout()
        columns.setSpacing(16)
        # A search above the pages: only the pages that mention what's typed stay listed.
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search settings"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(self.page_list.width())
        self.search.textChanged.connect(self._filter_pages)
        side = QVBoxLayout()
        side.addWidget(self.search)
        side.addWidget(self.page_list, 1)
        columns.addLayout(side)
        columns.addWidget(self.stack, 1)
        inside = QVBoxLayout(content)
        inside.setContentsMargins(0, 0, 0, 0)
        inside.addLayout(columns, 1)
        inside.addWidget(self.buttons)
        self._layout.addWidget(content)
        self._content = content
        self._no_default_buttons()
        self._building = False

    def _language_changed(self) -> None:
        code = self.general.language_choice()
        if code != i18n.language():
            self.language_picked.emit(code)  # the app switches now; Settings follows
            QTimer.singleShot(0, self, self._rebuild)  # after the dropdown has closed

    def _rebuild(self) -> None:
        """The same window in the new language, keeping what was picked but not saved."""
        page = self._shown_page()  # not "search": the rebuilt window opens without one
        chosen = self.host_lists.chosen()
        old = self._content
        values = (
            self.hosts.start_choice(),
            self.host_lists.added(),
            self.hosts.auto_status_choice(),
            self.general.theme_id(),
        )
        written = tuple(self.host_lists.written)
        self._hidden = self.host_lists.hidden()
        start_view = self.hosts.show_first_choice()
        old.hide()
        self._layout.removeWidget(old)
        self._old.append(old)
        self._build(*values, chosen=chosen, written=written, start_view=start_view)
        self.show_page(page)
        self._update_save()
        self.general.language.setFocus()

    def _no_default_buttons(self) -> None:
        for button in self.findChildren(QPushButton):  # the pages' buttons too
            button.setAutoDefault(False)
            button.setDefault(False)

    def _page_picked(self, row: int) -> None:
        """Leaving Connections with changes asks first: save them, drop them, or stay."""
        page_id = self._rows[row] if 0 <= row < len(self._rows) else None
        if page_id is None:
            return  # a group's label, never picked
        if self._lent:  # picking a page ends the search: its sections go home first
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self._end_search()
        leaving = self.current_page() == "connections" and page_id != "connections"
        if leaving and self.connections.has_changes():
            answer = self._ask_unsaved(_("The changes on the Connections page aren't saved yet."))
            if answer == "save" and not self._save_connections():
                answer = "stay"
            if answer == "stay":
                self.page_list.blockSignals(True)
                self.page_list.setCurrentRow(self.row_of("connections"))
                self.page_list.blockSignals(False)
                return
            if answer == "discard":
                self.connections.reset()
        self.stack.setCurrentIndex(list(self.pages).index(page_id))
        self._update_save()

    def _ask_unsaved(self, text: str, *, can_save: bool = True) -> str:
        box = QMessageBox(QMessageBox.Icon.Warning, _("Unsaved changes"), text, parent=self)
        save = box.addButton(_("&Save changes"), QMessageBox.ButtonRole.AcceptRole)
        save.setEnabled(can_save)
        discard = box.addButton(_("&Discard changes"), QMessageBox.ButtonRole.DestructiveRole)
        stay = box.addButton(_("&Keep editing"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(stay)
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "stay"

    def _save_connections(self) -> bool:
        try:
            apply(self.connections.catalogs, self.connections.changes())
        except (ProfileError, OSError) as e:
            message = _("Couldn't save the connection profiles: {error}").format(error=e)
            QMessageBox.warning(self, "CapyPanel", message)
            return False
        self.connections.reset()
        return True

    def _filter_pages(self, text: str) -> None:
        """From SEARCH_FROM letters on: every section that mentions `text`, from every page,
        on one results page, each under its page's name, to change right there. The page list
        keeps only the pages with a match. Fewer letters: back to the pages as they were."""
        page = self._shown_page()
        self._end_search()
        wanted = text.strip().casefold()
        if len(wanted) < SEARCH_FROM:
            self.stack.setCurrentIndex(list(self.pages).index(page))
            return
        group_of = {pid: group for group, ids in GROUPS for pid in ids}
        shown: list[str] = []
        layout = self._results.body
        for page_id, source in self.pages.items():
            title_match = wanted in source.title.casefold()
            parts = (source.body.itemAt(i) for i in range(source.body.count()))
            sections = [
                w for part in parts
                if part is not None and isinstance(w := part.widget(), Section)
                and (title_match or wanted in _words(w))
            ]  # fmt: skip
            if not sections:
                continue
            shown.append(page_id)
            where = hint(f"{_(group_of[page_id])} › {source.title}")
            self._result_labels.append(where)
            layout.addWidget(where)
            for section in sections:
                self._lent.append((source.body, source.body.indexOf(section), section))
                source.body.removeWidget(section)
                layout.addWidget(section)
        if not shown:
            nothing = hint(_("No settings mention “{text}”.").format(text=text.strip()))
            self._result_labels.append(nothing)
            layout.addWidget(nothing)
        layout.addStretch(1)
        for row, page_id in enumerate(self._rows):
            if page_id is not None:
                self.page_list.setRowHidden(row, page_id not in shown)
        for row, page_id in enumerate(self._rows):  # a group's label: hidden with its pages
            if page_id is None:
                after = self._rows[row + 1 :]
                end = after.index(None) if None in after else len(after)
                self.page_list.setRowHidden(row, not any(p in shown for p in after[:end]))
        self.page_list.blockSignals(True)
        self.page_list.clearSelection()
        self.page_list.blockSignals(False)
        self._before_search = page
        self.stack.setCurrentIndex(len(self.pages))

    def _end_search(self) -> None:
        """Sends the lent sections back to their pages, where they were, and lists every page."""
        layout = self._results.body
        for home, index, section in reversed(self._lent):
            layout.removeWidget(section)
            home.insertWidget(index, section)
        self._lent.clear()
        for label in self._result_labels:
            label.hide()
            label.deleteLater()  # a plain label: safe to delete, unlike lists and trees
        self._result_labels.clear()
        while layout.count() > 0:  # the stretch under the results
            layout.takeAt(0)
        for row in range(self.page_list.count()):
            self.page_list.setRowHidden(row, False)

    def _shown_page(self) -> str:
        """The page shown, or the one shown before the search."""
        if self.stack.currentIndex() < len(self.pages):
            return list(self.pages)[self.stack.currentIndex()]
        return getattr(self, "_before_search", "general")

    def show_page(self, page_id: str) -> None:
        self.page_list.setCurrentRow(self.row_of(page_id))

    def row_of(self, page_id: str) -> int:
        return self._rows.index(page_id)

    def current_page(self) -> str:
        """The page shown; "search" while the search's results are."""
        index = self.stack.currentIndex()
        return list(self.pages)[index] if index < len(self.pages) else "search"

    def choices(self) -> SettingsChoices:
        host_list = self.host_lists.chosen()
        assert host_list is not None, "Save is disabled until a list is chosen"
        written = self.host_lists.written
        return SettingsChoices(
            start_list=self.hosts.start_choice(),
            host_list=host_list,
            rewritten=any(same_path(host_list, p) for p in written),
            theme_id=self.general.theme_id(),
            language=self.general.language_choice(),
            added_lists=self.host_lists.added(),
            connections=self.connections.changes(),
            auto_status=self.hosts.auto_status_choice(),
            start_view=self.hosts.show_first_choice(),
            hidden_lists=self.host_lists.hidden(),
        )

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)
        self._no_default_buttons()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)  # any click or key in here may change something

    def hideEvent(self, event: QHideEvent) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.MouseButtonRelease, QEvent.Type.KeyRelease) and (
            isinstance(watched, QWidget) and self.isAncestorOf(watched)
        ):
            QTimer.singleShot(0, self, self._update_save)  # once the widget has changed
        return False

    def _state(self) -> tuple[object, ...] | None:
        """What Save would write (language and theme apply at once, so not here), to tell
        whether anything is left unsaved. None while a page can't be saved."""
        if not self.is_valid():
            return None
        c = self.choices()
        return (
            c.start_list, c.host_list, tuple(c.added_lists), tuple(c.hidden_lists), c.auto_status,
            c.start_view, self.connections.has_changes(),
        )  # fmt: skip

    def is_valid(self) -> bool:
        return all(page.is_valid() for page in self.pages.values())

    def unsaved(self) -> bool:
        return self._state() != self._saved_state

    def _update_save(self) -> None:
        """Save is on only while there's something valid to save."""
        if self._building:
            return
        self.save_button.setEnabled(self.is_valid() and self.unsaved())

    def reject(self) -> None:
        """Close, Esc or the window's X: asks first when something isn't saved."""
        if self.unsaved():
            answer = self._ask_unsaved(
                _("Some changes aren't saved yet."), can_save=self.is_valid()
            )
            if answer == "stay":
                return
            if answer == "save":
                self._save()
        super().reject()

    def _save(self) -> None:
        self.saved.emit(self.choices())

    def after_save(self, document: OpenList | None) -> None:
        """The window stays open after Save: its pages now show what's saved."""
        self._document = document
        self.connections.reset()
        self.host_lists.view.saved(document)
        self._saved_state = self._state()
        self._update_save()


def _scrolling(page: Page) -> QScrollArea:
    """A page that scrolls when it's taller than the window, with no frame of its own."""
    area = _PageArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area

class _PageArea(QScrollArea):
    """Never narrower than its page: the window widens instead of cutting off a button row."""

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        page = self.widget()
        if page is None:
            return hint
        bar = self.verticalScrollBar().sizeHint().width()
        return QSize(max(hint.width(), page.minimumSizeHint().width() + bar), hint.height())



def _words(page: QWidget) -> str:
    """Everything a page or section says, lower case, to search: its headings, labels, buttons,
    ticks, dropdown items and table rows."""
    texts = [page.title] if isinstance(page, Page) else []
    texts += [w.text() for w in page.findChildren(QLabel)]
    texts += [w.text() for w in page.findChildren(QAbstractButton)]
    for combo in page.findChildren(QComboBox):
        texts += [combo.itemText(i) for i in range(combo.count())]
    for table in page.findChildren(QTreeWidget):
        header = table.headerItem()
        texts += [header.text(c) for c in range(header.columnCount())]
        for i in range(table.topLevelItemCount()):
            item = table.topLevelItem(i)
            if item is not None:
                texts += [item.text(c) for c in range(item.columnCount())]
    return " ".join(texts).replace("&", "").casefold()
