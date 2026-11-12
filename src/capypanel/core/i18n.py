"""Translations with gettext. `_()` reads the current catalog, so the language can change live."""

import gettext
from pathlib import Path

DOMAIN = "capypanel"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"

# Each language is named in its own language, never translated.
LANGUAGES = {"en": "English", "pt_BR": "Português (Brasil)"}
DEFAULT_LANGUAGE = "en"

_current: gettext.NullTranslations = gettext.NullTranslations()
_code = DEFAULT_LANGUAGE


def set_language(code: str) -> str:
    """Switch the catalog; an unknown code falls back to English. Returns the code in use."""
    global _current, _code
    if code not in LANGUAGES:
        code = DEFAULT_LANGUAGE
    _current = gettext.translation(DOMAIN, LOCALE_DIR, [code], fallback=True)
    _code = code
    return code


def language() -> str:
    return _code


def _(message: str) -> str:
    return _current.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _current.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    """The same English text translated by context, e.g. a word whose gender depends on what
    it's about ("printers" and "hosts" differ in Portuguese)."""
    return _current.pgettext(context, message)


def npgettext(context: str, singular: str, plural: str, n: int) -> str:
    return _current.npgettext(context, singular, plural, n)


def in_every_language(message: str) -> list[str]:
    """The message in each language, e.g. to size something so it never changes on a switch."""
    return [
        gettext.translation(DOMAIN, LOCALE_DIR, [code], fallback=True).gettext(message)
        for code in LANGUAGES
    ]


PORTUGUESE = 0x16  # Windows' primary language id for Portuguese, Brazil's and Portugal's


def language_for(windows_id: int) -> str:
    """The app's language for a Windows language id: Portuguese for any Portuguese (Brazil's
    is the one we have), English for every other."""
    return "pt_BR" if windows_id & 0x3FF == PORTUGUESE else DEFAULT_LANGUAGE


def windows_language() -> str:
    """The app's language for the language this person sees Windows in (the display language,
    not the region's formats). English where Windows doesn't say."""
    try:
        import ctypes

        windows_id = ctypes.WinDLL("kernel32").GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return DEFAULT_LANGUAGE
    return language_for(int(windows_id))


def N_(message: str) -> str:
    """Mark a string for extraction without translating it yet."""
    return message
