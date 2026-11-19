"""The terminal's screen: pyte's parser and cell grid (our copy, capypanel/vendor/pyte), with what
the terminal needs on top. Each fix for what pyte gets wrong says why, so it can go back to
pyte's authors.

- Colours are kept as palette numbers (0 to 255) or "#rrggbb", never turned into fixed values,
  so a theme switch recolours the scrollback too. pyte itself turns 256 colours into hex.
- The alternate screen (1049, 1047, 47) is ours: pyte keeps the mode but doesn't act on it.
  Nothing drawn there reaches the scrollback.
- The scrollback is ours, 10,000 lines, each line packed as its text and style runs: pyte's
  HistoryScreen keeps whole cell objects and wraps every attribute access.
- Titles and icon names are counted and dropped: nothing the server prints renames the tab.
  pyte's parser already drops OSC 52 (the clipboard) and OSC 8 (links). Replies are pyte's
  standard ones only (device attributes, status, cursor position), sent through `reply`.
- Character widths are Windows' console's: every character takes its width and at least one
  cell, so nothing combines (a combining accent, a joiner or a variation selector takes a cell
  of its own), and a wide character that doesn't fit the row wraps whole. The console positions
  everything by its own widths, so the screen must too, or a row ends a cell off.
- Whether the console asked for keys as Windows key events (win32-input-mode, ESC[?9001h) is
  kept apart from pyte's modes, so a reset the server sends (ESC c) can't drop it: Windows 11's
  console asks at its start and still reads key events after. Windows 10's never asks, and its
  keys go as text (ui/ssh_tool/terminal/keys.py).

Never anything typed or printed in a log: this module logs nothing."""

from __future__ import annotations

import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable
from itertools import groupby
from operator import itemgetter
from typing import Any, NamedTuple

from capypanel.vendor import pyte
from capypanel.vendor.pyte import charsets as cs
from capypanel.vendor.pyte import modes as mo
from capypanel.vendor.pyte._widths import wcwidth
from capypanel.vendor.pyte.screens import Margins, StaticDefaultDict

SCROLLBACK = 10_000  # lines
ALT_SCREEN_MODES = (1049, 1047, 47)
BRACKETED_PASTE = 2004 << 5  # pyte keeps private modes shifted left by 5
APP_CURSOR_KEYS = 1 << 5  # DECCKM, which pyte doesn't name
WIN32_INPUT = 9001  # private mode: keys as Windows key events


class Style(NamedTuple):
    fg: int | str = "default"  # a palette number, "#rrggbb" or "default"
    bg: int | str = "default"
    bold: bool = False
    italics: bool = False
    underscore: bool = False
    strikethrough: bool = False
    reverse: bool = False


DEFAULT_STYLE = Style()
_DEFAULT_KEY = tuple(DEFAULT_STYLE)
_styles: dict[tuple[Any, ...], Style] = {_DEFAULT_KEY: DEFAULT_STYLE}
# Styles kept for lines to share. Full, it starts over: a server printing every cell in a 24-bit
# colour of its own once grew it to 1.15 million styles (328 MB) that outlived the tab.
MAX_STYLES = 4096
_KEY = itemgetter(1, 2, 3, 4, 5, 6, 7)  # a pyte Char's fg .. reverse, read in C
_DATA = itemgetter(0)


def _style(key: tuple[Any, ...]) -> Style:
    style = _styles.get(key)
    if style is None:
        if len(_styles) >= MAX_STYLES:  # lines keep the styles they hold
            _styles.clear()
            _styles[_DEFAULT_KEY] = DEFAULT_STYLE
        style = _styles[key] = Style(*key)
    return style


def cells_for(char: str) -> int:
    """The cells Windows' console gives one code point: 2 for a wide one, else 1."""
    return 2 if wcwidth(char) == 2 else 1


class PackedLine(NamedTuple):
    """One scrollback line: its cells' text and style runs [(start, end, style)]. `cells` is a
    str with one character per cell ("" stubs after wide characters become "\\0"), or a tuple
    when a cell holds more than one character."""

    cells: str | tuple[str, ...]
    runs: tuple[tuple[int, int, Style], ...]


def _cells(line: Any, columns: int) -> list[Any]:
    get, default = line.get, line.default
    return [get(x, default) for x in range(columns)]


def pack(line: Any, columns: int) -> PackedLine:
    """Packs a pyte line. map, groupby and itemgetter keep the work per cell in C: building a
    style per cell in Python was half the cost of a flood of output."""
    chars = _cells(line, columns)
    keys = list(map(_KEY, chars))
    datas = list(map(_DATA, chars))
    last = columns
    while last > 0 and keys[last - 1] == _DEFAULT_KEY and datas[last - 1] in (" ", ""):
        last -= 1  # trailing blanks in the default style aren't kept
    runs: list[tuple[int, int, Style]] = []
    x = 0
    for key, group in groupby(keys[:last]):
        n = len(list(group))
        if key != _DEFAULT_KEY:
            runs.append((x, x + n, _style(key)))
        x += n
    datas = datas[:last]
    if "" in datas:
        datas = ["\0" if d == "" else d for d in datas]
    text = "".join(datas)
    cells: str | tuple[str, ...] = text if len(text) == last else tuple(datas)
    return PackedLine(cells, tuple(runs))


def unpack(packed: PackedLine, columns: int) -> tuple[list[str], list[Style]]:
    chars = [" "] * columns
    styles = [DEFAULT_STYLE] * columns
    for x, ch in enumerate(packed.cells[:columns]):
        chars[x] = "" if ch == "\0" else ch
    for start, end, style in packed.runs:
        for x in range(start, min(end, columns)):
            styles[x] = style
    return chars, styles


def _unpair_before(line: Any, x: int) -> None:
    """A character about to go in cell x, the second half of a wide one: the first half becomes
    a space, as Windows' console does. pyte leaves it."""
    if x and line[x].data == "":
        line[x - 1] = line[x - 1]._replace(data=" ")


def _unpair_after(line: Any, x: int, columns: int) -> None:
    """Cell x, right after what was just written, the second half of a wide character whose
    first half was written over: it becomes a space, as in the console."""
    if x < columns and line[x].data == "":
        line[x] = line[x]._replace(data=" ")


class TermScreen(pyte.Screen):
    def __init__(
        self,
        columns: int,
        lines: int,
        *,
        scrollback: int = SCROLLBACK,
        reply: Callable[[str], None] | None = None,
    ) -> None:
        self.scrollback: deque[PackedLine] = deque(maxlen=scrollback)
        self.in_alt = False
        self.win32_input = False  # the console asked for key events (ESC[?9001h)
        self._main_buffer: Any = None
        self._reply = reply or (lambda data: None)
        self.titles_seen = 0
        self.bells = 0
        self.lines_scrolled = 0  # lines that went into the scrollback, ever
        self._cell_cache: dict[Any, dict[str, Any]] = {}
        super().__init__(columns, lines)

    # ---- what the server may not do: rename the tab, ring, or be answered beyond the standard

    def set_title(self, param: str) -> None:
        self.titles_seen += 1

    def set_icon_name(self, param: str) -> None:
        self.titles_seen += 1

    def bell(self, *args: Any) -> None:
        self.bells += 1

    def write_process_input(self, data: str) -> None:
        self._reply(data)

    @property
    def bracketed_paste(self) -> bool:
        return BRACKETED_PASTE in self.mode

    @property
    def app_cursor_keys(self) -> bool:
        """The program's ESC[?1h, if the console passes it on: Up is then ESC O A."""
        return APP_CURSOR_KEYS in self.mode

    # ---- drawing ----

    def draw(self, data: str) -> None:
        """pyte's draw stops at the first character with no width that isn't a combining mark,
        and drops the rest of the text: an ENQ right before other text, or the "]" after a
        heart's variation selector. Here control characters are skipped (the console never
        draws them) and everything else takes the console's cells (`_draw_cells`). Printable
        ASCII takes a fast path that reuses one cell object per style and character."""
        if not data.isprintable():
            data = "".join(ch for ch in data if unicodedata.category(ch) != "Cc")
            if not data:
                return
        if (
            not data.isascii()
            or self.charset
            or self.g0_charset is not cs.LAT1_MAP
            or mo.IRM in self.mode
        ):
            self._draw_cells(data)
            return
        attrs = self.cursor.attrs
        cache = self._cell_cache.get(attrs)
        if cache is None:
            if len(self._cell_cache) > 512:
                self._cell_cache.clear()
            cache = self._cell_cache[attrs] = {}
        cursor, columns = self.cursor, self.columns
        autowrap = mo.DECAWM in self.mode
        line = self.buffer[cursor.y]
        first = True
        for ch in data:
            if cursor.x == columns:
                if autowrap:
                    self.dirty.add(cursor.y)
                    self.carriage_return()
                    self.linefeed()
                    line = self.buffer[cursor.y]
                else:
                    cursor.x -= 1
            if first:  # the run's cells are contiguous: only its two ends can split a pair
                first = False
                _unpair_before(line, cursor.x)
            cell = cache.get(ch)
            if cell is None:
                cell = cache[ch] = attrs._replace(data=ch)
            line[cursor.x] = cell
            cursor.x += 1
        _unpair_after(line, cursor.x, columns)
        self.dirty.add(cursor.y)

    def _draw_cells(self, data: str) -> None:
        """pyte's draw with the console's widths: at least one cell each, so a combining accent,
        a joiner or a variation selector takes a cell of its own, as Windows' console gives it
        (pyte merges accents and stops at the others). A wide character that no longer fits the
        row goes whole to the next one, as in the console (pyte cuts it at the edge)."""
        data = data.translate(self.g1_charset if self.charset else self.g0_charset)
        cursor, columns = self.cursor, self.columns
        autowrap = mo.DECAWM in self.mode
        insert = mo.IRM in self.mode
        for ch in data:
            width = cells_for(ch)
            if cursor.x + width > columns:
                if autowrap:
                    self.dirty.add(cursor.y)
                    self.carriage_return()
                    self.linefeed()
                else:
                    cursor.x = max(0, columns - width)
            if insert:
                self.insert_characters(width)
            line = self.buffer[cursor.y]
            _unpair_before(line, cursor.x)
            line[cursor.x] = cursor.attrs._replace(data=ch)
            if width == 2:
                line[cursor.x + 1] = cursor.attrs._replace(data="")
            cursor.x += width
            _unpair_after(line, cursor.x, columns)
        self.dirty.add(cursor.y)

    # ---- colours as palette numbers ----

    def select_graphic_rendition(self, *attrs: int, **kwargs: Any) -> None:
        if kwargs.get("private"):
            return  # CSI ? ... m is a query (vim sends ESC[?4m), not a colour
        if not attrs or attrs == (0,):
            self.cursor.attrs = self.default_char
            return
        replace: dict[str, Any] = {}
        flags = {
            1: ("bold", True), 22: ("bold", False), 3: ("italics", True),
            23: ("italics", False), 4: ("underscore", True), 24: ("underscore", False),
            5: ("blink", True), 25: ("blink", False), 7: ("reverse", True),
            27: ("reverse", False), 9: ("strikethrough", True), 29: ("strikethrough", False),
        }  # fmt: skip
        rest = list(attrs)
        i = 0
        while i < len(rest):
            a = rest[i]
            i += 1
            if a == 0:
                replace.update(fg="default", bg="default", bold=False, italics=False,
                               underscore=False, strikethrough=False, reverse=False,
                               blink=False)  # fmt: skip
            elif a in flags:
                name, value = flags[a]
                replace[name] = value
            elif 30 <= a <= 37:
                replace["fg"] = a - 30
            elif a == 39:
                replace["fg"] = "default"
            elif 40 <= a <= 47:
                replace["bg"] = a - 40
            elif a == 49:
                replace["bg"] = "default"
            elif 90 <= a <= 97:
                replace["fg"] = a - 90 + 8
            elif 100 <= a <= 107:
                replace["bg"] = a - 100 + 8
            elif a in (38, 48) and i < len(rest):
                key = "fg" if a == 38 else "bg"
                kind = rest[i]
                if kind == 5 and i + 1 < len(rest):
                    replace[key] = max(0, min(255, rest[i + 1]))
                    i += 2
                elif kind == 2 and i + 3 < len(rest):
                    r, g, b = (max(0, min(255, v)) for v in rest[i + 1 : i + 4])
                    replace[key] = f"#{r:02x}{g:02x}{b:02x}"
                    i += 4
                else:
                    i = len(rest)
        self.cursor.attrs = self.cursor.attrs._replace(**replace)

    # ---- the alternate screen ----

    def set_mode(self, *modes: int, **kwargs: Any) -> None:
        if kwargs.get("private"):
            for m in modes:
                if m == WIN32_INPUT:
                    self.win32_input = True
                if m in ALT_SCREEN_MODES and not self.in_alt:
                    if m == 1049:
                        self.save_cursor()
                    self._main_buffer = self.buffer
                    self.buffer = defaultdict(lambda: StaticDefaultDict(self.default_char))
                    self.in_alt = True
                    self.dirty.update(range(self.lines))
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs: Any) -> None:
        if kwargs.get("private"):
            for m in modes:
                if m == WIN32_INPUT:
                    self.win32_input = False
                if m in ALT_SCREEN_MODES and self.in_alt:
                    self.buffer = self._main_buffer
                    self._main_buffer = None
                    self.in_alt = False
                    if m == 1049:
                        self.restore_cursor()
                    self.dirty.update(range(self.lines))
        super().reset_mode(*modes, **kwargs)

    # ---- the scrollback ----

    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom and top == 0 and not self.in_alt:
            self.scrollback.append(pack(self.buffer[0], self.columns))
            self.lines_scrolled += 1
        super().index()

    def erase_in_display(self, how: int = 0, *args: Any, **kwargs: Any) -> None:
        super().erase_in_display(how, *args, **kwargs)
        if how == 3:
            self.scrollback.clear()

    def resize(self, lines: int | None = None, columns: int | None = None) -> None:
        """pyte's resize deletes lines from the top of the screen wherever the cursor is, so a
        failed connection's message on the first row was lost when the ended strip took room.
        Here blank rows go from the bottom first; lines go off the top, into the scrollback,
        only as far as the cursor needs to stay on screen. An ended tab has no console left to
        repaint it, so this is all it gets."""
        lines = lines or self.lines
        columns = columns or self.columns
        if lines == self.lines and columns == self.columns:
            return
        if lines < self.lines:
            off_top = max(0, self.cursor.y + 1 - lines)
            if off_top:
                if not self.in_alt:
                    for y in range(off_top):
                        self.scrollback.append(pack(self.buffer[y], self.columns))
                        self.lines_scrolled += 1
                for y in range(self.lines - off_top):
                    self.buffer[y] = self.buffer[y + off_top]
                self.cursor.y -= off_top
            for y in range(lines, self.lines + off_top):
                self.buffer.pop(y, None)
        if columns < self.columns:
            for line in self.buffer.values():
                for x in [x for x in line if x >= columns]:
                    line.pop(x, None)
        self.lines, self.columns = lines, columns
        self.tabstops = {t for t in self.tabstops if t < columns} | set(range(8, columns, 8))
        self.cursor.x = min(self.cursor.x, columns - 1)
        self.margins = None
        self.dirty.update(range(lines))

    def clear_scrollback(self) -> None:
        self.scrollback.clear()

    # ---- reading it back ----

    def row(self, index: int) -> tuple[list[str], list[Style]]:
        """Row `index` of scrollback plus screen (0 is the oldest scrollback line)."""
        sb = len(self.scrollback)
        if index < sb:
            return unpack(self.scrollback[index], self.columns)
        cells = _cells(self.buffer[index - sb], self.columns)
        return list(map(_DATA, cells)), [_style(k) for k in map(_KEY, cells)]

    @property
    def total_rows(self) -> int:
        return len(self.scrollback) + self.lines

    def row_text(self, index: int) -> str:
        chars, _styles = self.row(index)
        return "".join(chars).rstrip()

    def screen_text(self) -> list[str]:
        sb = len(self.scrollback)
        return [self.row_text(sb + y) for y in range(self.lines)]

    def scrollback_text(self) -> list[str]:
        return ["".join(unpack(p, self.columns)[0]).rstrip() for p in self.scrollback]

    def text_between(self, start: tuple[int, int], end: tuple[int, int]) -> str:
        """The text from cell `start` to cell `end` (row, column; both included), rows joined
        with CRLF and trailing blanks dropped, as Windows' clipboard wants it."""
        (r0, c0), (r1, c1) = sorted((start, end))
        out = []
        for r in range(r0, r1 + 1):
            chars, _styles = self.row(r)
            a = c0 if r == r0 else 0
            b = c1 + 1 if r == r1 else self.columns
            out.append("".join(chars[a:b]).rstrip())
        return "\r\n".join(out)


class TermStream(pyte.ByteStream):
    """pyte's ByteStream, except that a sequence its screen can't take costs that sequence only.
    pyte hands any CSI with "?" to its handler with private=True, and most handlers don't take
    it: in pyte, one ESC[?4m (vim asks it at start) raised and lost the rest of the read, which
    was vim's whole first frame."""

    dropped = 0

    def feed(self, data: bytes) -> None:  # type: ignore[override]
        text = self.utf8_decoder.decode(data) if self.use_utf8 else "".join(map(chr, data))
        listener = self.listener
        assert listener is not None
        draw = listener.draw
        match_text = self._text_pattern.match
        taking_plain_text = self._taking_plain_text
        length, offset = len(text), 0
        while offset < length:
            before = offset
            try:
                if taking_plain_text:
                    match = match_text(text, offset)
                    if match:
                        start, offset = match.span()
                        draw(text[start:offset])
                    else:
                        taking_plain_text = False
                else:
                    taking_plain_text = self._send_to_parser(text[offset : offset + 1])
                    offset += 1
            except Exception:  # noqa: BLE001 -- pyte has reset its parser; go on after it
                self.dropped += 1
                taking_plain_text = True
                offset = max(offset, before + 1)
        self._taking_plain_text = taking_plain_text
