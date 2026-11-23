from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from itertools import groupby
from operator import itemgetter
from typing import Any, NamedTuple, cast

from capypanel.vendor import pyte
from capypanel.vendor.pyte import charsets as cs
from capypanel.vendor.pyte import modes as mo
from capypanel.vendor.pyte._widths import REGIONAL_INDICATORS, wcwidth
from capypanel.vendor.pyte.screens import Char, Margins, StaticDefaultDict

SCROLLBACK = 10_000  # lines
ALT_SCREEN_MODES = (1049, 1047, 47)
BRACKETED_PASTE = 2004 << 5  # pyte keeps private modes shifted left by 5
APP_CURSOR_KEYS = 1 << 5  # DECCKM, which pyte doesn't name
WIN32_INPUT = 9001  # private mode: keys as Windows key events


class Style(NamedTuple):
    fg: int | str = "default"
    bg: int | str = "default"
    bold: bool = False
    italics: bool = False
    underscore: bool = False
    strikethrough: bool = False
    reverse: bool = False


DEFAULT_STYLE = Style()
_DEFAULT_KEY = tuple(DEFAULT_STYLE)
_styles: dict[tuple[Any, ...], Style] = {_DEFAULT_KEY: DEFAULT_STYLE}
# Full, it starts over: 24-bit colour per cell would otherwise grow it without end.
MAX_STYLES = 4096
_KEY = itemgetter(1, 2, 3, 4, 5, 6, 7)  # a pyte Char's fg .. reverse, read in C
_DATA = itemgetter(0)


def _style(key: tuple[Any, ...]) -> Style:
    style = _styles.get(key)
    if style is None:
        if len(_styles) >= MAX_STYLES:
            _styles.clear()
            _styles[_DEFAULT_KEY] = DEFAULT_STYLE
        style = _styles[key] = Style(*key)
    return style


def cells_for(char: str) -> int:
    return 2 if wcwidth(char) == 2 else 1


class PackedLine(NamedTuple):
    cells: str | tuple[str, ...]
    runs: tuple[tuple[int, int, Style], ...]
    wrapped_at: int = 0  # the cells it held when its line went on to the next row; 0: it ended


def _cells(line: Any, columns: int) -> list[Any]:
    get, default = line.get, line.default
    return [get(x, default) for x in range(columns)]


def pack(line: Any, columns: int) -> PackedLine:
    """map, groupby and itemgetter keep the per-cell work in C: a flood of output depends on it."""
    chars = _cells(line, columns)
    keys = list(map(_KEY, chars))
    datas = list(map(_DATA, chars))
    wrapped_at = min(line.wrapped_at, columns)
    last = columns
    while last > wrapped_at and keys[last - 1] == _DEFAULT_KEY and datas[last - 1] in (" ", ""):
        last -= 1  # trailing blanks in the default style aren't kept, but a wrapped line's are
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
    return PackedLine(cells, tuple(runs), wrapped_at)


def unpack(packed: PackedLine, columns: int) -> tuple[list[str], list[Style]]:
    chars = [" "] * columns
    styles = [DEFAULT_STYLE] * columns
    for x, ch in enumerate(packed.cells[:columns]):
        chars[x] = "" if ch == "\0" else ch
    for start, end, style in packed.runs:
        for x in range(start, min(end, columns)):
            styles[x] = style
    return chars, styles


def rewrap(
    rows: Iterable[PackedLine], columns: int, mark: tuple[int, int] | None = None
) -> tuple[list[PackedLine], tuple[int, int] | None]:
    """Rows of any widths laid out again at `columns` as the console does, a wide character that
    won't fit moved down. `mark` (row, cell) moves with its text, past the line's end too."""
    out: list[PackedLine] = []
    parts: list[str | tuple[str, ...]] = []
    runs: list[tuple[int, int, Style]] = []
    length = 0
    marked: int | None = None
    moved: tuple[int, int] | None = None
    for index, row in enumerate(rows):
        is_marked = mark is not None and index == mark[0]
        if not parts and not row.wrapped_at and len(row.cells) <= columns and not is_marked:
            out.append(row)
            continue
        taken = row.wrapped_at or len(row.cells)
        if mark is not None and is_marked:
            marked = length + mark[1]
        for start, end, style in row.runs:
            if start < taken:
                runs.append((length + start, length + min(end, taken), style))
        parts.append(row.cells[:taken])
        length += taken
        if not row.wrapped_at:
            placed = _lay_out(parts, runs, length, columns, out, ended=True, marked=marked)
            moved = placed or moved
            parts, runs, length, marked = [], [], 0, None
    if parts:
        placed = _lay_out(parts, runs, length, columns, out, ended=False, marked=marked)
        moved = placed or moved
    return out, moved


def _lay_out(
    parts: list[str | tuple[str, ...]],
    runs: list[tuple[int, int, Style]],
    length: int,
    columns: int,
    out: list[PackedLine],
    *,
    ended: bool,
    marked: int | None,
) -> tuple[int, int] | None:
    line: str | tuple[str, ...]
    if all(isinstance(part, str) for part in parts):
        line = "".join(cast(list[str], parts))
    else:
        line = tuple(cell for part in parts for cell in part)
    if marked is not None and marked > length:
        pad = marked - length
        line = line + " " * pad if isinstance(line, str) else line + (" ",) * pad
        length = marked
    moved = None
    start = first_run = 0
    while True:
        end = min(start + columns, length)
        if end < length and line[end] == "\0" and end - 1 > start:
            end -= 1
        last = end >= length
        row_runs = []
        i = first_run
        while i < len(runs) and runs[i][0] < end:
            s, e, style = runs[i]
            if e > start:
                row_runs.append((max(s, start) - start, min(e, end) - start, style))
            i += 1
        while first_run < len(runs) and runs[first_run][1] <= end:
            first_run += 1
        if marked is not None and moved is None and (marked < end or last):
            moved = (len(out), marked - start)
        wrapped_at = 0 if last and ended else end - start
        out.append(PackedLine(line[start:end], tuple(row_runs), wrapped_at))
        if last:
            return moved
        start = end


def _row_from(packed: PackedLine, columns: int, blank: Char) -> _Row:
    row = _Row(blank)
    chars, styles = unpack(packed, columns)
    for x, (data, style) in enumerate(zip(chars, styles, strict=True)):
        if data != " " or style is not DEFAULT_STYLE:
            row[x] = blank._replace(data=data, **style._asdict())
    row.wrapped_at = packed.wrapped_at
    return row


def _matches(
    pattern: re.Pattern[str], rows: list[int], starts: list[int], cells: list[str]
) -> Iterator[tuple[int, int, int, int]]:
    text = "".join(cells)
    if len(text) == len(cells):
        owner: Sequence[int] = range(len(cells))
    else:
        owner = [i for i, cell in enumerate(cells) for _ in cell]
    for match in pattern.finditer(text):
        first, last = owner[match.start()], owner[match.end() - 1]
        if last + 1 < len(cells) and cells[last + 1] == "":
            last += 1  # a wide character's second half
        a, b = bisect_right(starts, first) - 1, bisect_right(starts, last) - 1
        yield rows[a], first - starts[a], rows[b], last - starts[b]


def _unpair_before(line: Any, x: int) -> None:
    """Writing over a wide character's second half blanks its first, as Windows' console does."""
    if x and line[x].data == "":
        line[x - 1] = line[x - 1]._replace(data=" ")


def _unpair_after(line: Any, x: int, columns: int) -> None:
    if x < columns and line[x].data == "":
        line[x] = line[x]._replace(data=" ")


class _Row(StaticDefaultDict[int, Char]):
    wrapped_at = 0


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
        self.win32_input = False  # ESC[?9001h, kept apart from pyte's modes: ESC c can't drop it
        # A regional indicator takes 2 cells in Windows' own console, 1 in the carried engine.
        self.regional_indicator_cells = 2
        self._main_buffer: Any = None
        self._main_size = (lines, columns)
        self.scrollback_settled = True  # every row laid out at the screen's width
        self._reply = reply or (lambda data: None)
        self.titles_seen = 0
        self.bells = 0
        self.lines_scrolled = 0
        self._cell_cache: dict[Any, dict[str, Any]] = {}
        self._wrapped_at = 0
        super().__init__(columns, lines)
        self.buffer = defaultdict(lambda: _Row(self.default_char))

    def _row(self, y: int) -> _Row:
        return cast(_Row, self.buffer[y])

    # What the server may not do: rename the tab, ring, or get answers beyond the standard ones.

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
        return APP_CURSOR_KEYS in self.mode

    def draw(self, data: str) -> None:
        """pyte's drops everything after a zero-width character that isn't combining."""
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
                    self._wrap()
                    line = self.buffer[cursor.y]
                else:
                    cursor.x -= 1
            if first:
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
        """As the console does: a combining mark or joiner gets a cell of its own, and a wide
        character that won't fit wraps whole."""
        data = data.translate(self.g1_charset if self.charset else self.g0_charset)
        cursor, columns = self.cursor, self.columns
        autowrap = mo.DECAWM in self.mode
        insert = mo.IRM in self.mode
        narrow_flags = self.regional_indicator_cells == 1
        for ch in data:
            width = cells_for(ch)
            if width == 2 and narrow_flags and ord(ch) in REGIONAL_INDICATORS:
                width = 1
            if cursor.x + width > columns:
                if autowrap:
                    self.dirty.add(cursor.y)
                    self._wrap()
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

    def _wrap(self) -> None:
        self._wrapped_at = self.cursor.x
        try:
            self.carriage_return()
            self.linefeed()
        finally:
            self._wrapped_at = 0

    # Colours stay palette numbers or "#rrggbb", so a theme switch recolours the scrollback too.

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

    # The alternate screen (1049, 1047, 47) is ours: pyte keeps the mode but doesn't act on it.

    def set_mode(self, *modes: int, **kwargs: Any) -> None:
        if kwargs.get("private"):
            for m in modes:
                if m == WIN32_INPUT:
                    self.win32_input = True
                if m in ALT_SCREEN_MODES and not self.in_alt:
                    if m == 1049:
                        self.save_cursor()
                    self._main_buffer = self.buffer
                    self._main_size = (self.lines, self.columns)
                    self.buffer = defaultdict(lambda: _Row(self.default_char))
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
                    if self._main_size != (self.lines, self.columns):
                        size = self.lines, self.columns
                        self.lines, self.columns = self._main_size
                        self.resize(*size)
                    self.dirty.update(range(self.lines))
        super().reset_mode(*modes, **kwargs)

    # The scrollback is ours, packed lines: pyte's HistoryScreen keeps whole cell objects.

    def index(self) -> None:
        # As in Windows Terminal: the row left goes on to the next only when autowrap left it.
        self._row(self.cursor.y).wrapped_at = self._wrapped_at
        top, bottom = self.margins or Margins(0, self.lines - 1)
        if self.cursor.y == bottom and top == 0 and not self.in_alt:
            self.scrollback.append(pack(self.buffer[0], self.columns))
            self.lines_scrolled += 1
        super().index()

    def erase_in_line(self, how: int = 0, *args: Any, **kwargs: Any) -> None:
        super().erase_in_line(how, *args, **kwargs)
        if how in (0, 2):
            self._row(self.cursor.y).wrapped_at = 0

    def erase_in_display(self, how: int = 0, *args: Any, **kwargs: Any) -> None:
        super().erase_in_display(how, *args, **kwargs)
        erased = {0: range(self.cursor.y + 1, self.lines), 1: range(self.cursor.y)}
        for y in erased.get(how, range(self.lines)):
            self._row(y).wrapped_at = 0
        if how == 3:
            self.scrollback.clear()

    def resize(
        self, lines: int | None = None, columns: int | None = None, *, defer: bool = False
    ) -> None:
        """Blank rows go from the bottom: pyte's cut the top, where an error message sits.
        `defer` leaves the scrollback to rewrap_scrollback(), as a window is dragged."""
        lines = lines or self.lines
        columns = columns or self.columns
        if lines == self.lines and columns == self.columns:
            return
        if columns != self.columns:
            self.scrollback_settled = False
            if not self.in_alt:
                self._rewrap_screen(columns)
        if lines < self.lines:
            off_top = max(0, self.cursor.y + 1 - lines)
            if off_top:
                if not self.in_alt:
                    for y in range(off_top):
                        self.scrollback.append(pack(self.buffer[y], columns))
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
        if not defer:
            self.rewrap_scrollback()

    def rewrap_scrollback(self) -> None:
        if not self.scrollback_settled:
            rows, _ = rewrap(self.scrollback, self.columns)
            self.scrollback = deque(rows, maxlen=self.scrollback.maxlen)
            self.scrollback_settled = True

    def _rewrap_screen(self, columns: int) -> None:
        """As the console lays out its own screen, so the two agree on the cursor: from the top,
        rows that no longer fit leave at the top, into the scrollback."""
        packed = [pack(self.buffer[y], self.columns) for y in range(self.lines)]
        used = max([y for y, row in enumerate(packed) if row.cells or row.runs] + [self.cursor.y])
        rows, moved = rewrap(packed[: used + 1], columns, (self.cursor.y, self.cursor.x))
        assert moved is not None
        off_top = max(0, len(rows) - self.lines)
        for row in rows[:off_top]:
            self.scrollback.append(row)
            self.lines_scrolled += 1
        self.buffer.clear()
        for y, row in enumerate(rows[off_top:]):
            self.buffer[y] = _row_from(row, columns, self.default_char)
        self.cursor.y, self.cursor.x = moved[0] - off_top, moved[1]

    def clear_scrollback(self) -> None:
        self.scrollback.clear()

    def row(self, index: int) -> tuple[list[str], list[Style]]:
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
        return ["".join(self._row_cells(r)).rstrip() for r in range(len(self.scrollback))]

    def whole_text(self) -> str:
        text = self.text_between((0, 0), (self.total_rows - 1, self.columns - 1))
        text = text.rstrip("\r\n")
        return text + "\r\n" if text else ""

    def wrapped_at(self, index: int) -> int:
        sb = len(self.scrollback)
        if index < sb:
            return self.scrollback[index].wrapped_at
        return self._row(index - sb).wrapped_at

    def _row_cells(self, index: int) -> list[str]:
        sb = len(self.scrollback)
        if index < sb:
            cells = self.scrollback[index].cells
            if isinstance(cells, str) and "\0" not in cells:
                return list(cells)
            return ["" if c == "\0" else c for c in cells]
        return list(map(_DATA, _cells(self.buffer[index - sb], self.columns)))

    def find(self, words: str, *, match_case: bool = False) -> list[tuple[int, int, int, int]]:
        """Each match as (row, cell, last row, last cell); a line wrapped over rows is one line."""
        if not words:
            return []
        pattern = re.compile(re.escape(words), 0 if match_case else re.IGNORECASE)
        found: list[tuple[int, int, int, int]] = []
        rows: list[int] = []
        starts: list[int] = []
        cells: list[str] = []
        last = self.total_rows - 1
        for r in range(self.total_rows):
            chars = self._row_cells(r)
            wrapped = self.wrapped_at(r)
            rows.append(r)
            starts.append(len(cells))
            cells.extend(chars[:wrapped] if wrapped else chars)
            if not wrapped or r == last:
                found.extend(_matches(pattern, rows, starts, cells))
                rows, starts, cells = [], [], []
        return found

    def text_between(self, start: tuple[int, int], end: tuple[int, int]) -> str:
        """A wrapped line comes whole; lines end with CRLF, as Windows' clipboard wants."""
        (r0, c0), (r1, c1) = sorted((start, end))
        out = []
        for r in range(r0, r1 + 1):
            chars = self._row_cells(r)
            a = c0 if r == r0 else 0
            b = c1 + 1 if r == r1 else len(chars)
            wrapped_at = self.wrapped_at(r) if r < r1 else 0
            if wrapped_at:
                out.append("".join(chars[a:wrapped_at]))
            else:
                out.append("".join(chars[a:b]).rstrip() + ("\r\n" if r < r1 else ""))
        return "".join(out)


class TermStream(pyte.ByteStream):
    """pyte raised on a CSI "?" most handlers refuse (vim's ESC[?4m), losing the read."""

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
