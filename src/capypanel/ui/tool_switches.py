"""The Tools window: which tools are on. Tools that are off don't load at all, so a change
applies on a restart, which the window's own button confirms."""

from collections.abc import Collection, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capypanel.core.i18n import _
from capypanel.ui.icons import tabler_icon
from capypanel.ui.notes import notes
from capypanel.ui.settings.pages import Section, SettingRow, add_rows
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import ToolInfo

ICON_SIZE = 22


class ToolsDialog(QDialog):
    def __init__(
        self, parent: QWidget | None, *, tools: Sequence[ToolInfo], on: Collection[str]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Tools"))
        self._was_on = {t.tool_id for t in tools if t.tool_id in on}
        self.ticks: dict[str, QCheckBox] = {}
        color = self.palette().color(QPalette.ColorRole.Text)
        section = Section(_("Tools"))
        rows: list[SettingRow] = []
        for tool in tools:
            tick = QCheckBox()
            tick.setChecked(tool.tool_id in self._was_on)
            tick.toggled.connect(lambda _on: self._update())
            self.ticks[tool.tool_id] = tick
            row = SettingRow(_(tool.name), _(tool.blurb), tick)
            badge = QLabel()
            badge.setPixmap(tabler_icon(tool.icon, color, ICON_SIZE).pixmap(ICON_SIZE, ICON_SIZE))
            badge.setFixedWidth(ICON_SIZE + 4)
            line = row.layout()
            assert isinstance(line, QHBoxLayout)
            line.insertWidget(0, badge, 0, Qt.AlignmentFlag.AlignVCenter)  # the icon first
            rows.append(row)
        for tick in self.ticks.values():
            tick.setFixedWidth(ICON_SIZE)  # a tick, not a value: no control-wide column
        add_rows(section.content, *rows)
        self.at_least_one = notes(_("At least one tool stays on."))
        self.buttons = QDialogButtonBox()
        self.restart_button = self.buttons.addButton(
            _("&Restart CapyPanel"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(12)
        column.addWidget(
            notes(
                _("Pick the tools CapyPanel shows. Tools that are off don't load: no rail "
                  "button, no menu entries, no Settings pages. Their lists and settings are "
                  "kept.")
            )
        )  # fmt: skip
        column.addWidget(section)
        column.addWidget(self.at_least_one)
        column.addStretch(1)
        column.addWidget(notes(_("CapyPanel restarts to apply the change. Open lists are saved "
                                 "first.")))  # fmt: skip
        column.addWidget(self.buttons)
        self._update()
        self.resize(560, self.sizeHint().height())

    def on(self) -> list[str]:
        return [tool_id for tool_id, tick in self.ticks.items() if tick.isChecked()]

    def off(self) -> list[str]:
        return [tool_id for tool_id, tick in self.ticks.items() if not tick.isChecked()]

    def _update(self) -> None:
        """The last tool on can't be turned off; Restart waits for a change."""
        on = self.on()
        for tool_id, tick in self.ticks.items():
            tick.setEnabled(not (len(on) == 1 and tool_id in on))
        self.at_least_one.setVisible(len(on) == 1)
        changed = set(on) != self._was_on
        self.restart_button.setEnabled(changed)
        self._set_default(changed)

    def _set_default(self, restart: bool) -> None:
        """Enter restarts only once something changed."""
        for button in self.buttons.buttons():
            if isinstance(button, QPushButton):
                button.setAutoDefault(False)
                button.setDefault(restart and button is self.restart_button)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        themes.paint_title_bar(self)
        self._set_default(self.restart_button.isEnabled())  # the box picks its own as it shows
