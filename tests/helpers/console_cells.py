"""The cells Windows' console gives characters: CONSOLE_CELLS for the screen's tests; run in a
pseudo console, it measures them (args: the samples' JSON file, then the answer's file)."""

import ctypes
import json
import sys
from ctypes import wintypes as wt

# Each sample's cells as Windows' own console gave them (its cursor column, read with
# GetConsoleScreenBufferInfo). The screen must place everything where the console does.
CONSOLE_CELLS = [
    ("abc", 3),
    ("ção", 3),  # pt-BR accents, precomposed
    ("é", 2),  # e and a combining acute: a cell each
    ("中文", 4),  # CJK
    ("한", 2),  # Hangul
    ("Ａ", 2),  # fullwidth A
    ("\U0001f44d", 2),  # thumbs up
    ("❤️", 2),  # heart and VS16: a cell each
    ("⚠", 1),  # warning sign
    ("\U0001f1e7\U0001f1f7", 4),  # the Brazilian flag: two wide regional indicators
    ("\U0001f469‍\U0001f4bb", 5),  # woman technologist: 2, the joiner 1, 2
    ("─│", 2),  # box drawing
    ("→", 1),  # arrow
    ("⚠️", 2),  # warning and VS16
    ("", 1),  # a Powerline separator (private use)
    ("a​b", 3),  # a zero-width space takes a cell
    ("\U0001fae8", 2),  # a Unicode 15 emoji
    ("±", 1),  # plus-minus (ambiguous width)
    ("❤", 1),  # heart alone
]


class COORD(ctypes.Structure):
    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", wt.SHORT), ("Top", wt.SHORT), ("Right", wt.SHORT), ("Bottom", wt.SHORT)]


class SCREEN_BUFFER_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", COORD),
        ("dwCursorPosition", COORD),
        ("wAttributes", wt.WORD),
        ("srWindow", SMALL_RECT),
        ("dwMaximumWindowSize", COORD),
    ]


def measure(samples: list[str]) -> list[int]:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wt.HANDLE
    # The console itself, whatever the standard handles are
    console = wt.HANDLE(k32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None))

    def write(text: str) -> None:
        units = len(text.encode("utf-16-le")) // 2  # WriteConsoleW counts UTF-16 units
        k32.WriteConsoleW(console, ctypes.c_wchar_p(text), units, None, None)

    def column() -> int:
        info = SCREEN_BUFFER_INFO()
        k32.GetConsoleScreenBufferInfo(console, ctypes.byref(info))
        return info.dwCursorPosition.X

    cells = []
    for sample in samples:
        write("\r\n")
        start = column()
        write(sample)
        cells.append(column() - start)
    return cells


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as file:
        measured = measure(json.load(file))
    with open(sys.argv[2], "w", encoding="utf-8") as file:
        json.dump(measured, file)
