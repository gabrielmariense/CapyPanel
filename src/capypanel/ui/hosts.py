"""Dialogs for hosts and groups: add/edit host (with its tag field), and confirming removals."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from capypanel.core.hosts.model import Host, HostList, clean_tags
from capypanel.core.i18n import _


@dataclass(frozen=True)
class HostValues:
    name: str
    address: str
    group: str
    tags: tuple[str, ...]
    notes: str
    profile: str = ""  # "" = the group's


@dataclass(frozen=True)
class ProfilePicker:
    """What the host dialog needs to offer connection profiles."""

    choices: list[tuple[str, str]] = field(default_factory=list)  # (id, name)
    inherited: Callable[[str], str] = lambda group_id: _("From group")  # text for "follow it"
    label: Callable[[str], str] = lambda profile_id: profile_id  # name of any id, even unknown


def list_file_filter() -> str:
    """The file-type filter for choosing host list files in file dialogs."""
    return _("Host lists (*.json);;All files (*)")


def group_path(host_list: HostList, group_id: str) -> str:
    """ "Headquarters › Finance": where a group sits, readable without indentation."""
    names = []
    current = host_list.group(group_id)
    while current is not None:
        names.append(current.name)
        current = host_list.group(current.parent) if current.parent else None
    return " › ".join(reversed(names))


def group_choices(host_list: HostList) -> list[tuple[str, str]]:
    """(id, path) for every group, depth-first, so each group follows the one it's inside."""
    choices: list[tuple[str, str]] = []

    def visit(parent: str | None) -> None:
        for group in sorted(host_list.children(parent), key=lambda g: g.name.casefold()):
            choices.append((group.id, group_path(host_list, group.id)))
            visit(group.id)

    visit(None)
    return choices


class HostDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        host_list: HostList,
        host: Host | None = None,
        default_group: str | None = None,
        profiles: ProfilePicker | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Edit host") if host else _("Add host"))
        self.name = QLineEdit(host.name if host else "")
        self.address = QLineEdit(host.address if host else "")
        self.address.setPlaceholderText(_("Hostname or IP address; leave blank to use the name"))
        self.group = QComboBox()
        for group_id, label in group_choices(host_list):
            self.group.addItem(label, group_id)
        wanted = host.group if host else default_group
        index = self.group.findData(wanted) if wanted else -1
        self.group.setCurrentIndex(max(index, 0))
        self.tags = TagEdit(known=host_list.all_tags())
        self.tags.set_tags(host.tags if host else ())
        self.notes = QPlainTextEdit(host.notes if host else "")
        self.notes.setTabChangesFocus(True)
        self._profiles = profiles or ProfilePicker()
        self.profile = QComboBox()
        self.profile.addItem("", "")  # "follow the group": its text follows the chosen group
        for profile_id, text in self._profiles.choices:
            self.profile.addItem(text, profile_id)
        current = host.profile if host else ""
        if current and self.profile.findData(current) < 0:  # kept, even if this PC lacks it
            self.profile.addItem(self._profiles.label(current), current)
        self.profile.setCurrentIndex(self.profile.findData(current))
        self.group.currentIndexChanged.connect(self._update_inherited)
        self._update_inherited()

        form = QFormLayout()
        form.addRow(_("&Name:"), self.name)
        form.addRow(_("&Address:"), self.address)
        form.addRow(_("&Group:"), self.group)
        tags_label = QLabel(_("&Tags:"))
        tags_label.setBuddy(self.tags.input)  # Alt+T goes to the text box inside the field
        form.addRow(tags_label, self.tags)
        form.addRow(_("Connection &profile:"), self.profile)
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

    def _update_inherited(self) -> None:
        self.profile.setItemText(0, self._profiles.inherited(self.group.currentData() or ""))

    def values(self) -> HostValues:
        return HostValues(
            name=self.name.text().strip(),
            address=self.address.text().strip(),
            group=self.group.currentData(),
            tags=self.tags.tags(),
            notes=self.notes.toPlainText().strip(),
            profile=self.profile.currentData() or "",
        )


def confirm(parent: QWidget, title: str, text: str, action: str) -> bool:
    """A yes/no question whose default is Cancel, so Enter or a stray click never confirms."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, parent=parent)
    yes = box.addButton(action, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is yes


# ---- tag field ----

SEPARATORS = ",;"


class TagEdit(QFrame):
    """Tags as removable chips. Enter or a comma turns the typed text into a chip; Enter on an
    empty box still presses the dialog's OK. Known tags are suggested and keep their spelling."""

    def __init__(self, known: Iterable[str] = ()) -> None:
        super().__init__()
        self.setObjectName("tagEdit")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self._known = {tag.casefold(): tag for tag in known}
        self._chips: list[TagChip] = []
        self.input = QLineEdit()
        self.input.setObjectName("tagInput")
        self.input.setFrame(False)
        self.input.setMinimumWidth(90)
        completer = QCompleter(sorted(self._known.values(), key=str.casefold), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._completed)
        self.input.setCompleter(completer)
        self._flow = FlowLayout(self, spacing=4)
        self._flow.setContentsMargins(4, 3, 4, 3)
        self._flow.addWidget(self.input)
        self.input.textEdited.connect(self._typed)
        self.input.installEventFilter(self)
        sizing = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        sizing.setHeightForWidth(True)
        self.setSizePolicy(sizing)
        self._update_placeholder()

    def tags(self) -> tuple[str, ...]:
        """The chips, plus whatever is still typed in the box (so OK never loses it)."""
        pending = self.input.text().split(",")
        return clean_tags([*(chip.text for chip in self._chips), *pending])

    def set_tags(self, tags: Iterable[str]) -> None:
        for chip in list(self._chips):
            self._remove(chip)
        for tag in tags:
            self._add(tag)

    def add_text(self, text: str) -> None:
        """Turns text into chips; commas or semicolons separate several tags."""
        for sep in SEPARATORS[1:]:
            text = text.replace(sep, SEPARATORS[0])
        for tag in text.split(SEPARATORS[0]):
            self._add(tag)

    def _add(self, tag: str) -> None:
        tag = tag.strip()
        if not tag or any(c.text.casefold() == tag.casefold() for c in self._chips):
            return
        tag = self._known.get(tag.casefold(), tag)  # "Kiosk" becomes the existing "kiosk"
        chip = TagChip(tag)
        chip.remove_button.clicked.connect(lambda: self._remove(chip))
        self._chips.append(chip)
        self._flow.insertWidget(len(self._chips) - 1, chip)  # chips first, the box last
        self._update_placeholder()

    def _remove(self, chip: "TagChip") -> None:
        self._chips.remove(chip)
        self._flow.removeWidget(chip)
        chip.deleteLater()
        self._update_placeholder()
        self.input.setFocus()

    def _typed(self, text: str) -> None:
        if any(sep in text for sep in SEPARATORS):  # typed or pasted a separator
            *done, rest = text.replace(";", ",").split(",")
            self.add_text(",".join(done))
            self.input.setText(rest.lstrip())

    def _completed(self, tag: str) -> None:
        self._add(tag)
        self.input.clear()

    def _update_placeholder(self) -> None:
        self.input.setPlaceholderText("" if self._chips else _("Type a tag and press Enter"))

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self.input:
            return super().eventFilter(watched, event)
        if isinstance(event, QKeyEvent) and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.input.text().strip():
                self.add_text(self.input.text())
                self.input.clear()
                return True  # consumed: an Enter that made a chip doesn't also press OK
            if key == Qt.Key.Key_Backspace and not self.input.text() and self._chips:
                # The last chip goes back to being text, so a typo costs one letter, not the tag.
                last = self._chips[-1]
                self._remove(last)
                self.input.setText(last.text)
                return True
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._show_focus(event.type() == QEvent.Type.FocusIn)
        # Leaving the field keeps what was typed, except when the suggestions pop-up opens.
        if (
            isinstance(event, QFocusEvent)
            and event.type() == QEvent.Type.FocusOut
            and event.reason() != Qt.FocusReason.PopupFocusReason
        ):
            self.add_text(self.input.text())
            self.input.clear()
        return super().eventFilter(watched, event)

    def _show_focus(self, focused: bool) -> None:
        # Stylesheets can't see focus inside a child, so the field carries it as a property.
        self.setProperty("focused", focused)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.input.setFocus()  # a click anywhere in the field types into it
        super().mousePressEvent(event)


class TagChip(QFrame):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
        self.setObjectName("tagChip")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        label = QLabel(text)
        self.remove_button = QToolButton()
        self.remove_button.setObjectName("tagChipRemove")
        self.remove_button.setText("×")
        self.remove_button.setToolTip(_("Remove tag"))
        self.remove_button.setAccessibleName(_("Remove tag {tag}").format(tag=text))
        self.remove_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 1, 2, 1)
        row.setSpacing(2)
        row.addWidget(label)
        row.addWidget(self.remove_button)


class FlowLayout(QLayout):
    """Lays widgets out left to right, wrapping onto new lines like words in a paragraph."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, *, move: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        last = len(self._items) - 1
        for index, item in enumerate(self._items):
            hint = item.sizeHint()
            if x + hint.width() > area.right() + 1 and line_height:
                x, y, line_height = area.x(), y + line_height + self.spacing(), 0
            width = hint.width()
            if index == last:  # the text box takes the rest of its line
                width = max(hint.width(), area.right() + 1 - x)
            if move:
                item.setGeometry(QRect(QPoint(x, y), QSize(width, hint.height())))
            x += width + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
