"""Review…: one of your own scripts, read before it can run. The whole script, read-only; then
the required risk question, with no answer picked; the arguments that follow the host's name;
and who it runs as, with Lock to keep that choice for every run. A file every user may change,
or one too big or unreadable, is shown with why and can't be approved."""

import codecs
import locale

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.core.remote import own_scripts
from capypanel.core.remote.own_scripts import Approval, OwnScript, State
from capypanel.core.remote.run import Language, RunAs
from capypanel.ui.hosts_tool.command_windows import output_box, run_as_text
from capypanel.ui.notes import hint

SIZE = (760, 600)


def script_text(code: bytes) -> str:
    """A script's text as an editor shows it: UTF-8 or UTF-16 by its mark, else UTF-8, else
    this PC's own code page."""
    if code.startswith(codecs.BOM_UTF8):
        text = code[3:].decode("utf-8", "replace")
    elif code.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text = code.decode("utf-16", "replace")
    else:
        try:
            text = code.decode("utf-8")
        except UnicodeDecodeError:
            text = code.decode(locale.getpreferredencoding(False), "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def state_text(script: OwnScript) -> str:
    """Why it can't run as it is, in a few words; "" when it can."""
    return {
        State.READY: "",
        State.NEW: _("new, review before use"),
        State.CHANGED: _("changed, review before use"),
        State.OPEN: _("every user can change it"),
        State.TOO_BIG: _("too big for a script"),
        State.UNREADABLE: _("couldn't be read"),
        State.NO_PATH: _("names no script on the PC"),
    }[script.state]


class ReviewDialog(QDialog):
    def __init__(self, parent: QWidget | None, script: OwnScript) -> None:
        super().__init__(parent)
        self.script = script
        self.setWindowTitle(_("Review {name}").format(name=script.name))
        self.resize(*SIZE)
        if script.file.suffix.casefold() == own_scripts.ON_PC:
            language = _("File on the PC")
        elif script.language is Language.POWERSHELL:
            language = "PowerShell"
        else:
            language = _("Batch file")
        about = QLabel(f"<b>{_escape(script.file.name)}</b> · {language} · "
                       f"{_escape(str(script.file.parent))}")  # fmt: skip
        about.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(about)
        why = {
            State.NEW: _("Read it all before approving: once approved, it can run on any PC."),
            State.CHANGED: _("It changed since it was approved. Read it again before approving."),
            State.OPEN: _("Every user can change this file, so it can't be approved: someone "
                          "could change it between your review and a run. Make the file "
                          "writable by administrators only, then Rescan."),
            State.TOO_BIG: _("It's bigger than {n} KB, too big for a script.").format(
                n=own_scripts.MAX_SIZE // 1024),
            State.UNREADABLE: _("CapyPanel couldn't read the file."),
            State.NO_PATH: _("Its first line should be the script's path on the PC, such as "
                             "C:\\ProgramData\\Scripts\\printers.cmd or "
                             "%ProgramData%\\Scripts\\printers.ps1."),
        }.get(script.state, "")  # fmt: skip
        if script.on_pc and script.state in (State.NEW, State.CHANGED):
            why += " " + _("It runs {path} on each PC, which can't be shown here: every PC has "
                           "its own copy. Run as anyone but the person signed in, it doesn't run "
                           "where every user of the PC can change that file.").format(
                path=script.on_pc)  # fmt: skip
        if why:
            note = QLabel(why)
            note.setWordWrap(True)
            if script.state not in (State.NEW, State.CHANGED):
                note.setObjectName("warningText")
            layout.addWidget(note)
        self.code = output_box(script_text(script.code))
        self.code.setMaximumHeight(16_777_215)
        layout.addWidget(self.code, 1)

        before = script.approval
        self.safe = QRadioButton(_("&No: it runs at once"))
        self.risky = QRadioButton(_("&Yes: it asks before every run"))
        self.risk = QButtonGroup(self)  # neither picked: the answer is always given here
        self.risk.addButton(self.safe)
        self.risk.addButton(self.risky)
        risk = QHBoxLayout()
        risk.addWidget(self.safe)
        risk.addWidget(self.risky)
        risk.addStretch(1)
        self.arguments = QLineEdit(before.arguments if before else "")
        self.arguments.setPlaceholderText(_("None"))
        self.run_as = QComboBox()
        for choice in RunAs:
            self.run_as.addItem(run_as_text(choice), choice)
        self.run_as.setCurrentIndex(max(self.run_as.findData(
            before.run_as if before else RunAs.ACCOUNT), 0))  # fmt: skip
        self.locked = QCheckBox(_("&Lock: always run as this"))
        self.locked.setChecked(before.locked if before else False)
        who = QHBoxLayout()
        who.addWidget(self.run_as, 1)
        who.addWidget(self.locked)
        form = QFormLayout()
        form.addRow(_("Is it risky?"), risk)
        form.addRow(_("&Arguments:"), self.arguments)
        form.addRow("", hint(_("Called as: script <host> <arguments>. Quotes keep spaces "
                               "together.")))  # fmt: skip
        run_as_label = QLabel(_("Run &as:"))
        run_as_label.setBuddy(self.run_as)  # the field is a row of two: no buddy by itself
        form.addRow(run_as_label, who)
        self.problem = QLabel()
        self.problem.setObjectName("warningText")
        self.problem.hide()
        layout.addLayout(form)
        layout.addWidget(self.problem)

        self.approve = QPushButton(_("A&pprove"))
        self.approve.clicked.connect(self.accept)
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.approve)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        can_approve = script.state in (State.NEW, State.CHANGED, State.READY)
        for widget in (self.safe, self.risky, self.arguments, self.run_as, self.locked):
            widget.setEnabled(can_approve)
        self.risk.buttonToggled.connect(lambda *_a: self._update())
        self.arguments.textChanged.connect(self._update)
        self._can_approve = can_approve
        self._update()

    def _update(self) -> None:
        problem = ""
        try:
            own_scripts.split_arguments(self.arguments.text())
        except ValueError:
            problem = _("A quote in the arguments isn't closed.")
        self.problem.setText(problem)
        self.problem.setVisible(bool(problem))
        picked = self.risk.checkedButton() is not None
        self.approve.setEnabled(self._can_approve and picked and not problem)

    def approval(self) -> Approval:
        return Approval(
            self.script.digest,
            risky=self.risky.isChecked(),
            arguments=self.arguments.text().strip(),
            run_as=RunAs(self.run_as.currentData()),
            locked=self.locked.isChecked(),
        )


def _escape(text: str) -> str:
    import html

    return html.escape(text, quote=False)
