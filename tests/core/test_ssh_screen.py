"""The terminal's screen on our pyte, and what a server may not do to it."""

import pytest
from console_cells import CONSOLE_CELLS  # as Windows' own console counted them

from capypanel.core.ssh import screen as screen_module
from capypanel.core.ssh.screen import (
    DEFAULT_STYLE,
    TermScreen,
    TermStream,
    cells_for,
    pack,
    unpack,
)
from capypanel.vendor.pyte._widths import wcwidth


def screen_and_stream(columns: int = 40, lines: int = 5, **kw) -> tuple[TermScreen, TermStream]:
    screen = TermScreen(columns, lines, **kw)
    return screen, TermStream(screen)


@pytest.mark.parametrize(("sample", "cells"), CONSOLE_CELLS)
def test_each_sample_takes_the_cells_the_console_gives_it(sample: str, cells: int) -> None:
    screen, stream = screen_and_stream()
    stream.feed(("[" + sample + "]").encode())
    assert screen.cursor.x == cells + 2
    assert screen.row_text(0).endswith("]")  # nothing after the sample was lost


def test_half_a_flag_takes_the_cells_its_console_engine_gives_it() -> None:
    for cells, flag_cells in ((2, 4), (1, 2)):
        screen, stream = screen_and_stream()
        screen.regional_indicator_cells = cells
        stream.feed("[\U0001f1e7\U0001f1f7]".encode())
        assert screen.cursor.x == flag_cells + 2
        assert screen.row_text(0).endswith("]")


def test_the_widths_are_wcwidths_from_pythons_own_tables() -> None:
    assert wcwidth("\x07") == -1
    assert wcwidth("\x9b") == -1
    assert wcwidth("\u0301") == 0  # combining
    assert wcwidth("\u3099") == 0  # combining, though East Asian Wide
    assert wcwidth("\u200d") == 0  # a joiner
    assert wcwidth("\u00ad") == 1  # the soft hyphen shows, as in wcwidth
    assert wcwidth("\U0001f1e6") == 2  # a regional indicator
    assert wcwidth("Ａ") == 2
    assert wcwidth("a") == 1
    assert [cells_for(c) for c in "\u0301\u200d\x07"] == [1, 1, 1]  # never less than one


def test_a_wide_character_that_no_longer_fits_goes_whole_to_the_next_row() -> None:
    screen, stream = screen_and_stream(columns=5)
    stream.feed("abcd中".encode())
    assert screen.row_text(0) == "abcd"
    assert screen.row_text(1) == "中"


def test_writing_over_half_of_a_wide_character_blanks_its_other_half() -> None:
    screen, stream = screen_and_stream()
    stream.feed("中文\r\n中文".encode())
    stream.feed(b"\x1b[1;2HX")  # over the right half of the first
    stream.feed(b"\x1b[2;3HY")  # over the left half of the second
    assert screen.row_text(0) == " X文"
    assert screen.row(1)[0][:4] == ["中", "", "Y", " "]


def test_a_private_sgr_costs_nothing_after_it() -> None:
    screen, stream = screen_and_stream()
    stream.feed(b"\x1b[?4mvim's first frame")
    assert screen.row_text(0) == "vim's first frame"


class _Refusing(TermScreen):
    def erase_in_line(self, *args: object, **kwargs: object) -> None:
        raise ValueError("a handler that can't take what it was given")


def test_a_sequence_the_screen_cant_take_costs_that_sequence_only() -> None:
    screen = _Refusing(40, 5)
    stream = TermStream(screen)
    stream.feed(b"before\x1b[Kafter")
    assert screen.row_text(0) == "beforeafter"
    assert stream.dropped == 1


def test_an_enq_or_a_variation_selector_never_drops_the_text_after_it() -> None:
    screen, stream = screen_and_stream()
    stream.feed("\x05<SENT> ❤\ufe0f]".encode())
    assert screen.row_text(0) == "<SENT> ❤\ufe0f]"


def test_colours_stay_palette_numbers_so_a_theme_switch_recolours_them() -> None:
    screen, stream = screen_and_stream()
    stream.feed(b"\x1b[31ma\x1b[91;101mb\x1b[38;5;200;48;5;17mc\x1b[38;2;1;2;3md\x1b[0me")
    _chars, styles = screen.row(0)
    assert (styles[0].fg, styles[0].bg) == (1, "default")
    assert (styles[1].fg, styles[1].bg) == (9, 9)
    assert (styles[2].fg, styles[2].bg) == (200, 17)
    assert styles[3].fg == "#010203"
    assert styles[4] == DEFAULT_STYLE


def test_titles_never_reach_anything_and_nothing_is_answered_beyond_the_standard() -> None:
    replies: list[str] = []
    screen, stream = screen_and_stream(reply=replies.append)
    stream.feed(b"\x1b]0;rename the tab\x07\x1b]2;again\x1b\\\x1b]52;c;c2VjcmV0\x07text\x07")
    assert screen.titles_seen == 3  # OSC 0 sets the title and the icon name, OSC 2 the title
    assert screen.bells == 1
    assert screen.row_text(0) == "text"
    stream.feed(b"\x1b[c")  # device attributes: a standard reply
    assert len(replies) == 1


def test_the_alternate_screen_leaves_the_main_one_and_the_scrollback_as_they_were() -> None:
    screen, stream = screen_and_stream(lines=3)
    stream.feed(b"one\r\ntwo\r\nthree\r\nfour")
    assert screen.scrollback_text() == ["one"]
    stream.feed(b"\x1b[?1049h\x1b[2J\x1b[Hvim\r\n~\r\n~\r\n~\r\n~")
    assert screen.in_alt
    assert screen.scrollback_text() == ["one"]  # nothing of vim's
    stream.feed(b"\x1b[?1049l")
    assert not screen.in_alt
    assert screen.screen_text() == ["two", "three", "four"]


def test_the_scrollback_keeps_its_last_lines_only() -> None:
    screen, stream = screen_and_stream(lines=2, scrollback=3)
    stream.feed(b"\r\n".join(b"line %d" % n for n in range(10)))
    assert screen.scrollback_text() == ["line 5", "line 6", "line 7"]
    assert screen.lines_scrolled == 8
    stream.feed(b"\x1b[3J")
    assert screen.scrollback_text() == []


def test_a_flood_of_colours_keeps_the_shared_styles_within_their_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every cell in a 24-bit colour of its own: the styles lines share start over when full,
    # instead of outliving the tab, and every cell keeps its own colour.
    monkeypatch.setattr(screen_module, "MAX_STYLES", 64)
    screen, stream = screen_and_stream(columns=10, lines=2, scrollback=100)
    for n in range(300):
        stream.feed(f"\x1b[38;2;0;{n // 256};{n % 256}mx".encode())
    assert len(screen_module._styles) <= 64
    colours = [style.fg for row in range(screen.total_rows) for style in screen.row(row)[1]]
    assert colours == [f"#00{n // 256:02x}{n % 256:02x}" for n in range(300)]


def test_a_packed_line_comes_back_as_it_was() -> None:
    screen, stream = screen_and_stream()
    stream.feed("a\x1b[1;31mb中c\x1b[0md  ".encode())
    chars, styles = screen.row(0)
    packed = pack(screen.buffer[0], screen.columns)
    assert unpack(packed, screen.columns) == (chars, styles)


def test_shrinking_keeps_a_message_on_the_first_row() -> None:
    screen, stream = screen_and_stream(lines=10)
    stream.feed(b"ssh: connect to host port 22: Connection refused\r\n")
    screen.resize(lines=7)
    assert screen.screen_text()[0].startswith("ssh: connect")
    assert screen.scrollback_text() == []


def test_shrinking_below_the_cursor_moves_lines_into_the_scrollback() -> None:
    screen, stream = screen_and_stream(lines=5)
    stream.feed(b"1\r\n2\r\n3\r\n4\r\n5")
    screen.resize(lines=3)
    assert screen.scrollback_text() == ["1", "2"]
    assert screen.screen_text() == ["3", "4", "5"]


def test_bracketed_paste_follows_the_program() -> None:
    screen, stream = screen_and_stream()
    assert not screen.bracketed_paste
    stream.feed(b"\x1b[?2004h")
    assert screen.bracketed_paste
    stream.feed(b"\x1b[?2004l")
    assert not screen.bracketed_paste


def test_the_console_s_ask_for_key_events_outlasts_a_reset_from_the_server() -> None:
    screen, stream = screen_and_stream()
    assert not screen.win32_input  # Windows 10's console never asks
    stream.feed(b"\x1b[?9001h\x1b[?1004h")  # Windows 11's, first thing
    assert screen.win32_input
    stream.feed(b"\x1bc")  # the console still reads key events after the server's reset
    assert screen.win32_input
    stream.feed(b"\x1b[?9001l")
    assert not screen.win32_input


def test_application_cursor_keys_follow_the_program() -> None:
    screen, stream = screen_and_stream()
    assert not screen.app_cursor_keys
    stream.feed(b"\x1b[?1h")
    assert screen.app_cursor_keys
    stream.feed(b"\x1b[?1l")
    assert not screen.app_cursor_keys


def test_copied_text_joins_rows_with_crlf_without_trailing_blanks() -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed(b"first\r\nsecond   \r\nthird")
    assert screen.text_between((0, 2), (2, 1)) == "rst\r\nsecond\r\nth"


def test_a_line_longer_than_its_row_copies_as_one_line_with_the_blank_where_it_wrapped() -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed(b"abcd efgh ijkl\r\nnext")
    assert screen.text_between((0, 0), (2, 3)) == "abcd efgh ijkl\r\nnext"
    assert screen.text_between((0, 5), (1, 1)) == "efgh ij"


def test_a_wrapped_line_still_copies_as_one_line_from_the_scrollback() -> None:
    screen, stream = screen_and_stream(columns=10, lines=2)
    stream.feed(b"abcd efgh ijkl\r\n1\r\n2\r\n3")
    assert screen.scrollback_text() == ["abcd efgh", "ijkl", "1"]
    assert screen.text_between((0, 0), (1, 9)) == "abcd efgh ijkl"


def test_a_line_that_ends_at_the_row_s_edge_copies_on_its_own() -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed(b"abcdefghij\r\nnext")
    assert screen.text_between((0, 0), (1, 3)) == "abcdefghij\r\nnext"


def test_a_wide_character_that_wraps_whole_leaves_no_blank_in_the_copy() -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed("abcdefghi中".encode())
    assert screen.row_text(1) == "中"
    assert screen.text_between((0, 0), (1, 1)) == "abcdefghi中"


@pytest.mark.parametrize(
    ("then", "copied"),
    [
        (b"\x1b[1;5H\x1b[K", "abcd\r\nijkl"),  # erased from its 5th cell to its end
        (b"\x1b[1;1H\x1b[2K", "\r\nijkl"),  # erased whole
        (b"\x1b[2;1H\x1b[1J", "\r\n jkl"),  # the screen erased up to the next row's first cell
        (b"\x1b[2J", "\r\n"),  # the screen erased
        (b"\x1b[1;1Hshort\n", "shortefgh\r\nijkl"),  # written over, then left by a line feed
    ],
)
def test_a_row_erased_to_its_end_or_left_by_a_line_feed_no_longer_joins_the_next(
    then: bytes, copied: str
) -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed(b"abcd efgh ijkl")
    stream.feed(then)
    assert screen.text_between((0, 0), (1, 9)) == copied


def test_a_line_windows_own_engine_wraps_after_a_scroll_copies_as_one_line() -> None:
    # Its bytes: the row's first part, a line feed that scrolls, then the row's last cell
    # written again, so the terminal wraps by itself (tests/core/test_ssh_conpty.py).
    screen, stream = screen_and_stream(columns=10, lines=3)
    stream.feed(b"1\r\n2\r\nabcdefghij\r\n\x1b[2;10Hjklm")
    assert screen.text_between((2, 0), (3, 9)) == "abcdefghijklm"


def test_a_wrapped_line_copies_without_the_room_the_window_gained_since() -> None:
    screen, stream = screen_and_stream(columns=10)
    stream.feed(b"abcd efgh ijkl")
    screen.resize(columns=20)
    assert screen.text_between((0, 0), (1, 19)) == "abcd efgh ijkl"
