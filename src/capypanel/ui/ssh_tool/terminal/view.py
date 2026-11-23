"""Typed keys and screen text never reach a log."""

import functools
import math
import time
import unicodedata
from bisect import bisect_left
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QKeyCombination,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QHelpEvent,
    QImage,
    QInputMethodEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QRawFont,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QToolTip,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.core.ssh.conpty import PseudoConsole
from capypanel.core.ssh.screen import SCROLLBACK, Style, TermScreen, TermStream
from capypanel.ui import help_links
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.menus import popup
from capypanel.ui.shortcuts import Keys, portable
from capypanel.ui.ssh_tool.terminal import glyphs, keys
from capypanel.ui.ssh_tool.terminal.palette import TermPalette, current
from capypanel.ui.ssh_tool.terminal.search import SearchBar
from capypanel.ui.themes import engine as themes

FONT_FAMILIES = ("Cascadia Mono", "Consolas")
EMOJI_FAMILY = "Segoe UI Emoji"
SYMBOL_FAMILY = "Segoe UI Symbol"
VS16 = "\ufe0f"
INVISIBLE = frozenset({VS16, "\ufe0e", "\u200d", "\u200c", "\u200b", "\u2060"})
MIN_PT, MAX_PT, DEFAULT_PT = 8, 20, 10
PAD = 8
DRAIN_BUDGET_S = 0.008
# About 1 ms a chunk (CHUNK_TARGET_S): between chunks, Refresh's threads get Python's lock.
CHUNK = 1024
CHUNK_MIN, CHUNK_MAX = 128, 16384
CHUNK_TARGET_S = 0.001
CHUNK_LOG = 10_000
# A full cache starts over, so a flood of 24-bit colours or characters can't grow it.
MAX_CACHED = 16_384
MAX_PENDING = 131072  # bytes the reader holds before ssh.exe waits: Ctrl+C shows at once
SETTLE_MS = 150  # a drag's last resize this long ago: the scrollback rewraps once, not each step
COPY_PASTE = (int(Qt.Key.Key_C), int(Qt.Key.Key_V))
FIND = int(Qt.Key.Key_F)
STEADY, UNDERLINE, BAR = (2, 4, 6), (3, 4), (5, 6)  # DECSCUSR's cursor styles
NOTCH = 120  # one step of a mouse wheel, in angleDelta()'s units
LINES_A_NOTCH = 3
_Match = tuple[int, int, int, int]  # first row and cell, last row and cell; rows counted stable
_Link = tuple[int, int, int, int, str]  # as a match, then the address
# As key events they keep the selection and scroll: Ctrl goes down before Ctrl+C's C.
HELD_KEYS = frozenset(
    int(k)
    for k in (
        Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_AltGr, Qt.Key.Key_Meta,
        Qt.Key.Key_Super_L, Qt.Key.Key_Super_R, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock,
        Qt.Key.Key_ScrollLock,
    )
)  # fmt: skip
SIZE_KEYS = (int(Qt.Key.Key_Equal), int(Qt.Key.Key_Plus), int(Qt.Key.Key_Minus))
_Fit = tuple[float, float, float, QFont, str]


def chunk_summary(view: "TerminalView") -> dict[str, float]:
    times = sorted(view.chunk_s)
    if not times:
        return {"chunks": 0}
    n = len(times)
    return {
        "chunks": n,
        "median_ms": round(times[n // 2] * 1000, 3),
        "p95_ms": round(times[min(n - 1, int(n * 0.95))] * 1000, 3),
        "max_ms": round(times[-1] * 1000, 3),
        "last_chunk_bytes": view.chunk_bytes,
    }


def pick_family(families: Sequence[str] = FONT_FAMILIES) -> str:
    available = set(QFontDatabase.families())
    for family in families:
        if family in available:
            return family
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


class _Bridge(QObject):
    """Signals carry their start's number: an old connection's queue never ends Reconnect's."""

    ready = Signal(int)
    exited = Signal(int, object)  # object: exit codes like 0xC000013A don't fit a C int


class _Live:
    session: PseudoConsole | None = None


def _close_left(live: _Live) -> None:
    """On the view's `destroyed`, so ssh.exe never outlives its tab: no reference to the view."""
    session, live.session = live.session, None
    if session is not None:
        session.close()


class PasteQuestion(Question):
    def __init__(self, parent: QWidget | None, lines: Sequence[str], host: str) -> None:
        n = len(lines)
        question = ngettext("Paste {n} line into {host}?", "Paste {n} lines into {host}?", n)
        risk = _("It may run as a command.") if n == 1 else _("Each line may run as a command.")
        super().__init__(
            parent,
            _("Paste"),
            question.format(n=n, host=host),
            risk,
            _("&Paste"),
            place="ssh-work-in-the-terminal",
        )
        self.preview = QPlainTextEdit("\n".join(lines[:3]))
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        frame = 2 * (self.preview.frameWidth() + int(self.preview.document().documentMargin()))
        shown = min(n, 3) * self.preview.fontMetrics().lineSpacing()
        scroll_bar = self.preview.horizontalScrollBar().sizeHint().height()
        self.preview.setFixedHeight(shown + frame + scroll_bar)
        self.body.addWidget(self.preview)
        if n > 3:
            more = ngettext("…and {n} more line", "…and {n} more lines", n - 3)
            self.body.addWidget(QLabel(more.format(n=n - 3)))
        self.cancel.setFocus()


def ask_paste(parent: QWidget, lines: Sequence[str], host: str) -> bool:
    return run_modal(PasteQuestion(parent, lines, host)) == QDialog.DialogCode.Accepted


def ask_save_path(parent: QWidget, title: str, suggested: str) -> str:
    name, _filter = QFileDialog.getSaveFileName(parent, title, suggested, _("Text files (*.txt)"))
    return name


def documents(_remember: str | None = None) -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)


def file_name(host: str) -> str:
    safe = "".join("_" if c in '<>:"/\\|?*' else c for c in host).strip() or "ssh"
    return f"{safe} {time.strftime('%Y-%m-%d %H-%M')}.txt"


class TerminalView(QAbstractScrollArea):
    started = Signal()
    ended = Signal(object)  # object: 0xC000013A doesn't fit a C int
    size_picked = Signal(int)
    text_saved = Signal(str)
    rang = Signal()

    def __init__(
        self,
        *,
        host: str,
        palette: TermPalette | None = None,
        point_size: int = DEFAULT_PT,
        scrollback: int = SCROLLBACK,
        families: Sequence[str] = FONT_FAMILIES,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._follows_theme = palette is None
        self._palette = current() if palette is None else palette
        self._scrollback_size = scrollback
        self._family = pick_family(families)
        self._point_size = max(MIN_PT, min(MAX_PT, point_size))
        self._colors: dict[str, QColor] = {}
        self._pairs: dict[Style, tuple[str, str]] = {}
        self.session: PseudoConsole | None = None
        self._argv: list[str] = []
        self._env: Mapping[str, str] | None = None
        self._cwd: str | None = None
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self._bridge.exited.connect(self._on_exit, Qt.ConnectionType.QueuedConnection)
        self._start_number = 0
        self._live = _Live()
        self.destroyed.connect(functools.partial(_close_left, self._live))
        self._exit_code: int | None = None
        self._ended_sent = False
        self._closed_by_us = False
        self._sel: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._selecting = False
        self._sent_down: set[int] = set()
        self._blink_on = True
        self._last_paint = 0.0
        self._paint_cost = 0.0
        # Counts only, never what was typed or shown.
        self.stats = {"drain_max_ms": 0.0, "paint_max_ms": 0.0, "paints": 0, "bytes_fed": 0,
                      "keys_sent": 0, "pastes": 0}  # fmt: skip
        self.chunk_bytes = CHUNK
        self.chunk_s: deque[float] = deque(maxlen=CHUNK_LOG)
        self.confirm_paste: Callable[[QWidget, Sequence[str], str], bool] = ask_paste
        self.open_menu: Callable[[QMenu, QPoint], None] = popup
        self.extend_menu: Callable[[QMenu], None] = lambda _menu: None
        self.ask_save_path: Callable[[QWidget, str, str], str] = ask_save_path
        self.save_folder: Callable[[str | None], str] = documents
        self.search_bar: SearchBar | None = None
        self._matches: list[_Match] = []
        self._current: int | None = None
        self._bells_heard = 0
        self._link: _Link | None = None
        self._pointer: QPoint | None = None
        self._hand = False
        self._reported: set[Qt.MouseButton] = set()
        self._moved_at: tuple[int, int] | None = None
        self._wheel = 0
        self.open_link: Callable[[str], object] = lambda address: QDesktopServices.openUrl(
            QUrl(address)
        )

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Always shown, so the screen never changes width while the scrollback grows.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._scrolled())
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.timeout.connect(self.viewport().update)
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(SETTLE_MS)
        self._settle_timer.timeout.connect(self.settle)
        self._blink = QTimer(self)
        flash = QApplication.cursorFlashTime()
        if flash > 0:
            self._blink.setInterval(flash // 2)
            self._blink.timeout.connect(self._toggle_blink)
            self._blink.start()
        self._set_font()
        self.term = self._new_screen(80, 24)
        if self._follows_theme:
            themes.switches().switched.connect(self._theme_switched)

    def _theme_switched(self) -> None:
        self.set_palette(current())

    def _set_font(self) -> None:
        font = QFont(self._family)
        font.setPointSize(self._point_size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self._fonts: dict[tuple[bool, bool], QFont] = {}
        m = QFontMetricsF(font)
        if m.horizontalAdvance("M") < 2 or m.ascent() + m.descent() < 4:
            # A platform with no fonts at all (Qt's offscreen one): a fixed cell keeps the grid.
            self.cell_w, self.cell_h, self._ascent = 8, 16, 12.0
        else:
            self.cell_w = math.ceil(m.horizontalAdvance("M"))
            self.cell_h = math.ceil(m.ascent() + m.descent())
            self._ascent = m.ascent()
        self._plain: dict[tuple[bool, bool], QFontMetricsF] = {}
        for bold in (False, True):
            for italic in (False, True):
                f = QFont(font)
                f.setBold(bold)
                f.setItalic(italic)
                f.setKerning(False)
                self._plain[(bold, italic)] = QFontMetricsF(f)
                # One cell per glyph, so a run draws in one call; cell by cell was 41 ms a screen.
                advance = QFontMetricsF(f).horizontalAdvance("M")
                if advance >= 2:
                    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.cell_w - advance)
                self._fonts[(bold, italic)] = f
        self._glyph_metrics = glyphs.Metrics(self.cell_w, self.cell_h)
        # QFontMetrics.inFont counts Qt's fallback fonts: it says Cascadia Mono has ⚠, it hasn't.
        self._raw = QRawFont.fromFont(self._fonts[(False, False)])
        self._fit_cache: dict[tuple[str, bool, bool, int], _Fit] = {}

    @property
    def font_family(self) -> str:
        return self._family

    @property
    def point_size(self) -> int:
        return self._point_size

    def set_point_size(self, pt: int) -> None:
        pt = max(MIN_PT, min(MAX_PT, pt))
        if pt != self._point_size:
            self._point_size = pt
            self._set_font()
            self._fit()
            self._place_search_bar()
            self.viewport().update()

    def grid_for(self, width: int, height: int) -> tuple[int, int]:
        return (
            max(2, (width - 2 * PAD) // self.cell_w),
            max(2, (height - 2 * PAD) // self.cell_h),
        )

    def _fit(self) -> None:
        cols, rows = self.grid_for(self.viewport().width(), self.viewport().height())
        if (cols, rows) != (self.term.columns, self.term.lines):
            if cols != self.term.columns:
                self._sel = None
                self._settle_timer.start()
            self.term.resize(rows, cols, defer=True)
            if self.session is not None:
                self.session.resize(cols, rows)
            self._sync_scrollbar(at_bottom=True)

    def settle(self) -> None:
        if not self.term.scrollback_settled:
            self._settle_timer.stop()
            at_bottom = self._at_bottom()
            self.term.rewrap_scrollback()
            self._sel = None
            self._sync_scrollbar(at_bottom=at_bottom)
            self.viewport().update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()
        self._place_search_bar()

    def set_palette(self, palette: TermPalette) -> None:
        self._palette = palette
        self._pairs.clear()
        self.viewport().update()

    @property
    def term_palette(self) -> TermPalette:
        return self._palette

    def _qcolor(self, hex_value: str) -> QColor:
        c = self._colors.get(hex_value)
        if c is None:
            if len(self._colors) >= MAX_CACHED:
                self._colors.clear()
            c = self._colors[hex_value] = QColor(hex_value)
        return c

    def _new_screen(self, cols: int, rows: int) -> TermScreen:
        screen = TermScreen(cols, rows, scrollback=self._scrollback_size, reply=self._reply)
        self._stream = TermStream(screen)
        return screen

    def _reply(self, data: str) -> None:
        if self.session is not None:
            self.session.write(data.encode("utf-8"))

    def start(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        if self.session is not None:
            self.session.close()
        self._argv, self._env, self._cwd = list(argv), env, cwd
        cols, rows = self.grid_for(self.viewport().width(), self.viewport().height())
        self.term = self._new_screen(cols, rows)
        self._exit_code = None
        self._ended_sent = False
        self._closed_by_us = False
        self._sel = None
        self._forget_matches()
        self._bells_heard = 0
        self._link = None
        self._reported.clear()
        self._wheel = 0
        self._start_number += 1
        number, bridge = self._start_number, self._bridge
        self.session = PseudoConsole(
            self._argv,
            cols,
            rows,
            env=env,
            cwd=cwd,
            on_ready=lambda: bridge.ready.emit(number),
            on_exit=lambda code: bridge.exited.emit(number, code),
            max_pending=MAX_PENDING,
        )
        self.term.regional_indicator_cells = self.session.engine.regional_indicator_cells
        self._live.session = self.session
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()
        self.started.emit()

    def restart(self) -> None:
        self.start(self._argv, env=self._env, cwd=self._cwd)

    def close_connection(self) -> None:
        if self.session is not None:
            self._closed_by_us = True
            self.session.close()

    @property
    def closed_by_us(self) -> bool:
        return self._closed_by_us

    @property
    def running(self) -> bool:
        return self.session is not None and self.session.running

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def _on_exit(self, number: int, code: int) -> None:
        if number != self._start_number:
            return
        self._exit_code = code
        session = self.session
        if session is not None:
            QTimer.singleShot(0, session.close)
            QTimer.singleShot(0, self, self._drain)

    def _drain(self, number: int | None = None) -> None:
        if number is not None and number != self._start_number:
            return
        session = self.session
        if session is None:
            return
        start = time.perf_counter()
        before = self.term.lines_scrolled
        at_bottom = self._at_bottom()
        fed = 0
        while time.perf_counter() - start < DRAIN_BUDGET_S:
            chunk = session.take(self.chunk_bytes)
            if not chunk:
                break
            fed += len(chunk)
            t0 = time.perf_counter()
            self._stream.feed(chunk)
            parsed = time.perf_counter() - t0
            self.chunk_s.append(parsed)
            if parsed > CHUNK_TARGET_S * 1.25:
                self.chunk_bytes = max(CHUNK_MIN, int(self.chunk_bytes * 0.75))
            elif parsed < CHUNK_TARGET_S * 0.75:
                self.chunk_bytes = min(CHUNK_MAX, int(self.chunk_bytes * 1.25))
            time.sleep(0)
        took = (time.perf_counter() - start) * 1000
        self.stats["drain_max_ms"] = max(self.stats["drain_max_ms"], took)
        self.stats["bytes_fed"] += fed
        if fed:
            scrolled = self.term.lines_scrolled - before
            self._sync_scrollbar(at_bottom=at_bottom, scrolled=scrolled)
            self._schedule_paint()
            if self.term.bells != self._bells_heard:
                self._bells_heard = self.term.bells
                self.rang.emit()
            if self._link is not None:
                self._hover(self._pointer, QGuiApplication.keyboardModifiers())
        if session.pending:
            QTimer.singleShot(0, self, self._drain)
        elif session.at_eof and self._exit_code is not None and not self._ended_sent:
            self._ended_sent = True
            self.viewport().update()
            self.ended.emit(self._exit_code)

    def _schedule_paint(self) -> None:
        if self._repaint_timer.isActive():
            return
        since = (time.perf_counter() - self._last_paint) * 1000
        wait = max(16.0, 2 * self._paint_cost * 1000) - since
        self._repaint_timer.start(max(0, int(wait)))

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum()

    def _sync_scrollbar(self, *, at_bottom: bool, scrolled: int = 0) -> None:
        bar = self.verticalScrollBar()
        old_value = bar.value()
        sb = 0 if self.term.in_alt else len(self.term.scrollback)
        bar.blockSignals(True)
        bar.setRange(0, sb)
        bar.setPageStep(self.term.lines)
        bar.setSingleStep(1)
        if at_bottom:
            bar.setValue(sb)
        else:
            full = len(self.term.scrollback) == self.term.scrollback.maxlen
            bar.setValue(max(0, old_value - scrolled) if full else old_value)
        bar.blockSignals(False)

    def scroll_to_bottom(self) -> None:
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        mods = event.modifiers()
        reports = self._takes_mouse(mods)
        step = NOTCH if reports else NOTCH // LINES_A_NOTCH
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / step)
        self._wheel -= steps * step
        if not steps:
            return
        if reports:
            code = keys.WHEEL_UP if steps > 0 else keys.WHEEL_DOWN
            for _ in range(abs(steps)):
                self._report(code, event.position().toPoint(), mods)
        elif self.term.in_alt:
            if self.session is not None and self.session.running:
                arrow = Qt.Key.Key_Up if steps > 0 else Qt.Key.Key_Down
                press = QKeyEvent(QEvent.Type.KeyPress, arrow, Qt.KeyboardModifier.NoModifier)
                data = keys.encode_text(press, app_cursor=self.term.app_cursor_keys)
                self.session.write(data * abs(steps))
        else:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - steps)

    def _top_row(self) -> int:
        if self.term.in_alt:
            return len(self.term.scrollback)
        return self.verticalScrollBar().value()

    def _stable(self, row: int) -> int:
        return row + self.term.lines_scrolled - len(self.term.scrollback)

    def _row_of(self, stable: int) -> int:
        return stable - (self.term.lines_scrolled - len(self.term.scrollback))

    def _grid_cell(self, pos: QPoint) -> tuple[int, int]:
        """(column, row) on the screen shown, the nearest one when pos is in the margin."""
        col = max(0, min(self.term.columns - 1, (pos.x() - PAD) // self.cell_w))
        row = max(0, min(self.term.lines - 1, (pos.y() - PAD) // self.cell_h))
        return col, row

    def cell_at(self, pos: QPoint) -> tuple[int, int]:
        col, row = self._grid_cell(pos)
        return self._stable(self._top_row() + row), col

    def has_selection(self) -> bool:
        return self._sel is not None and self._sel[0] != self._sel[1]

    def selected_text(self) -> str:
        if self._sel is None:
            return ""
        (s0, c0), (s1, c1) = sorted(self._sel)
        r0, r1 = max(0, self._row_of(s0)), self._row_of(s1)
        if r1 < 0:
            return ""
        return self.term.text_between((r0, c0), (r1, c1))

    def select_cells(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        self._sel = ((self._stable(start[0]), start[1]), (self._stable(end[0]), end[1]))
        self.viewport().update()

    def select_all(self) -> None:
        self.select_cells((0, 0), (self.term.total_rows - 1, self.term.columns - 1))

    def copy_selection(self) -> str:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def paste_from_clipboard(self) -> bool:
        return self.paste_text(QGuiApplication.clipboard().text())

    def paste_text(self, text: str) -> bool:
        """ESCs go, so no hidden end marker closes the bracket early. Without bracketed paste, a
        line break asks first: each line may run as it lands."""
        if not text or self.session is None or not self.session.running:
            return False
        text = text.replace("\x1b", "").replace("\r\n", "\r").replace("\n", "\r")
        if self.term.bracketed_paste:
            payload = "\x1b[200~" + text + "\x1b[201~"
        else:
            if "\r" in text:
                lines = text.rstrip("\r").split("\r")
                if not self.confirm_paste(self, lines, self.host):
                    return False
            payload = text
        self.stats["pastes"] += 1
        self.session.write(payload.encode("utf-8"))
        self.scroll_to_bottom()
        return True

    def clear_scrollback(self) -> None:
        self.term.clear_scrollback()
        self._sel = None
        self._forget_matches()
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()

    def set_scrollback(self, lines: int) -> None:
        self._scrollback_size = lines
        at_bottom = self._at_bottom()
        dropped = self.term.set_scrollback(lines)
        if dropped:
            self._sel = None
            self._forget_matches()
        self._sync_scrollbar(at_bottom=at_bottom, scrolled=dropped)
        self.viewport().update()

    def save_text(self) -> None:
        self.settle()
        text = self.term.whole_text()
        folder = self.save_folder(None)
        if not folder or not Path(folder).is_dir():
            folder = documents()
        title = _("Save all the text")
        name = self.ask_save_path(self, title, str(Path(folder) / file_name(self.host)))
        if not name:
            return
        path = Path(name)
        try:
            path.write_text(text, encoding="utf-8-sig", newline="")  # BOM: PowerShell 5.1 reads it
        except OSError as e:
            words = _("Couldn't save “{path}”: {error}").format(path=path, error=e.strerror or e)
            help_links.warning(self, title, words, place="ssh-work-in-the-terminal")
            return
        self.save_folder(str(path.parent))
        self.text_saved.emit(str(path))

    def open_search(self) -> None:
        bar = self.search_bar
        if bar is None:
            bar = self.search_bar = SearchBar(self)
            bar.words_changed.connect(self._search_typed)
            bar.older.connect(lambda: self.find_step(older=True))
            bar.newer.connect(lambda: self.find_step(older=False))
            bar.close_asked.connect(self.close_search)
            bar.resized.connect(self._place_search_bar)
        picked = self.selected_text().strip()
        if picked and "\n" not in picked:
            bar.field.setText(picked)
        bar.adjustSize()
        self._place_search_bar()
        bar.show()
        bar.raise_()
        bar.field.setFocus()
        bar.field.selectAll()
        if bar.words and not bar.flush():
            self._search_typed()

    def close_search(self) -> None:
        if self.search_bar is not None:
            self.search_bar.hide()
        self._matches, self._current = [], None
        self.setFocus()
        self.viewport().update()

    def _forget_matches(self) -> None:
        self._matches, self._current = [], None
        if self.search_bar is not None:
            self.search_bar.show_count(None, 0)

    def _place_search_bar(self) -> None:
        bar = self.search_bar
        if bar is not None:
            bar.setFixedHeight(math.ceil(bar.sizeHint().height() / self.cell_h) * self.cell_h)
            area = self.viewport().geometry()
            bar.move(max(area.left(), area.right() + 1 - bar.width() - PAD), area.top() + PAD)

    def _search_typed(self) -> None:
        self._run_search()
        self._current = len(self._matches) - 1 if self._matches else None
        self._show_current()

    def find_step(self, *, older: bool) -> None:
        """From the match shown, found again first: the output may have moved since."""
        bar = self.search_bar
        if bar is None or bar.flush():
            return
        before = self._matches[self._current] if self._current is not None else None
        self._run_search()
        n = len(self._matches)
        if not n:
            self._current = None
        elif before is None:
            self._current = n - 1
        else:
            starts = [(m[0], m[1]) for m in self._matches]
            i = bisect_left(starts, (before[0], before[1]))
            if older:
                self._current = (i - 1) % n
            else:
                same = i < n and starts[i] == (before[0], before[1])
                self._current = (i + 1 if same else i) % n
        self._show_current()

    def _run_search(self) -> None:
        bar = self.search_bar
        if bar is None:
            return
        self.settle()
        found = self.term.find(bar.words, match_case=bar.match_case)
        if self.term.in_alt:
            found = [m for m in found if m[0] >= len(self.term.scrollback)]
        self._matches = [(self._stable(r0), c0, self._stable(r1), c1) for r0, c0, r1, c1 in found]

    def _show_current(self) -> None:
        if self._current is not None:
            s0, c0, s1, c1 = self._matches[self._current]
            self._sel = ((s0, c0), (s1, c1))
            self._reveal(self._row_of(s0))
        if self.search_bar is not None:
            self.search_bar.show_count(self._current, len(self._matches))
        self.viewport().update()

    def _reveal(self, row: int) -> None:
        top = self._top_row()
        if not self.term.in_alt and not top <= row < top + self.term.lines:
            bar = self.verticalScrollBar()
            bar.setValue(max(0, min(bar.maximum(), row - self.term.lines // 2)))

    def _visible_matches(self, top: int) -> dict[int, list[tuple[int, int]]]:
        spans: dict[int, list[tuple[int, int]]] = {}
        bottom = top + self.term.lines - 1
        for s0, c0, s1, c1 in self._matches:
            r0, r1 = self._row_of(s0), self._row_of(s1)
            if r1 < top or r0 > bottom:
                continue
            for r in range(max(r0, top), min(r1, bottom) + 1):
                end = c1 if r == r1 else self.term.columns - 1
                spans.setdefault(r, []).append((c0 if r == r0 else 0, end))
        return spans

    def retranslate(self) -> None:
        if self.search_bar is not None:
            self.search_bar.retranslate()
            self.search_bar.show_count(self._current, len(self._matches))

    def menu(self) -> QMenu:
        menu = QMenu(self)
        copy = menu.addAction(_("&Copy"), self.copy_selection)
        copy.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy.setEnabled(self.has_selection())
        paste = menu.addAction(_("&Paste"), self.paste_from_clipboard)
        paste.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste.setEnabled(self.running)
        menu.addAction(_("Select &all"), self.select_all)
        menu.addSeparator()
        find = menu.addAction(_("&Find…"), self.open_search)
        find.setShortcut(QKeySequence("Ctrl+Shift+F"))
        menu.addAction(_("Save all the &text…"), self.save_text)
        menu.addAction(_("Clear &scrollback"), self.clear_scrollback)
        self.extend_menu(menu)
        for action in menu.actions():
            action.setShortcutVisibleInContextMenu(True)
        return menu

    def _takes_mouse(self, mods: Qt.KeyboardModifier) -> bool:
        return (
            self.term.mouse_tracking != 0
            and self.running
            and not mods & Qt.KeyboardModifier.ShiftModifier
            and (self.term.in_alt or self._at_bottom())
        )

    def _report(
        self, code: int, pos: QPoint, mods: Qt.KeyboardModifier, *, released: bool = False
    ) -> None:
        col, row = self._grid_cell(pos)
        sgr = self.term.mouse_sgr
        data = keys.mouse(code, col + 1, row + 1, mods, released=released, sgr=sgr)
        if data and self.session is not None:
            self.session.write(data)

    def _link_under(self, pos: QPoint) -> _Link | None:
        x, y = pos.x() - PAD, pos.y() - PAD
        width, height = self.term.columns * self.cell_w, self.term.lines * self.cell_h
        if not (0 <= x < width and 0 <= y < height):
            return None
        col, row = self._grid_cell(pos)
        found = self.term.link_at(self._top_row() + row, col)
        if found is None:
            return None
        r0, c0, r1, c1, address = found
        return self._stable(r0), c0, self._stable(r1), c1, address

    def _link_click(self, event: QMouseEvent) -> _Link | None:
        if event.button() != Qt.MouseButton.LeftButton:
            return None
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return None
        return self._link_under(event.position().toPoint())

    def _hover(self, pos: QPoint | None, mods: Qt.KeyboardModifier) -> None:
        link = None if pos is None else self._link_under(pos)
        if link != self._link:
            self._link = link
            self.viewport().update()
        self._show_hand(mods)

    def _show_hand(self, mods: Qt.KeyboardModifier) -> None:
        hand = self._link is not None and bool(mods & Qt.KeyboardModifier.ControlModifier)
        if hand != self._hand:
            self._hand = hand
            shape = Qt.CursorShape.PointingHandCursor if hand else Qt.CursorShape.IBeamCursor
            self.viewport().setCursor(shape)

    def _scrolled(self) -> None:
        if self._pointer is not None:
            self._hover(self._pointer, QGuiApplication.keyboardModifiers())
        self.viewport().update()

    def viewportEvent(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            link = self._link_under(event.pos())
            if link is None:
                QToolTip.hideText()
                event.ignore()
            else:
                # Without a rect, Qt keeps the tip up wherever the mouse goes in the terminal.
                tip = _("Ctrl+click to open the link")
                QToolTip.showText(event.globalPos(), tip, self.viewport(), self._link_rect(link))
            return True
        if event.type() == QEvent.Type.Leave:
            self._pointer = None
            self._hover(None, Qt.KeyboardModifier.NoModifier)
        return super().viewportEvent(event)

    def _link_rect(self, link: _Link) -> QRect:
        top = self._row_of(link[0]) - self._top_row()
        bottom = self._row_of(link[2]) - self._top_row()
        left, right = (link[1], link[3]) if top == bottom else (0, self.term.columns - 1)
        x, y = PAD + left * self.cell_w, PAD + top * self.cell_h
        return QRect(x, y, (right - left + 1) * self.cell_w, (bottom - top + 1) * self.cell_h)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        button = event.button()
        link = self._link_click(event)
        if link is not None:
            self.open_link(link[4])
            return
        if button in keys.BUTTONS and self._takes_mouse(event.modifiers()):
            self._reported.add(button)
            self._moved_at = self._grid_cell(pos)
            self._sel = None
            self.viewport().update()
            self._report(keys.BUTTONS[button], pos, event.modifiers())
            return
        if button == Qt.MouseButton.RightButton:
            self.open_menu(self.menu(), event.globalPosition().toPoint())
            return
        if button == Qt.MouseButton.LeftButton:
            self.settle()
            cell = self.cell_at(pos)
            self._sel = (cell, cell)
            self._selecting = True
            self.viewport().update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._link_click(event) is None:  # Qt's own presses again: a link would open twice
            self.mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        mods = event.modifiers()
        cell = self._grid_cell(pos)
        if self._pointer is None or self._grid_cell(self._pointer) != cell:
            self._hover(pos, mods)
        else:
            self._show_hand(mods)
        self._pointer = pos
        if self._selecting and self._sel is not None:
            self._sel = (self._sel[0], self.cell_at(pos))
            self.viewport().update()
            return
        tracking = self.term.mouse_tracking
        held = next((b for b in keys.BUTTONS if b in self._reported), None)
        if held is None and not (tracking == 1003 and self._takes_mouse(mods)):
            return
        if tracking in (1002, 1003) and self.running and cell != self._moved_at:
            self._moved_at = cell
            button = keys.NO_BUTTON if held is None else keys.BUTTONS[held]
            self._report(button | keys.MOVED, pos, mods)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        button = event.button()
        if button in self._reported:
            self._reported.discard(button)
            # A program that quit on the press has given the mouse back: its shell gets nothing.
            if self.running and self.term.mouse_tracking:
                pos = event.position().toPoint()
                self._report(keys.BUTTONS[button], pos, event.modifiers(), released=True)
            return
        self._selecting = False

    def event(self, e: QEvent) -> bool:
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and not self.leaves(e)
        ):
            # Taken before the app's shortcuts: Ctrl+W goes to the server, Ctrl+Shift+C copies here.
            e.accept()
            return True
        if (
            e.type() == QEvent.Type.KeyPress
            and isinstance(e, QKeyEvent)
            and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab)
            and not e.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.keyPressEvent(e)  # Tab completes in the shell; it never moves the focus
            return True
        return super().event(e)

    def leaves(self, e: QKeyEvent) -> bool:
        combo = e.keyCombination()
        mods = combo.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        key = combo.key()
        if mods & ctrl and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            return True
        if mods == ctrl | shift and key == Qt.Key.Key_W:
            return True
        window_keys = getattr(self.window(), "keys", None)
        if not isinstance(window_keys, Keys) or not window_keys.past_terminal:
            return False
        return portable(QKeySequence(QKeyCombination(mods, key))) in window_keys.past_terminal

    @staticmethod
    def is_ours(e: QKeyEvent) -> bool:
        """Never with Alt: AltGr is Ctrl+Alt, and AltGr with + or = types ~ or § on some layouts."""
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        key = int(e.key())
        if mods == ctrl | shift and key in (*COPY_PASTE, FIND):
            return True
        return mods in (ctrl, ctrl | shift) and key in SIZE_KEYS

    def _copies(self, e: QKeyEvent) -> bool:
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        return mods == ctrl and int(e.key()) == int(Qt.Key.Key_C) and self.has_selection()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control:
            self._show_hand(Qt.KeyboardModifier.ControlModifier)
        if self.leaves(event):
            event.ignore()
            return
        if self.is_ours(event):
            key = int(event.key())
            if key == int(Qt.Key.Key_C):
                self.copy_selection()
            elif key == int(Qt.Key.Key_V):
                self.paste_from_clipboard()
            elif key == FIND:
                self.open_search()
            else:
                step = -1 if key == int(Qt.Key.Key_Minus) else 1
                before = self._point_size
                self.set_point_size(self._point_size + step)
                if self._point_size != before:
                    self.size_picked.emit(self._point_size)
            return
        if self._copies(event):
            self.copy_selection()
            self._sel = None
            self.viewport().update()
            return
        if self.session is None or not self.session.running:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._ended_sent:
                self.restart()
            return
        if self.term.win32_input:
            data = keys.encode(event, True)
        else:  # a console that never asked for key events, as Windows 10's
            data = keys.encode_text(event, app_cursor=self.term.app_cursor_keys)
        if data:
            self.session.write(data)
            self.stats["keys_sent"] += 1
            if self.term.win32_input and not event.isAutoRepeat():
                self._sent_down.add(event.nativeVirtualKey())
            if int(event.key()) in HELD_KEYS:
                return
            self._sel = None
            self._blink_on = True
            if not self._at_bottom():
                self.scroll_to_bottom()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Control:
            self._show_hand(Qt.KeyboardModifier.NoModifier)
        if event.isAutoRepeat() or self.session is None or not self.session.running:
            return
        vk = event.nativeVirtualKey()
        if vk in self._sent_down:
            self._sent_down.discard(vk)
            data = keys.encode(event, False)
            if data:
                self.session.write(data)

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        if event.commitString() and self.session is not None and self.session.running:
            self.session.write(event.commitString().encode("utf-8"))

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.viewport().update()

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        if self.term.cursor_style in STEADY:
            return
        c = self.term.cursor
        x, y = PAD + c.x * self.cell_w, PAD + c.y * self.cell_h
        self.viewport().update(QRect(x, y, self.cell_w * 2, self.cell_h))

    def paintEvent(self, event: QPaintEvent) -> None:
        start = time.perf_counter()
        p = QPainter(self.viewport())
        pal = self._palette
        pairs = self._pairs
        p.fillRect(event.rect(), self._qcolor(pal.background))
        p.translate(PAD, PAD)
        top = self._top_row()
        screen = self.term
        cw, ch = self.cell_w, self.cell_h
        sel = None
        if self._sel is not None and self.has_selection():
            (s0, c0), (s1, c1) = sorted(self._sel)
            sel = (self._row_of(s0), c0, self._row_of(s1), c1)
        first = max(0, (event.rect().top() - PAD) // ch)
        last = min(screen.lines - 1, (event.rect().bottom() - PAD) // ch)
        found = self._visible_matches(top) if self._matches else {}
        link = self._link
        link_rows = (-1, -1) if link is None else (self._row_of(link[0]), self._row_of(link[2]))
        for vy in range(first, last + 1):
            row = top + vy
            if row >= screen.total_rows:
                break
            chars, styles = screen.row(row)
            spans = found.get(row)
            under = (-1, -1)
            if link is not None and link_rows[0] <= row <= link_rows[1]:
                under = (link[1] if row == link_rows[0] else 0,
                         link[3] if row == link_rows[1] else screen.columns - 1)  # fmt: skip
            y = vy * ch
            run_x, run_text, run_key = 0, "", None
            for x in range(screen.columns):
                st = styles[x]
                pair = pairs.get(st)
                if pair is None:
                    if len(pairs) >= MAX_CACHED:
                        pairs.clear()
                    pair = pairs[st] = pal.cell_colors(
                        st.fg, st.bg, bold=st.bold, reverse=st.reverse
                    )
                fg, bg = pair
                if sel and (sel[0], sel[1]) <= (row, x) <= (sel[2], sel[3]):
                    bg = pal.selection
                elif spans and any(a <= x <= b for a, b in spans):
                    bg = pal.match
                if bg != pal.background:
                    p.fillRect(QRect(x * cw, y, cw, ch), self._qcolor(bg))
                text = chars[x]
                key = (fg, st.bold, st.italics)
                if len(text) == 1 and " " <= text <= "~":
                    if key != run_key:
                        self._draw_run(p, run_x, run_text, run_key, y)
                        run_x, run_text, run_key = x, "", key
                    run_text += text
                else:
                    self._draw_run(p, run_x, run_text, run_key, y)
                    run_x, run_text, run_key = x + 1, "", None
                    if text and text != " " and text not in INVISIBLE:
                        nxt = chars[x + 1] if x + 1 < screen.columns else None
                        if nxt == VS16:  # the console gave VS16 a cell: the emoji takes both
                            text, cells = text + VS16, 2
                        else:
                            cells = 2 if nxt == "" else 1
                        self._draw_cell_text(p, text, x, y, st, self._qcolor(fg), cells)
                if text and text != " " and (st.underscore or st.strikethrough):
                    p.setPen(self._qcolor(fg))
                    if st.underscore:
                        p.drawLine(x * cw, y + ch - 1, (x + 1) * cw - 1, y + ch - 1)
                    if st.strikethrough:
                        p.drawLine(x * cw, y + ch // 2, (x + 1) * cw - 1, y + ch // 2)
                if under[0] <= x <= under[1]:
                    p.setPen(self._qcolor(fg))
                    p.drawLine(x * cw, y + ch - 1, (x + 1) * cw - 1, y + ch - 1)
            self._draw_run(p, run_x, run_text, run_key, y)
        self._paint_cursor(p, top)
        p.end()
        self._last_paint = time.perf_counter()
        self._paint_cost = self._last_paint - start
        self.stats["paints"] += 1
        self.stats["paint_max_ms"] = max(self.stats["paint_max_ms"], self._paint_cost * 1000)

    def _draw_run(
        self, p: QPainter, x: int, text: str, key: tuple[str, bool, bool] | None, y: int
    ) -> None:
        if key is not None and text.strip():
            p.setFont(self._fonts[(key[1], key[2])])
            p.setPen(self._qcolor(key[0]))
            p.drawText(QPointF(x * self.cell_w, y + self._ascent), text)

    def _paint_cursor(self, p: QPainter, top: int) -> None:
        screen = self.term
        c = screen.cursor
        if c.hidden or self._ended_sent or top != len(screen.scrollback):
            return
        rect = QRect(c.x * self.cell_w, c.y * self.cell_h, self.cell_w, self.cell_h)
        accent = self._qcolor(self._palette.cursor)
        style = screen.cursor_style
        shows = style in STEADY or self._blink_on or not self.hasFocus()
        if style in UNDERLINE or style in BAR:
            if shows:
                p.fillRect(self._thin_cursor(rect, bar=style in BAR), accent)
            return
        if not self.hasFocus():
            p.setPen(accent)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            return
        if not shows:
            return
        p.fillRect(rect, accent)
        chars, styles = screen.row(len(screen.scrollback) + c.y)
        if 0 <= c.x < len(chars) and chars[c.x] not in ("", " "):
            st = styles[c.x]
            text = chars[c.x]
            back = self._qcolor(self._palette.background)
            if len(text) == 1 and " " <= text <= "~":
                p.setFont(self._fonts[(st.bold, st.italics)])
                p.setPen(back)
                p.drawText(QPointF(rect.x(), rect.y() + self._ascent), text)
            elif text not in INVISIBLE:
                nxt = chars[c.x + 1] if c.x + 1 < len(chars) else None
                text, cells = (text + VS16, 2) if nxt == VS16 else (text, 2 if nxt == "" else 1)
                self._draw_cell_text(p, text, c.x, rect.y(), st, back, cells)

    def _thin_cursor(self, cell: QRect, *, bar: bool) -> QRect:
        if bar:
            return QRect(cell.x(), cell.y(), max(2, self.cell_w // 4), cell.height())
        height = max(2, self.cell_h // 8)
        return QRect(cell.x(), cell.bottom() + 1 - height, cell.width(), height)

    def _draw_cell_text(
        self, p: QPainter, text: str, x: int, y: int, st: Style, color: QColor, cells: int
    ) -> None:
        cw = self.cell_w
        if glyphs.is_builtin(text):
            glyphs.draw(p, text, x * cw, y, self._glyph_metrics, color)
            return
        key = (text, st.bold, st.italics, cells)
        fit = self._fit_cache.get(key)
        if fit is None:
            if unicodedata.combining(text[0]) or unicodedata.category(text[0]) == "Me":
                # A lone mark goes over a no-break space, as Unicode shows one, so it has a width.
                text = " " + text
            if len(self._fit_cache) >= MAX_CACHED:
                self._fit_cache.clear()
            fit = self._fit_cache[key] = (*self._fit_text(text, st, cells), text)
        scale, dx, dy, font, text = fit
        p.setFont(font)
        p.setPen(color)
        if scale == 1.0 and dy == 0.0:
            p.drawText(QPointF(x * cw + dx, y + self._ascent), text)
            return
        p.save()
        p.translate(x * cw + dx, y + self.cell_h / 2 + dy)
        p.scale(scale, scale)
        p.drawText(QPointF(0, self._ascent - self.cell_h / 2), text)
        p.restore()

    def _fit_text(self, text: str, st: Style, cells: int) -> tuple[float, float, float, QFont]:
        font = self._fonts[(st.bold, st.italics)]
        metrics = self._plain[(st.bold, st.italics)]
        symbol = False
        if VS16 in text:
            font = QFont(font)
            font.setFamilies([EMOJI_FAMILY, self._family])
            metrics = QFontMetricsF(font)
        elif cells == 1 and not all(self._raw.supportsCharacter(ord(c)) for c in text):
            # Segoe UI Symbol: Windows' fallback draws ⚠ from Segoe UI Emoji, orange, a third high.
            font = QFont(font)
            font.setFamilies([self._family, SYMBOL_FAMILY])
            metrics = QFontMetricsF(font)
            symbol = True
        target, ch, asc = cells * self.cell_w, self.cell_h, self._ascent
        advance = metrics.horizontalAdvance(text)
        scale = min(1.0, target / advance) if advance > 0 else 1.0
        dx, dy = (target - advance * scale) / 2, 0.0
        ink = metrics.tightBoundingRect(text)
        if not (0 < ink.width() < 10 * target and 0 < ink.height() < 10 * ch):
            # Qt can't measure some strings: an accent over a no-break space is 100000 px wide.
            found = self._ink_by_pixels(text, font)
            if found is None:
                return scale, dx, dy, font
            ink = found

        def lands(s: float, dx: float) -> tuple[float, float, float, float]:
            base = ch / 2 + (asc - ch / 2) * s
            return (
                dx + ink.left() * s,
                dx + ink.right() * s,
                base + ink.top() * s,
                base + ink.bottom() * s,
            )

        x0, x1, y0, y1 = lands(scale, dx)
        if x0 < 0 or x1 > target or y0 < 0 or y1 > ch:
            scale = min(scale, (target - 1) / ink.width(), (ch - 1) / ink.height())
            dx = (target - ink.width() * scale) / 2 - ink.left() * scale
            _, _, y0, y1 = lands(scale, dx)
            if y0 < 0 or y1 > ch:
                dy = (ch - (y1 - y0)) / 2 - y0
        if symbol and scale < 1:
            # Shrunk to its one cell, a symbol sits on the middle: on its baseline ⚠ sat low.
            dy = (ch - (y1 - y0)) / 2 - y0
        return scale, dx, dy, font

    def _ink_by_pixels(self, text: str, font: QFont) -> QRectF | None:
        w, h = self.cell_w * 8, self.cell_h * 3
        ox, oy = self.cell_w * 3, self.cell_h + self._ascent
        img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(ox, oy), text)
        p.end()
        bits, bpl = bytes(img.constBits()), img.bytesPerLine()
        x0 = y0 = 1 << 30
        x1 = y1 = -1
        for y in range(h):
            alpha = bits[y * bpl + 3 : y * bpl + 4 * w : 4]  # BGRA: every fourth byte from the 4th
            hits = [i for i, a in enumerate(alpha) if a > 64]
            if hits:
                x0, x1 = min(x0, hits[0]), max(x1, hits[-1])
                y0, y1 = min(y0, y), max(y1, y)
        if x1 < 0:
            return None
        return QRectF(x0 - ox, y0 - oy, x1 - x0 + 1, y1 - y0 + 1)
