"""The small windows host commands open: Open a path…, Send a message…, Restart… and Shut down…,
the questions before logging someone off, disconnecting them, restarting the Print Spooler or
running a script that disturbs the PC, a script's output, and the two lists a PC is read for,
Printers on this PC and Installed programs. The same window opens from the menus, the Details
panel and the Commands window."""

import html
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import shiboken6
from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.hosts.bulk import list_separator, write_csv
from capypanel.core.i18n import _, ngettext
from capypanel.core.remote import host_printers, places
from capypanel.core.remote.host_printers import HostPrinter
from capypanel.core.remote.run import RunAs
from capypanel.core.remote.sessions import Session
from capypanel.ui import checks as check_texts
from capypanel.ui.dialogs import run_modal
from capypanel.ui.icons import STATUS_COLORS, tabler_icon
from capypanel.ui.notes import hint
from capypanel.ui.tables import fit_menu

if TYPE_CHECKING:
    from capypanel.ui.hosts_tool.runner import HostTarget, Report, Runner


def escape(text: str) -> str:
    """Text shown as rich text: <, > and & escaped; quotes stay as they are."""
    return html.escape(text, quote=False)


MAX_MESSAGE = 255  # Windows' message box shows about this much
MAX_PATH = 1024
RECENT_PATHS = 10
DELAYS = (0, 60, 5 * 60, 15 * 60)  # Restart's When: now, or in 1, 5 or 15 minutes
DEFAULT_DELAY = 0  # When's first pick: now (Cancel stays the default button)
AMBER = STATUS_COLORS["attention"]
WIDE = 460  # px: a question names a person, a session and a time; narrower, it wraps badly


def where_text(session: Session) -> str:
    """Where someone is signed in, for questions and tooltips: "at the PC, active, since 8:05 AM"
    or "Remote Desktop from LAB-01, disconnected, since 7:40 AM"."""
    kinds = {"console": _("at the PC"), "rdp": _("Remote Desktop")}
    states = {"active": _("active"), "disconnected": _("disconnected"), "idle": _("idle")}
    parts = [kinds.get(session.kind, "")]
    if session.client:
        parts[0] = _("{kind} from {computer}").format(kind=parts[0], computer=session.client)
    parts.append(states.get(session.state, session.state))
    if session.logon_time is not None:
        parts.append(_("since {when}").format(when=check_texts.clock_text(session.logon_time)))
    return ", ".join(p for p in parts if p)


def risky_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName("risky")
    button.setAutoDefault(False)
    return button


class Question(QDialog):
    """A question before something that disturbs whoever uses the PC: the warning sign, the
    question in bold, what happens, then the amber action and Cancel (the default, so Enter or a
    stray click never confirms)."""

    def __init__(self, parent: QWidget | None, title: str, question: str, text: str,
                 action: str) -> None:  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(WIDE)
        sign = QLabel()
        sign.setPixmap(tabler_icon("alert-triangle", QColor(AMBER), 36).pixmap(36, 36))
        self.heading = QLabel(f"<b>{escape(question)}</b>")
        font = self.heading.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.heading.setFont(font)
        self.text = QLabel(text)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.body.addWidget(self.heading)
        self.body.addWidget(self.text)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(sign, 0, Qt.AlignmentFlag.AlignTop)
        top.addLayout(self.body, 1)
        self.action = risky_button(action)
        self.cancel = QPushButton(_("Cancel"))
        self.cancel.setDefault(True)
        self.action.clicked.connect(self.accept)
        self.cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.action)
        buttons.addWidget(self.cancel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.addLayout(top)
        layout.addSpacing(6)
        layout.addLayout(buttons)
        self.cancel.setFocus()


def ask_session_action(parent: QWidget | None, host: str, session: Session, *,
                       log_off: bool) -> bool:  # fmt: skip
    """Log off… or Disconnect… one person: what it means for them, then yes or Cancel."""
    who, where = session.user, where_text(session)
    if log_off:
        question = _("Log off {user} on {host}?").format(user=who, host=host)
        text = _("They're signed in {where}. Work they haven't saved is lost.")
        title, action = _("Log off"), _("&Log off")
    else:
        question = _("Disconnect {user} on {host}?").format(user=who, host=host)
        text = _("They're signed in {where}. Their programs keep running, and they get back to "
                 "them when they sign in again.")  # fmt: skip
        title, action = _("Disconnect"), _("&Disconnect")
    box = Question(parent, title, question, escape(text.format(where=where)), action)
    return run_modal(box) == QDialog.DialogCode.Accepted


def ask_spooler(parent: QWidget | None, host: str) -> bool:
    box = Question(
        parent,
        _("Restart Print Spooler"),
        _("Restart the Print Spooler on {host}?").format(host=host),
        escape(
            _(
                "Every printer on {host} stops for a few seconds. Documents waiting in the "
                "queues stay and print once it's back."
            ).format(host=host)
        ),  # fmt: skip
        _("&Restart Print Spooler"),
    )
    return run_modal(box) == QDialog.DialogCode.Accepted


def ask_script(parent: QWidget | None, command_id: str, host: str) -> bool:
    """The question before a script that disturbs the PC: Repair Windows files… or Clean
    temporary files…"""
    if command_id == "repair":
        title, question = _("Repair Windows files"), _("Repair Windows files on {host}?")
        text = _("DISM and sfc check every Windows file on {host} and repair the damaged ones. It "
                 "takes up to an hour and slows the PC while it runs; whoever uses it can keep "
                 "working. Nothing restarts.")  # fmt: skip
        action = _("&Repair")
    else:
        title, question = _("Clean temporary files"), _("Delete temporary files on {host}?")
        text = _("Files in Windows' Temp folder and in every user's Temp folder that no one has "
                 "touched for a day are deleted from {host}. Files in use stay.")  # fmt: skip
        action = _("&Delete")
    box = Question(
        parent, title, question.format(host=host), escape(text.format(host=host)), action
    )
    return run_modal(box) == QDialog.DialogCode.Accepted


def run_as_text(run_as: RunAs) -> str:
    return {
        RunAs.ACCOUNT: _("CapyPanel's account for the PC"),
        RunAs.SYSTEM: _("SYSTEM"),
        RunAs.USER: _("The person signed in"),
    }[run_as]


def ask_own_script(parent: QWidget | None, name: str, host: str, run_as: RunAs) -> bool:
    """The question before one of your own scripts approved as risky."""
    text = _("It was approved as risky, so it asks every time. It runs as: {who}.").format(
        who=run_as_text(run_as))  # fmt: skip
    box = Question(parent, name, _("Run {name} on {host}?").format(name=name, host=host),
                   escape(text), _("&Run"))  # fmt: skip
    return run_modal(box) == QDialog.DialogCode.Accepted


class OutputDialog(QDialog):
    """What a script wrote on the PC, to read and copy."""

    def __init__(self, parent: QWidget | None, title: str, output: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self.text = output_box(output)
        self.text.setMaximumHeight(16_777_215)  # here it takes the whole window
        copy = QPushButton(_("&Copy"))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(output))
        close = QPushButton(_("Close"))
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        layout.addLayout(buttons)


def output_box(output: str) -> QPlainTextEdit:
    """A script's output as the console showed it: fixed-width, read-only; long lines wrap."""
    box = QPlainTextEdit(output)
    box.setReadOnly(True)
    box.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    box.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    box.setMaximumHeight(OUTPUT_HEIGHT)
    return box


OUTPUT_HEIGHT = 240  # px in the Commands window; Show output… opens it bigger


def ask_clear_queue(parent: QWidget | None, host: str, printer: HostPrinter) -> bool:
    jobs = ngettext(
        "The {n} document waiting is deleted, and nobody gets it printed.",
        "The {n} documents waiting are deleted, and nobody gets them printed.",
        printer.jobs,
    ).format(n=printer.jobs)
    box = Question(
        parent,
        _("Clear queue"),
        _("Clear the queue of {printer} on {host}?").format(printer=printer.name, host=host),
        escape(jobs),
        _("&Clear queue"),
    )
    return run_modal(box) == QDialog.DialogCode.Accepted


# ---- Open a path… ----


class OpenPathDialog(QDialog):
    """A folder on the PC, typed or pasted as File Explorer copies it (quotes and all), or a
    full \\\\PC\\D$\\… path; a line shows what opens. Keeps the last folders opened."""

    def __init__(self, parent: QWidget | None, host: str, recent: Sequence[str]) -> None:
        super().__init__(parent)
        self._host = host
        self.setWindowTitle(_("Open a folder on {host}").format(host=host))
        intro = QLabel(_("Opens a folder on {host} in File Explorer, over file sharing.").format(
            host=host))  # fmt: skip
        self.path = QComboBox()
        self.path.setEditable(True)
        self.path.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.path.addItems(list(recent)[:RECENT_PATHS])
        self.path.setCurrentIndex(-1)
        line = self.path.lineEdit()
        assert line is not None
        line.setMaxLength(MAX_PATH)
        line.setPlaceholderText(_("D:\\Logs"))
        self.path.setMinimumWidth(340)
        form = QFormLayout()
        form.addRow(_("&Folder on {host}:").format(host=host), self.path)
        self.opens = QLabel()
        self.opens.setWordWrap(True)
        self.opens.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        note = hint(_("Paste a path as File Explorer copies it, quotes and all, or a full "
                      "\\\\{host}\\D$\\… path. The list keeps the last {n} folders you "
                      "opened.").format(host=host, n=RECENT_PATHS))  # fmt: skip
        self.open_button = QPushButton(_("&Open"))
        self.open_button.setDefault(True)
        cancel = QPushButton(_("Cancel"))
        self.open_button.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.opens)
        layout.addWidget(note)
        layout.addLayout(buttons)
        self.path.editTextChanged.connect(self._update)
        self._update()
        self.resize(WIDE + 40, self.sizeHint().height())

    def typed(self) -> str:
        return self.path.currentText().strip()

    def _update(self) -> None:
        try:
            shown = places.typed_path(self._host, self.typed())
        except ValueError:
            shown = ""
        self.opens.setText(_("Opens {path}").format(path=shown) if shown else "")
        self.open_button.setEnabled(bool(shown))


# ---- Send a message… ----


class MessageDialog(QDialog):
    """A message for everyone at their screen on the PC: who gets it shows as chips."""

    def __init__(self, parent: QWidget | None, host: str, to: Sequence[Session]) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Send a message to {host}").format(host=host))
        intro = QLabel(
            _("It pops up on their screen on {host} until they click OK.").format(host=host)
            if to
            else _("No one is at their screen on {host} right now.").format(host=host)
        )
        intro.setWordWrap(True)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(QLabel(_("To:")))
        for session in to:
            chip = QLabel(session.user)
            chip.setObjectName("tagValue")
            chip.setToolTip(where_text(session))
            chips.addWidget(chip)
        chips.addStretch(1)
        label = QLabel(_("&Message:"))
        self.message = QPlainTextEdit()
        self.message.setTabChangesFocus(True)
        self.message.setFixedHeight(96)
        label.setBuddy(self.message)
        self.send = QPushButton(_("&Send"))
        self.send.setDefault(True)
        cancel = QPushButton(_("Cancel"))
        self.send.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.send)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        if to:
            layout.addLayout(chips)
        layout.addWidget(label)
        layout.addWidget(self.message)
        layout.addLayout(buttons)
        self.message.textChanged.connect(self._update)
        self._can_send = bool(to)
        self._update()
        self.message.setFocus()
        self.resize(560, self.sizeHint().height())

    def text(self) -> str:
        return self.message.toPlainText().strip()[:MAX_MESSAGE]

    def _update(self) -> None:
        self.send.setEnabled(self._can_send and bool(self.text()))


# ---- Restart… and Shut down… ----


class PowerDialog(Question):
    """Restart… or Shut down…: this window is the question. It names who is signed in; When is
    now, or in 1, 5 or 15 minutes with a message Windows shows them with a countdown."""

    def __init__(self, parent: QWidget | None, host: str, found: Sequence[Session] | None, *,
                 restart: bool) -> None:  # fmt: skip
        self._restart = restart
        self._host = host
        if restart:
            title = _("Restart {host}").format(host=host)
            question = _("Restart {host}?").format(host=host)
        else:
            title = _("Shut down {host}").format(host=host)
            question = _("Shut down {host}?").format(host=host)
        super().__init__(parent, title, question, self._people(found), "")
        self.when = QComboBox()
        for delay in DELAYS:
            self.when.addItem(_delay_text(delay), delay)
        self.when.setCurrentIndex(DELAYS.index(DEFAULT_DELAY))
        self.box = QPlainTextEdit()
        self.box.setTabChangesFocus(True)
        self.box.setFixedHeight(64)
        when_label, message_label = QLabel(_("&When:")), QLabel(_("&Message to them:"))
        when_label.setBuddy(self.when)
        message_label.setBuddy(self.box)
        form = QFormLayout()
        form.addRow(when_label, self.when)
        form.addRow(message_label, self.box)
        self.note = hint()
        self.body.addSpacing(4)
        self.body.addLayout(form)
        self.body.addWidget(self.note)
        self._typed = False  # once they type, the message is theirs: When no longer rewrites it
        self.box.textChanged.connect(self._edited)
        self.when.currentIndexChanged.connect(self._update)
        self._update()
        # The keyboard starts in When: arrows pick, Tab goes to the message (when there is one),
        # then to the action, where Enter runs it. Enter anywhere else is still Cancel.
        self.setTabOrder(self.when, self.box)
        self.setTabOrder(self.box, self.action)
        self.setTabOrder(self.action, self.cancel)
        self.when.setFocus()
        self.resize(520, self.sizeHint().height())

    def delay(self) -> int:
        return int(self.when.currentData())

    def message(self) -> str:
        return self.box.toPlainText().strip()[:MAX_MESSAGE] if self.delay() else ""

    def _people(self, found: Sequence[Session] | None) -> str:
        if found is None:
            return escape(_("CapyPanel couldn't see who is signed in. Work anyone hasn't saved "
                            "is lost."))  # fmt: skip
        people = check_texts.by_state(found)
        if not people:
            return escape(_("No one is signed in."))
        if len(people) == 1:
            text = escape(_("{name} is signed in ({where}). Work they haven't saved is lost."))
            return text.format(name=f"<b>{escape(people[0].user)}</b>",
                               where=escape(where_text(people[0])))  # fmt: skip
        names = "; ".join(f"<b>{escape(s.user)}</b> ({escape(where_text(s))})" for s in people)
        return escape(_("Signed in: {names}. Work they haven't saved is lost.")).format(names=names)

    def _edited(self) -> None:
        self._typed = self.box.hasFocus() or self._typed

    def _update(self) -> None:
        delay = self.delay()
        now = delay == 0
        self.box.setEnabled(not now)
        if now:
            self.box.blockSignals(True)
            self.box.clear()
            self.box.blockSignals(False)
            self.box.setPlaceholderText(
                _("No message: it restarts right away.")
                if self._restart
                else _("No message: it shuts down right away.")  # fmt: skip
            )
            self._typed = False
        elif not self._typed:
            minutes = delay // 60
            text = (ngettext("This PC restarts in {n} minute. Please save your work.",
                             "This PC restarts in {n} minutes. Please save your work.", minutes)
                    if self._restart
                    else ngettext("This PC shuts down in {n} minute. Please save your work.",
                                  "This PC shuts down in {n} minutes. Please save your work.",
                                  minutes))  # fmt: skip
            self.box.blockSignals(True)
            self.box.setPlainText(text.format(n=minutes))
            self.box.blockSignals(False)
        if now:
            note = (
                _("Now restarts {host} at once, with no warning on its screen. Pick a delay to "
                  "send them a message first.") if self._restart
                else _("Now shuts {host} down at once, with no warning on its screen. Pick a "
                       "delay to send them a message first.")
            )  # fmt: skip
            self.note.setText(note.format(host=self._host))
            self.action.setText(_("&Restart now") if self._restart else _("&Shut down now"))
        else:
            self.note.setText(_("Windows shows the message with a countdown. You can cancel "
                                "until then."))  # fmt: skip
            self.action.setText(_("&Restart") if self._restart else _("&Shut down"))


def _delay_text(delay: int) -> str:
    if not delay:
        return _("Now")
    minutes = delay // 60
    return ngettext("In {n} minute", "In {n} minutes", minutes).format(n=minutes)


# ---- the lists a PC is read for ----


class ReadList(QDialog):
    """A window that reads a list from the PC on a background thread: "Reading…" until it's
    back, then the rows, or why it couldn't. Read again reads it once more."""

    def __init__(self, parent: QWidget | None, runner: "Runner", target: "HostTarget") -> None:
        super().__init__(parent)
        self.runner, self.target = runner, target
        self.read_at: datetime | None = None
        self.table = QTreeWidget()
        self.table.setObjectName("grid")
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        fit_menu(self.table)
        self.summary = QLabel()
        self.summary.setObjectName("hint")
        self.summary.setWordWrap(True)
        self.read_button = QPushButton(_("&Read again"))
        self.read_button.setAutoDefault(False)
        self.read_button.clicked.connect(self.read)
        self.close_button = QPushButton(_("Close"))
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)

    def read(self) -> None:
        self.read_button.setEnabled(False)
        self.summary.setText(_("Reading {host}…").format(host=self.target.name))
        self.runner.call(self.work, self._read, self._failed, self.target)

    def work(self, account: Any) -> Any:
        raise NotImplementedError

    def show_rows(self, found: Any) -> None:
        raise NotImplementedError

    def _alive(self) -> bool:
        """Still open: the list can come back after the window was closed and deleted."""
        return shiboken6.isValid(self) and shiboken6.isValid(self.table)

    def _read(self, found: Any) -> None:
        if not self._alive():
            return
        self.read_at = datetime.now(UTC)
        self.read_button.setEnabled(True)
        self.show_rows(found)

    def _failed(self, error: BaseException) -> None:
        from capypanel.ui.hosts_tool.runner import reason_text

        if not self._alive():
            return
        self.read_button.setEnabled(True)
        self.table.clear()
        self.summary.setText(_("Couldn't read {host}: {reason}").format(
            host=self.target.name, reason=reason_text(error)))  # fmt: skip


class PrintersDialog(ReadList):
    """Printers on this PC: name, driver, port, status and documents waiting; Clear queue… for
    the printer picked and Restart Print Spooler… for them all, both asking first."""

    def __init__(self, parent: QWidget | None, runner: "Runner", target: "HostTarget",
                 report: "Report") -> None:  # fmt: skip
        super().__init__(parent, runner, target)
        self._report = report
        self._printers: list[HostPrinter] = []
        self.setWindowTitle(_("Printers on {host}").format(host=target.name))
        self.table.setHeaderLabels([_("Printer"), _("Driver"), _("Port"), _("Status"), _("Jobs")])
        self.clear_button = risky_button(_("Clear &queue…"))
        self.spooler_button = risky_button(_("Restart Print &Spooler…"))
        self.clear_button.clicked.connect(self._clear)
        self.spooler_button.clicked.connect(self._spooler)
        self.table.itemSelectionChanged.connect(self._update)
        actions = QHBoxLayout()
        for button in (self.clear_button, self.spooler_button, self.read_button):
            actions.addWidget(button)
        actions.addStretch(1)
        note = hint(_("Clear queue deletes the documents waiting on the printer picked. Restart "
                      "Print Spooler stops every printer on this PC for a few seconds. Both ask "
                      "first."))  # fmt: skip
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        layout.addWidget(note)
        layout.addLayout(bottom)
        self.resize(860, 440)
        self._update()
        self.read()

    def work(self, account: Any) -> list[HostPrinter]:
        return host_printers.list_printers(self.target.address, account)

    def show_rows(self, found: list[HostPrinter]) -> None:
        self._printers = list(found)
        self.table.clear()
        for printer in self._printers:
            status = printer_status(printer)
            row = QTreeWidgetItem([printer.name, printer.driver, printer.port, status,
                                   str(printer.jobs)])  # fmt: skip
            self.table.addTopLevelItem(row)
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)
        assert self.read_at is not None
        self.summary.setText(
            ngettext(
                "The printer installed on {host}, read at {when}.",
                "The {n} printers installed on {host}, read at {when}.",
                len(found),
            ).format(n=len(found), host=self.target.name, when=check_texts.clock_text(self.read_at))
            if found
            else _("No printers are installed on {host}.").format(host=self.target.name)
        )
        self._update()

    def picked(self) -> HostPrinter | None:
        row = self.table.currentItem()
        index = self.table.indexOfTopLevelItem(row) if row is not None else -1
        return self._printers[index] if 0 <= index < len(self._printers) else None

    def _update(self) -> None:
        picked = self.picked()
        self.clear_button.setEnabled(picked is not None and picked.jobs > 0)
        self.spooler_button.setEnabled(bool(self._printers))

    def _clear(self) -> None:
        printer = self.picked()
        if printer is None or not ask_clear_queue(self, self.target.name, printer):
            return
        from capypanel.ui.hosts_tool.runner import Outcome, bold, failed_text

        def done(_value: object) -> None:
            text = _("Cleared the queue of {printer} on {host}.").format(
                printer=bold(printer.name), host=escape(self.target.name))  # fmt: skip
            self._report("clear-queue", Outcome(text))
            self.read()

        def failed(error: BaseException) -> None:
            action = _("clear the queue of {printer}").format(printer=bold(printer.name))
            self._report("clear-queue", Outcome(failed_text(action, self.target.name, error),
                                                error))  # fmt: skip

        self.runner.call(
            lambda account: host_printers.clear_queue(self.target.address, printer.name, account),
            done,
            failed,
            self.target,
        )

    def _spooler(self) -> None:
        if ask_spooler(self, self.target.name):
            self.runner.restart_spooler(self.target, self._report, then=self.read)


class ProgramsDialog(ReadList):
    """Installed programs: a search, the count and when it was read, then Copy list and Export
    CSV… for the rows shown."""

    def __init__(self, parent: QWidget | None, runner: "Runner", target: "HostTarget",
                 folder: Callable[[str | None], str], found: Sequence[Any] | None = None,
                 read_at: datetime | None = None) -> None:  # fmt: skip
        """`found`: a list already read (the Commands window's), shown without reading again."""
        super().__init__(parent, runner, target)
        self._folder = folder  # the last folder a CSV went to; called with one to keep it
        self._programs: list[Any] = []
        self.setWindowTitle(_("Installed programs on {host}").format(host=target.name))
        self.table.setHeaderLabels([_("Name"), _("Publisher"), _("Version"), _("Installed on")])
        self.table.setSortingEnabled(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search programs"))
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._filter)
        self.copy_button = QPushButton(_("&Copy list"))
        self.export_button = QPushButton(_("&Export CSV…"))
        for button in (self.copy_button, self.export_button):
            button.setAutoDefault(False)
        self.copy_button.clicked.connect(self._copy)
        self.export_button.clicked.connect(self._export)
        top = QHBoxLayout()
        top.addWidget(self.search)
        top.addStretch(1)
        top.addWidget(self.summary)
        self.summary.setWordWrap(False)
        actions = QHBoxLayout()
        for button in (self.copy_button, self.export_button, self.read_button):
            actions.addWidget(button)
        actions.addStretch(1)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        layout.addLayout(bottom)
        self.resize(900, 620)
        self._update()
        if found is None:
            self.read()
        else:
            self._read(list(found))
            self.read_at = read_at or self.read_at
            self._filter()

    def work(self, account: Any) -> list[Any]:
        from capypanel.core.remote import inventory

        return inventory.installed_programs(self.target.address, account)

    def show_rows(self, found: list[Any]) -> None:
        self._programs = list(found)
        self.table.setSortingEnabled(False)
        self.table.clear()
        for program in self._programs:
            installed = check_texts.date_text(program.installed) if program.installed else ""
            row = _ProgramRow([program.name, program.publisher, program.version, installed])
            row.setData(3, SORT_KEY, program.installed.isoformat() if program.installed else "")
            self.table.addTopLevelItem(row)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)
        self._filter()

    def _rows(self) -> list[QTreeWidgetItem]:
        rows = (self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount()))
        return [r for r in rows if r is not None and not r.isHidden()]

    def _filter(self) -> None:
        needle = self.search.text().strip().casefold()
        for index in range(self.table.topLevelItemCount()):
            row = self.table.topLevelItem(index)
            if row is not None:
                texts = (row.text(0), row.text(1))
                row.setHidden(bool(needle) and not any(needle in t.casefold() for t in texts))
        if self.read_at is not None:
            shown, total = len(self._rows()), len(self._programs)
            if shown == total:
                count = ngettext("{n} program", "{n} programs", total).format(n=total)
            else:
                count = _("{shown} of {total} programs").format(shown=shown, total=total)
            self.summary.setText(_("{count} on {host} · read at {when}").format(
                count=count, host=self.target.name,
                when=check_texts.clock_text(self.read_at)))  # fmt: skip
        self._update()

    def _update(self) -> None:
        has_rows = bool(self._rows())
        self.copy_button.setEnabled(has_rows)
        self.export_button.setEnabled(has_rows)

    def _table_rows(self) -> list[list[str]]:
        return [[r.text(c) for c in range(self.table.columnCount())] for r in self._rows()]

    def _header(self) -> list[str]:
        header = self.table.headerItem()
        return [header.text(c) for c in range(self.table.columnCount())]

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(write_csv(self._header(), self._table_rows(), "\t"))

    def _export(self) -> None:
        export_csv(self, self.target.name, self._header(), self._table_rows(), self._folder)


def program_header() -> list[str]:
    return [_("Name"), _("Publisher"), _("Version"), _("Installed on")]


def program_rows(programs: Sequence[Any]) -> list[list[str]]:
    return [
        [p.name, p.publisher, p.version, check_texts.date_text(p.installed) if p.installed else ""]
        for p in programs
    ]


def export_csv(
    parent: QWidget,
    host: str,
    header: Sequence[str],
    rows: Sequence[Sequence[str]],
    folder: Callable[[str | None], str],
) -> None:
    """Export CSV…: the programs, in the CSV Excel opens on this PC; the folder is kept."""
    start = folder(None)
    if not start or not Path(start).is_dir():
        start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    name, _filter = QFileDialog.getSaveFileName(
        parent,
        _("Export CSV"),
        str(Path(start) / f"{_file_safe(host)} - {_('programs')}.csv"),
        _("CSV files (*.csv)"),
    )
    if not name:
        return
    path = Path(name)
    text = write_csv(header, rows, list_separator())
    try:
        path.write_text(text, encoding="utf-8-sig")  # the BOM: Excel reads accents right
    except OSError as e:
        text = _("Couldn't save {path}: {error}").format(path=path, error=e)
        QMessageBox.warning(parent, _("Export CSV"), text)
        return
    folder(str(path.parent))


def printer_dot(printer: HostPrinter) -> str:
    """The Printers tool's status colours: green ready, grey offline, red stopped, amber the
    rest that needs someone."""
    if not printer.problems:
        return "online"
    if "offline" in printer.problems:
        return "offline"
    if "error" in printer.problems or "paused" in printer.problems:
        return "stopped"
    return "attention"


def printer_status(printer: HostPrinter) -> str:
    return ", ".join(problem_text(p) for p in printer.problems) or _("Ready")


SORT_KEY = Qt.ItemDataRole.UserRole + 1


class _ProgramRow(QTreeWidgetItem):
    """Sorted by the date itself in Installed on, and by the text, case aside, elsewhere."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        mine, theirs = self.data(column, SORT_KEY), other.data(column, SORT_KEY)
        if mine is not None and theirs is not None:
            return str(mine) < str(theirs)
        return self.text(column).casefold() < other.text(column).casefold()


def problem_text(problem: str) -> str:
    """What the print spooler reports, as core.remote.host_printers names it, in words."""
    texts = {
        "error": _("Error"), "paper jam": _("Paper jam"), "out of paper": _("Out of paper"),
        "paper problem": _("Paper problem"), "offline": _("Offline"),
        "output bin full": _("Output bin full"), "out of toner": _("Out of toner"),
        "toner low": _("Toner low"), "page punt": _("Page too complex"),
        "user intervention": _("Needs someone at the printer"),
        "out of memory": _("Out of memory"), "door open": _("Door open"), "paused": _("Paused"),
    }  # fmt: skip
    return texts.get(problem, problem)


def _file_safe(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' else c for c in name).strip() or "host"
