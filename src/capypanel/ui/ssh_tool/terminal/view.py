"""A connection's screen: draws what core/ssh/screen.py keeps, sends keys as Windows key events,
and runs ssh.exe on a pseudo console (core/ssh/conpty.py).

Threads: the pseudo console's threads only signal. Output is parsed here, on the window's
thread, in chunks of about 1 ms that give way to any thread waiting between them, so typing and
painting keep their turn during a flood and a Refresh running beside it keeps its pace.

Typed keys and the screen's text never reach a log or a file: this module logs nothing."""

import functools
import math
import time
import unicodedata
from collections import deque
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtCore import (
    QEvent,
    QKeyCombination,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
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
    QFrame,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QWidget,
)

from capypanel.core.i18n import _, ngettext
from capypanel.core.ssh.conpty import PseudoConsole
from capypanel.core.ssh.screen import SCROLLBACK, Style, TermScreen, TermStream
from capypanel.ui.dialogs import run_modal
from capypanel.ui.hosts_tool.command_windows import Question
from capypanel.ui.menus import popup
from capypanel.ui.shortcuts import Keys, portable
from capypanel.ui.ssh_tool.terminal import glyphs, keys
from capypanel.ui.ssh_tool.terminal.palette import TermPalette, current
from capypanel.ui.themes import engine as themes

FONT_FAMILIES = ("Cascadia Mono", "Consolas")
EMOJI_FAMILY = "Segoe UI Emoji"  # an emoji asked for with VS16 (❤️) comes out in colour
SYMBOL_FAMILY = "Segoe UI Symbol"  # one-cell symbols the terminal's font lacks, in text colour
VS16 = "\ufe0f"  # "draw the one before me as an emoji"
# Cells the console gives a code point that draws nothing by itself: the variation selectors,
# the joiners and the zero-width space. Their cell stays blank.
INVISIBLE = frozenset({VS16, "\ufe0e", "\u200d", "\u200c", "\u200b", "\u2060"})
MIN_PT, MAX_PT, DEFAULT_PT = 8, 20, 10
PAD = 8  # px of the terminal's own background around the cells
DRAIN_BUDGET_S = 0.008  # one drain parses this long at most, then the window gets its turn
# Each chunk is sized to parse in about 1 ms, and the drain gives way to any thread waiting for
# Python's lock between chunks: a Refresh is many short round trips, each waiting for that lock,
# and one spinning thread made a refresh of 50 printers 6.6 times as long.
CHUNK = 1024  # the first chunk; each next one is resized towards CHUNK_TARGET_S
CHUNK_MIN, CHUNK_MAX = 128, 16384
CHUNK_TARGET_S = 0.001
CHUNK_LOG = 10_000  # the last chunks' parse times kept: a tab left on tail -f for days
# Colours, colour pairs and character fits kept per tab. Full, a cache starts over, so a flood
# of 24-bit colours or of every character there is can't grow it for as long as the tab is open.
MAX_CACHED = 16_384
MAX_PENDING = 131072  # bytes the reader holds before ssh.exe waits: Ctrl+C shows at once
COPY_PASTE = (int(Qt.Key.Key_C), int(Qt.Key.Key_V))  # with Ctrl+Shift
# Keys that only hold others down or switch a lock. As key events they still reach the program,
# as every key does, but keep the selection and the scroll: Ctrl goes down before the C of
# Ctrl+C. As text they send nothing.
HELD_KEYS = frozenset(
    int(k)
    for k in (
        Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_AltGr, Qt.Key.Key_Meta,
        Qt.Key.Key_Super_L, Qt.Key.Key_Super_R, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock,
        Qt.Key.Key_ScrollLock,
    )
)  # fmt: skip
SIZE_KEYS = (int(Qt.Key.Key_Equal), int(Qt.Key.Key_Plus), int(Qt.Key.Key_Minus))  # with Ctrl
_Fit = tuple[float, float, float, QFont, str]  # scale, dx, dy, the font, the text drawn


def chunk_summary(view: "TerminalView") -> dict[str, float]:
    """The last chunks' parse times, in ms: how many, the median, the 95th percentile and the
    longest. For measuring a flood's cost to a Refresh beside it."""
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
    """Carries the pseudo console's thread calls over to the window's thread, each with the
    number of the start it belongs to, so whatever an earlier connection still had queued is
    dropped: Reconnect while connected never ends the new connection."""

    ready = Signal(int)
    exited = Signal(int, object)  # object: exit codes like 0xC000013A don't fit a C int


class _Live:
    """The connection a view holds, for closing it if the view goes without closing it."""

    session: PseudoConsole | None = None


def _close_left(live: _Live) -> None:
    """Connected to the view's `destroyed`: a deleted tab never leaves ssh.exe running. Holds no
    reference to the view itself."""
    session, live.session = live.session, None
    if session is not None:
        session.close()


class PasteQuestion(Question):
    """Before text with a line break is pasted into a program that didn't ask for bracketed
    paste: each line may run as it lands. The house question, as for closing a connection, with
    the first three lines under its words; Cancel is the default, so Enter pastes nothing."""

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
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # a line as it runs
        frame = 2 * (self.preview.frameWidth() + int(self.preview.document().documentMargin()))
        shown = min(n, 3) * self.preview.fontMetrics().lineSpacing()
        scroll_bar = self.preview.horizontalScrollBar().sizeHint().height()
        self.preview.setFixedHeight(shown + frame + scroll_bar)  # room for a long line's bar
        self.body.addWidget(self.preview)
        if n > 3:
            more = ngettext("…and {n} more line", "…and {n} more lines", n - 3)
            self.body.addWidget(QLabel(more.format(n=n - 3)))
        self.cancel.setFocus()


def ask_paste(parent: QWidget, lines: Sequence[str], host: str) -> bool:
    return run_modal(PasteQuestion(parent, lines, host)) == QDialog.DialogCode.Accepted


class TerminalView(QAbstractScrollArea):
    """One connection's screen. `started` comes each time a connection starts, by any route (the
    tab's start, Reconnect, Enter on an ended tab); `ended(code)` comes once the program has
    ended and its last output is drawn; `size_picked(points)` when Ctrl+= or Ctrl+- changed the
    text size."""

    started = Signal()
    ended = Signal(object)  # the exit code; object, as 0xC000013A doesn't fit a C int
    size_picked = Signal(int)

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
        """`palette` None: the app's theme, now and after every switch. A palette given stays."""
        super().__init__(parent)
        self.host = host
        self._follows_theme = palette is None
        self._palette = current() if palette is None else palette
        self._scrollback_size = scrollback
        self._family = pick_family(families)
        self._point_size = max(MIN_PT, min(MAX_PT, point_size))
        self._colors: dict[str, QColor] = {}
        self._pairs: dict[Style, tuple[str, str]] = {}  # each style's colours in this palette
        self.session: PseudoConsole | None = None
        self._argv: list[str] = []
        self._env: Mapping[str, str] | None = None
        self._cwd: str | None = None
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._drain, Qt.ConnectionType.QueuedConnection)
        self._bridge.exited.connect(self._on_exit, Qt.ConnectionType.QueuedConnection)
        self._start_number = 0  # which start the bridge's signals must carry to count
        self._live = _Live()
        self.destroyed.connect(functools.partial(_close_left, self._live))
        self._exit_code: int | None = None
        self._ended_sent = False
        self._closed_by_us = False
        self._sel: tuple[tuple[int, int], tuple[int, int]] | None = None  # stable rows
        self._selecting = False
        self._sent_down: set[int] = set()
        self._blink_on = True
        self._last_paint = 0.0
        self._paint_cost = 0.0
        # Counts only, never what was typed or shown.
        self.stats = {"drain_max_ms": 0.0, "paint_max_ms": 0.0, "paints": 0, "bytes_fed": 0,
                      "keys_sent": 0, "pastes": 0}  # fmt: skip
        self.chunk_bytes = CHUNK
        self.chunk_s: deque[float] = deque(maxlen=CHUNK_LOG)  # for chunk_summary
        # The paste question and the right-click menu; a test puts its own in their place.
        self.confirm_paste: Callable[[QWidget, Sequence[str], str], bool] = ask_paste
        self.open_menu: Callable[[QMenu, QPoint], None] = popup

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Always shown, so the screen never changes width while the scrollback grows.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self.viewport().update())
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.timeout.connect(self.viewport().update)
        self._blink = QTimer(self)
        flash = QApplication.cursorFlashTime()
        if flash > 0:
            self._blink.setInterval(flash // 2)
            self._blink.timeout.connect(self._toggle_blink)
            self._blink.start()
        self._set_font()
        self.term = self._new_screen(80, 24)
        if self._follows_theme:  # every theme switch reaches the terminal, scrollback and all
            themes.switches().switched.connect(self._theme_switched)

    def _theme_switched(self) -> None:
        self.set_palette(current())

    # ---- fonts and size ----

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
            self.cell_w = math.ceil(m.horizontalAdvance("M"))  # whole pixels: lines join
            self.cell_h = math.ceil(m.ascent() + m.descent())
            self._ascent = m.ascent()
        self._plain: dict[tuple[bool, bool], QFontMetricsF] = {}
        for bold in (False, True):
            for italic in (False, True):
                f = QFont(font)
                f.setBold(bold)
                f.setItalic(italic)
                f.setKerning(False)
                self._plain[(bold, italic)] = QFontMetricsF(f)  # measuring, without spacing
                # Each glyph advances exactly one cell, so a run of ASCII drawn in one call
                # stays on the grid (drawing a full screen cell by cell cost up to 41 ms).
                advance = QFontMetricsF(f).horizontalAdvance("M")
                if advance >= 2:
                    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, self.cell_w - advance)
                self._fonts[(bold, italic)] = f
        self._glyph_metrics = glyphs.Metrics(self.cell_w, self.cell_h)
        # The terminal's own font alone: QFontMetrics.inFont counts Qt's fallback fonts too, and
        # says Cascadia Mono has ⚠, which it hasn't.
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
            self.viewport().update()

    def grid_for(self, width: int, height: int) -> tuple[int, int]:
        return (
            max(2, (width - 2 * PAD) // self.cell_w),
            max(2, (height - 2 * PAD) // self.cell_h),
        )

    def _fit(self) -> None:
        cols, rows = self.grid_for(self.viewport().width(), self.viewport().height())
        if (cols, rows) != (self.term.columns, self.term.lines):
            self.term.resize(rows, cols)
            if self.session is not None:
                self.session.resize(cols, rows)
            self._sync_scrollbar(at_bottom=True)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    # ---- palette ----

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

    # ---- the connection ----

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
        """Runs the program on a new pseudo console; a connection still open is closed first.
        Raises OSError when Windows won't start it."""
        if self.session is not None:
            self.session.close()
        self._argv, self._env, self._cwd = list(argv), env, cwd
        cols, rows = self.grid_for(self.viewport().width(), self.viewport().height())
        self.term = self._new_screen(cols, rows)
        self._exit_code = None
        self._ended_sent = False
        self._closed_by_us = False
        self._sel = None
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
        # Before its output: the engine that runs it counts half a flag as it does.
        self.term.regional_indicator_cells = self.session.engine.regional_indicator_cells
        self._live.session = self.session
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()
        self.started.emit()

    def restart(self) -> None:
        self.start(self._argv, env=self._env, cwd=self._cwd)

    def close_connection(self) -> None:
        """Ends the program if it still runs. The strip that may follow is never the error one."""
        if self.session is not None:
            self._closed_by_us = True
            self.session.close()

    @property
    def closed_by_us(self) -> bool:
        """The connection ended because CapyPanel closed it, not by itself."""
        return self._closed_by_us

    @property
    def running(self) -> bool:
        return self.session is not None and self.session.running

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    def _on_exit(self, number: int, code: int) -> None:
        if number != self._start_number:
            return  # an earlier connection's, closed already
        self._exit_code = code
        # Closing the pseudo console makes it hand over its last frame; the reader drains it,
        # and _drain sends `ended` once everything is drawn. After a close of ours the reader
        # may have reached the end before this exit came (two threads, either order), and it
        # signals no more: the drain after the close sends `ended` then.
        session = self.session
        if session is not None:
            QTimer.singleShot(0, session.close)
            QTimer.singleShot(0, self, self._drain)

    def _drain(self, number: int | None = None) -> None:
        if number is not None and number != self._start_number:
            return  # an earlier connection's output: its screen is gone
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
            time.sleep(0)  # gives way: a thread waiting for Python's lock takes it here
        took = (time.perf_counter() - start) * 1000
        self.stats["drain_max_ms"] = max(self.stats["drain_max_ms"], took)
        self.stats["bytes_fed"] += fed
        if fed:
            scrolled = self.term.lines_scrolled - before
            self._sync_scrollbar(at_bottom=at_bottom, scrolled=scrolled)
            self._schedule_paint()
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

    # ---- scrolling ----

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
            # Scrolled up: the same lines stay in view. Until the scrollback is full, new lines
            # land below them; once it's full, each new line drops one off the top.
            full = len(self.term.scrollback) == self.term.scrollback.maxlen
            bar.setValue(max(0, old_value - scrolled) if full else old_value)
        bar.blockSignals(False)

    def scroll_to_bottom(self) -> None:
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.term.in_alt:
            return
        steps = event.angleDelta().y() / 120
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - round(steps * 3))

    def _top_row(self) -> int:
        if self.term.in_alt:
            return len(self.term.scrollback)
        return self.verticalScrollBar().value()

    # ---- rows: stable numbers survive lines dropping off the top of a full scrollback ----

    def _stable(self, row: int) -> int:
        return row + self.term.lines_scrolled - len(self.term.scrollback)

    def _row_of(self, stable: int) -> int:
        return stable - (self.term.lines_scrolled - len(self.term.scrollback))

    def cell_at(self, pos: QPoint) -> tuple[int, int]:
        col = max(0, min(self.term.columns - 1, (pos.x() - PAD) // self.cell_w))
        row = self._top_row() + max(0, min(self.term.lines - 1, (pos.y() - PAD) // self.cell_h))
        return self._stable(row), col

    # ---- selection, copy and paste ----

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
        """Select from (row, column) to (row, column), rows counted over scrollback + screen."""
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
        """Sends pasted text. Every ESC goes first, so no end marker hidden in the text can close
        the bracket early. Without bracketed paste, a text with a line break asks first, since
        each line may run as it lands."""
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
        self._sync_scrollbar(at_bottom=True)
        self.viewport().update()

    def menu(self) -> QMenu:
        menu = QMenu(self)
        copy = menu.addAction(_("&Copy"), self.copy_selection)
        copy.setShortcut(QKeySequence("Ctrl+Shift+C"))  # shown in the menu: works while it's open
        copy.setEnabled(self.has_selection())
        paste = menu.addAction(_("&Paste"), self.paste_from_clipboard)
        paste.setShortcut(QKeySequence("Ctrl+Shift+V"))
        paste.setEnabled(self.running)
        menu.addAction(_("Select &all"), self.select_all)
        menu.addSeparator()
        menu.addAction(_("Clear &scrollback"), self.clear_scrollback)
        for action in menu.actions():
            action.setShortcutVisibleInContextMenu(True)
        return menu

    # ---- mouse ----

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.open_menu(self.menu(), event.globalPosition().toPoint())
            return
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self.cell_at(event.position().toPoint())
            self._sel = (cell, cell)
            self._selecting = True
            self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._selecting and self._sel is not None:
            self._sel = (self._sel[0], self.cell_at(event.position().toPoint()))
            self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._selecting = False

    # ---- keys ----

    def event(self, e: QEvent) -> bool:
        if (
            e.type() == QEvent.Type.ShortcutOverride
            and isinstance(e, QKeyEvent)
            and not self.leaves(e)
        ):
            # Ours or the program's, even where the app has a shortcut: Ctrl+W goes to the
            # server, and Ctrl+Shift+C copies here, not the list's address.
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
        """The keys the tool and the window take: Ctrl+Tab and Ctrl+Shift+Tab (the tabs),
        Ctrl+Shift+W (close the tab), and the keys that change tools (Home too) and open
        Settings, as Settings › Keyboard shortcuts has them now (Ctrl+0 to Ctrl+4 and Ctrl+,
        unless someone changed them). Every other key goes to the program: Ctrl+W (bash deletes
        a word), Ctrl+Q (micro quits), F5 (mc copies). AltGr is Ctrl+Alt on Windows, so AltGr+2
        (² on ABNT2) still reaches it."""
        combo = e.keyCombination()
        mods = combo.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        key = combo.key()
        if mods & ctrl and key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            return True
        if mods == ctrl | shift and key == Qt.Key.Key_W:
            return True
        window_keys = getattr(self.window(), "keys", None)  # the main window's (ui/shortcuts.py)
        if not isinstance(window_keys, Keys) or not window_keys.past_terminal:
            return False
        return portable(QKeySequence(QKeyCombination(mods, key))) in window_keys.past_terminal

    @staticmethod
    def is_ours(e: QKeyEvent) -> bool:
        """The terminal's own keys: Ctrl+Shift+C and Ctrl+Shift+V copy and paste, Ctrl+= (or
        Ctrl++) and Ctrl+- change the text size. Never with Alt: AltGr is Ctrl+Alt, and AltGr
        with + types ~ on a German keyboard, as AltGr with = types § on ABNT2."""
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier
        key = int(e.key())
        if mods == ctrl | shift and key in COPY_PASTE:
            return True
        return mods in (ctrl, ctrl | shift) and key in SIZE_KEYS

    def _copies(self, e: QKeyEvent) -> bool:
        """Ctrl+C with text selected copies it, as Windows' own console and Windows Terminal do;
        with nothing selected, it goes to the program and stops what runs."""
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ctrl = Qt.KeyboardModifier.ControlModifier
        return mods == ctrl and int(e.key()) == int(Qt.Key.Key_C) and self.has_selection()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.leaves(event):
            event.ignore()
            return
        if self.is_ours(event):
            key = int(event.key())
            if key == int(Qt.Key.Key_C):
                self.copy_selection()
            elif key == int(Qt.Key.Key_V):
                self.paste_from_clipboard()
            else:
                step = -1 if key == int(Qt.Key.Key_Minus) else 1
                before = self._point_size
                self.set_point_size(self._point_size + step)
                if self._point_size != before:
                    self.size_picked.emit(self._point_size)
            return
        if self._copies(event):
            self.copy_selection()
            self._sel = None  # a second Ctrl+C goes to the program
            self.viewport().update()
            return
        if self.session is None or not self.session.running:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._ended_sent:
                self.restart()  # Enter reconnects an ended tab
            return
        if self.term.win32_input:
            data = keys.encode(event, True)
        else:  # a console that never asked for key events, as Windows 10's
            data = keys.encode_text(event, app_cursor=self.term.app_cursor_keys)
        if data:
            self.session.write(data)
            self.stats["keys_sent"] += 1
            if self.term.win32_input and not event.isAutoRepeat():
                self._sent_down.add(event.nativeVirtualKey())  # its release goes too
            if int(event.key()) in HELD_KEYS:
                return
            self._sel = None
            self._blink_on = True
            if not self._at_bottom():
                self.scroll_to_bottom()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
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
        c = self.term.cursor
        x, y = PAD + c.x * self.cell_w, PAD + c.y * self.cell_h
        self.viewport().update(QRect(x, y, self.cell_w * 2, self.cell_h))

    # ---- painting ----

    def paintEvent(self, event: QPaintEvent) -> None:
        start = time.perf_counter()
        p = QPainter(self.viewport())
        pal = self._palette
        pairs = self._pairs
        p.fillRect(event.rect(), self._qcolor(pal.background))  # the padding too
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
        for vy in range(first, last + 1):
            row = top + vy
            if row >= screen.total_rows:
                break
            chars, styles = screen.row(row)
            y = vy * ch
            run_x, run_text, run_key = 0, "", None  # ASCII in one style, drawn in one call
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
                if bg != pal.background:
                    p.fillRect(QRect(x * cw, y, cw, ch), self._qcolor(bg))
                text = chars[x]
                key = (fg, st.bold, st.italics)
                if len(text) == 1 and " " <= text <= "~":
                    if key != run_key:  # ASCII joins the run while the style holds
                        self._draw_run(p, run_x, run_text, run_key, y)
                        run_x, run_text, run_key = x, "", key
                    run_text += text
                else:
                    self._draw_run(p, run_x, run_text, run_key, y)
                    run_x, run_text, run_key = x + 1, "", None
                    if text and text != " " and text not in INVISIBLE:  # its own cells
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
        """A run of ASCII in one colour and font: one call, each glyph one cell wide."""
        if key is not None and text.strip():
            p.setFont(self._fonts[(key[1], key[2])])
            p.setPen(self._qcolor(key[0]))
            p.drawText(QPointF(x * self.cell_w, y + self._ascent), text)

    def _paint_cursor(self, p: QPainter, top: int) -> None:
        screen = self.term
        c = screen.cursor
        if c.hidden or self._ended_sent or top != len(screen.scrollback):
            return  # hidden by the program, ended, or scrolled up into the scrollback
        rect = QRect(c.x * self.cell_w, c.y * self.cell_h, self.cell_w, self.cell_h)
        accent = self._qcolor(self._palette.cursor)
        if not self.hasFocus():
            p.setPen(accent)
            p.drawRect(rect.adjusted(0, 0, -1, -1))  # hollow without the focus
            return
        if not self._blink_on:
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

    def _draw_cell_text(
        self, p: QPainter, text: str, x: int, y: int, st: Style, color: QColor, cells: int
    ) -> None:
        """One cell's character, or a wide one's two cells: line, block and Powerline characters
        drawn by our code; anything else from the font, scaled down if it's wider than its cells
        (a lone ⚠) and centred in them (the fullwidth Ａ), and with VS16 in the colour emoji font
        (❤️). The fit is worked out once per character and style."""
        cw = self.cell_w
        if glyphs.is_builtin(text):
            glyphs.draw(p, text, x * cw, y, self._glyph_metrics, color)
            return
        key = (text, st.bold, st.italics, cells)
        fit = self._fit_cache.get(key)
        if fit is None:
            if unicodedata.combining(text[0]) or unicodedata.category(text[0]) == "Me":
                # An accent in a cell of its own (e + U+0301 through the console): drawn over a
                # no-break space, as Unicode shows a mark alone, so it has a width to centre.
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
        """Scale and offsets that put a character in its cells: centred by its advance, as the
        font means it, and smaller when wider than the cells (a lone ⚠). Where its ink would
        still reach past the cells (a fallback font's arrow, an accent on its own, a tall
        emoji), the ink itself is fitted and centred, so nothing lands on a neighbour's cells."""
        font = self._fonts[(st.bold, st.italics)]
        metrics = self._plain[(st.bold, st.italics)]
        symbol = False
        if VS16 in text:
            font = QFont(font)
            font.setFamilies([EMOJI_FAMILY, self._family])
            metrics = QFontMetricsF(font)
        elif cells == 1 and not all(self._raw.supportsCharacter(ord(c)) for c in text):
            # One cell the terminal's font can't draw, such as ⚠ or ❤ without VS16, which
            # Unicode shows as text: Segoe UI Symbol first, in the text's own colour. Windows'
            # own fallback took Segoe UI Emoji for ⚠: orange, a third of the height.
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
            # Qt can't measure some strings (an accent over a no-break space comes back as
            # 100000 px): measure what drawing it leaves instead.
            found = self._ink_by_pixels(text, font)
            if found is None:
                return scale, dx, dy, font
            ink = found

        def lands(s: float, dx: float) -> tuple[float, float, float, float]:
            base = ch / 2 + (asc - ch / 2) * s  # the baseline, from the cell's top
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
            # Made smaller to fit its one cell, a symbol sits on the cell's middle; on its own
            # baseline it sat low (⚠ was 5 px tall at the foot of a 15 px cell).
            dy = (ch - (y1 - y0)) / 2 - y0
        return scale, dx, dy, font

    def _ink_by_pixels(self, text: str, font: QFont) -> QRectF | None:
        """Where drawing `text` leaves ink, from the pen's place on the baseline: drawn once
        into a small transparent image and read back. Only for what the font's metrics can't
        measure, so it runs once per such character."""
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
