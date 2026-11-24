"""Refresh by itself stays off until picked: fail2ban may ban it."""

import html
import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import N_, _
from capypanel.core.ssh import terminals
from capypanel.core.ssh.terminals import Terminal
from capypanel.ui import help_links
from capypanel.ui.dialogs import ok_cancel, run_modal
from capypanel.ui.settings.group import SettingsGroup
from capypanel.ui.settings.pages import AutoStatusOnlyPage, Page, Section, SettingRow, add_rows

if TYPE_CHECKING:
    from capypanel.ui.ssh_tool.tool import SshTool

MONO = "'Cascadia Mono', Consolas, monospace"
# The terminal's own copies, which Settings can't load before a first connection: tests match them.
MIN_POINTS, MAX_POINTS, DEFAULT_POINTS = 8, 20, 10
MIN_SCROLLBACK, MAX_SCROLLBACK, DEFAULT_SCROLLBACK = 1_000, 50_000, 10_000


def auto_line() -> str:
    return _("Only the SSH port, so nothing logs in. A server running fail2ban in a strict mode "
             "may count each check as a failed login and block this PC.")  # fmt: skip


def terminal_line() -> str:
    return _("Where ssh.exe opens when you use Connect in a separate window. In a terminal "
             "program, that program's own settings decide whether its window stays open "
             "after an error.")  # fmt: skip


def as_typed(text: str) -> str:
    words = html.escape(text, quote=False)
    return re.sub(
        r"\{(?:ssh|name)\}", lambda m: f'<span style="font-family: {MONO}">{m[0]}</span>', words
    )


class TerminalDialog(QDialog):
    def __init__(self, parent: QWidget | None, terminal: Terminal | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Another terminal program"))
        self.about = QLabel(as_typed(
            _("Connect in a separate window starts this program, which runs ssh.exe. In the "
              "arguments, {ssh} stands for ssh.exe with the server's address, port and login, "
              "and {name} for the server's name, for a window or tab title.")
        ))  # fmt: skip
        self.about.setTextFormat(Qt.TextFormat.RichText)
        self.about.setWordWrap(True)
        self.program = QLineEdit(str(terminal.program) if terminal else "")
        self.choose = QPushButton(_("C&hoose…"))
        self.choose.setAutoDefault(False)
        self.choose.clicked.connect(self._choose)
        program_row = QHBoxLayout()
        program_row.addWidget(self.program, 1)
        program_row.addWidget(self.choose)
        self.arguments = QLineEdit(terminal.arguments if terminal else terminals.SSH)
        self.problem = QLabel()
        self.problem.setObjectName("hint")
        self.problem.setTextFormat(Qt.TextFormat.RichText)
        self.problem.setWordWrap(True)
        form = QFormLayout()
        program_label = QLabel(_("&Program:"))
        program_label.setBuddy(self.program)
        form.addRow(program_label, program_row)
        form.addRow(_("&Arguments:"), self.arguments)
        form.addRow("", self.problem)
        self.buttons = ok_cancel(self, _("Save"))
        layout = QVBoxLayout(self)
        layout.addWidget(self.about)
        layout.addLayout(form)
        self.help_button = help_links.HelpButton("ssh-connect-in-a-separate-window")
        layout.addLayout(help_links.row(self.help_button, self.buttons))
        self.program.textChanged.connect(self._update_ok)
        self.arguments.textChanged.connect(self._update_ok)
        self.resize(520, self.sizeHint().height())
        layout.activate()
        self._keep_room_for_problems()
        self._update_ok()
        self.resize(520, self.sizeHint().height())

    def _choose(self) -> None:
        name, _filter = QFileDialog.getOpenFileName(
            self, _("Choose the terminal program"), str(Path.home()), _("Programs (*.exe)")
        )
        if name:
            self.program.setText(str(Path(name)))

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._keep_room_for_problems()

    def _keep_room_for_problems(self) -> None:
        shown, width, tallest = self.problem.text(), self.problem.width(), 0
        for text in terminals.problems():
            self.problem.setText(as_typed(text))
            tallest = max(tallest, self.problem.heightForWidth(width))
        self.problem.setText(shown)
        # Fixed, not a minimum: a form row gave a wrapping label the height it wraps to on its own.
        self.problem.setFixedHeight(tallest)

    def _update_ok(self) -> None:
        why = terminals.problem(self.program.text(), self.arguments.text())
        self.problem.setText(as_typed(why))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not why)
        ok.setToolTip(why)

    def terminal(self) -> Terminal:
        return Terminal(Path(self.program.text().strip()), self.arguments.text().strip())


class TerminalSection(Section):
    changed = Signal()

    def __init__(self, chosen: Terminal | None, ready: list[Terminal]) -> None:
        super().__init__(_("Separate windows"))
        self._chosen = chosen
        self._ready = ready
        self.terminal = QComboBox()
        self._fill()
        self.terminal.activated.connect(self._picked)
        add_rows(self.content, SettingRow(_("Open &in"), terminal_line(), self.terminal))

    def choice(self) -> Terminal | None:
        return self._chosen

    def _fill(self) -> None:
        self._offered: list[Terminal | None] = [None, *self._ready]
        if self._chosen not in self._offered:
            self._offered.append(self._chosen)
        self.terminal.clear()
        self.terminal.addItem(_("A console window"))
        for terminal in self._offered[1:]:
            self.terminal.addItem(terminal.name if terminal else "")
        self.terminal.addItem(_("Another program…"))
        self.terminal.setCurrentIndex(self._offered.index(self._chosen))

    def _picked(self, index: int) -> None:
        if index < len(self._offered):
            self.pick(self._offered[index])
            return
        dialog = TerminalDialog(self, self._chosen)
        if run_modal(dialog) != QDialog.DialogCode.Accepted:
            self._fill()
            return
        typed = dialog.terminal()
        same = (typed.program, typed.arguments)
        self.pick(next((r for r in self._ready if (r.program, r.arguments) == same), typed))

    def pick(self, terminal: Terminal | None) -> None:
        self._chosen = terminal
        self._fill()
        self.changed.emit()


class TextSection(Section):
    changed = Signal()

    def __init__(self, points: int, scrollback: int) -> None:
        super().__init__(_("Terminal"))
        self.points = QSpinBox()
        self.points.setRange(MIN_POINTS, MAX_POINTS)
        self.points.setValue(points)
        self.points.setSuffix(_(" pt"))
        self.scrollback = QSpinBox()
        self.scrollback.setRange(MIN_SCROLLBACK, MAX_SCROLLBACK)
        self.scrollback.setSingleStep(1_000)
        self.scrollback.setGroupSeparatorShown(True)
        self.scrollback.setValue(scrollback)
        self.scrollback.setSuffix(_(" lines"))
        for box in (self.points, self.scrollback):
            box.valueChanged.connect(self.changed)
        add_rows(
            self.content,
            SettingRow(
                _("&Text size"),
                _("In every connection. Ctrl+= and Ctrl+- in a terminal change it too."),
                self.points,
            ),
            SettingRow(
                _("&Scrollback"),
                _("Lines each connection keeps above its screen, to scroll back to, find and "
                  "save. More lines take more memory."),
                self.scrollback,
            ),
        )  # fmt: skip


class SshGeneralPage(AutoStatusOnlyPage):
    def __init__(
        self,
        *,
        auto_status: tuple[bool, int],
        terminal: Terminal | None,
        ready: list[Terminal],
        points: int = DEFAULT_POINTS,
        scrollback: int = DEFAULT_SCROLLBACK,
        place: str,
    ) -> None:
        super().__init__(auto_line=auto_line(), auto_status=auto_status, place=place)
        self.text_section = TextSection(points, scrollback)
        self.text_section.changed.connect(self.changed)
        self.terminal_section = TerminalSection(terminal, ready)
        self.terminal_section.changed.connect(self.changed)
        self.body.insertWidget(self.body.count() - 1, self.text_section)
        self.body.insertWidget(self.body.count() - 1, self.terminal_section)

    def terminal_choice(self) -> Terminal | None:
        return self.terminal_section.choice()

    def points_choice(self) -> int:
        return self.text_section.points.value()

    def scrollback_choice(self) -> int:
        return self.text_section.scrollback.value()


class SshSettings(SettingsGroup):
    LABEL = N_("SSH")
    TITLES = (N_("General"),)

    general: SshGeneralPage

    def __init__(self, tool: "SshTool") -> None:
        self._tool = tool

    def build(self) -> list[tuple[str, Page]]:
        self.general = SshGeneralPage(
            auto_status=self._tool.auto_status(),
            terminal=self._tool.terminal(),
            ready=terminals.ready_here(),
            points=self._tool.terminal_points(),
            scrollback=self._tool.terminal_scrollback(),
            place="settings-ssh-general",
        )
        self.general.changed.connect(self._changed)
        return [("ssh", self.general)]

    def _changed(self) -> None:
        self._tool.set_auto_status(self.general.auto_status_choice())
        self._tool.set_terminal(self.general.terminal_choice())
        self._tool.set_terminal_points(self.general.points_choice())
        self._tool.set_terminal_scrollback(self.general.scrollback_choice())
        self._tool.prefs_applied()
