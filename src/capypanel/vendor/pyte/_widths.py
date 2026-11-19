"""
    pyte._widths
    ~~~~~~~~~~~~

    Character widths for CapyPanel's copy of pyte, from Python's own Unicode
    tables (unicodedata), in place of the wcwidth package, so nothing else
    joins the app. The answers are wcwidth's, as pyte uses them:

    * -1 for a control character;
    * 0 for one that takes no cell of its own: a combining mark, or a format
      character such as a zero-width joiner or space;
    * 2 for a wide one: East Asian Wide or Fullwidth, and the regional
      indicators that make up a flag, which wcwidth and Windows' console both
      count as wide (the console gives a flag four cells);
    * 1 for the rest.

    A character newer than Python's tables (Unicode 15.1 in Python 3.13)
    counts as 1.

    Added by CapyPanel on 2026-11-18. Part of CapyPanel's copy of pyte, under
    pyte's own license: LGPL, see LICENSE for more details.
"""
from __future__ import annotations

import unicodedata
from functools import lru_cache

REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)


@lru_cache(maxsize=4096)
def wcwidth(char: str) -> int:
    code = ord(char)
    if code == 0:
        return 0
    if code < 0x20 or 0x7F <= code < 0xA0:
        return -1
    if unicodedata.category(char) in ("Mn", "Me", "Cf") and code != 0xAD:
        return 0  # the soft hyphen shows, as in wcwidth
    if code in REGIONAL_INDICATORS or unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    return 1
