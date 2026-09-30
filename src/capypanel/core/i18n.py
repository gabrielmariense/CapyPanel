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


def N_(message: str) -> str:
    """Mark a string for extraction without translating it yet."""
    return message
