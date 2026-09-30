"""The translation files stay in step with the code: nothing missing, stale or half-translated."""

import gettext
import re
from pathlib import Path

import pytest
from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
from babel.messages.pofile import read_po

from capypanel.core import i18n

PACKAGE = Path(i18n.__file__).resolve().parent.parent
TRANSLATED = [code for code in i18n.LANGUAGES if code != i18n.DEFAULT_LANGUAGE]
FIX = "run: uv run python scripts/translations.py"
type Texts = tuple[str, ...]  # one text, or singular and plural


def _texts(value: object) -> Texts:
    if isinstance(value, tuple | list):
        return tuple(str(v) for v in value)
    return (str(value),) if value else ()


def _in_code() -> set[Texts]:
    found = extract_from_dir(str(PACKAGE), [("**.py", "python")], keywords=DEFAULT_KEYWORDS)
    return {_texts(message) for _file, _line, message, _comments, _context in found}


def _po(code: str) -> list[tuple[Texts, Texts, set[str]]]:
    """(source texts, translated texts, flags) for every entry but the header."""
    path = i18n.LOCALE_DIR / code / "LC_MESSAGES" / f"{i18n.DOMAIN}.po"
    with path.open("rb") as f:
        catalog = read_po(f, locale=code)
    return [(_texts(m.id), _texts(m.string), set(m.flags)) for m in catalog if m.id]


def _fields(text: str) -> set[str]:
    return set(re.findall(r"\{\w+\}", text))


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_text_in_the_code_is_in_the_catalog(code: str) -> None:
    catalog = {ids for ids, _strings, _flags in _po(code)}
    assert not _in_code() - catalog, f"new texts not in the {code} catalog; {FIX}"
    assert not catalog - _in_code(), f"texts no longer used are still in the catalog; {FIX}"


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_text_is_translated_with_the_same_fields(code: str) -> None:
    for ids, strings, flags in _po(code):
        assert "fuzzy" not in flags, f"needs checking: {ids[0]!r}"
        assert strings and all(strings), f"not translated: {ids[0]!r}"
        # A translation may drop {n} ("O host desse grupo…") but never invent a field.
        for text in strings:
            assert _fields(text) <= _fields(ids[-1]), f"unknown field in {text!r}"
            if "&" in ids[0]:
                assert text.count("&") == 1, f"access key lost in {text!r}"


@pytest.mark.parametrize("code", TRANSLATED)
def test_compiled_catalog_matches_the_source(code: str) -> None:
    # The app reads the .mo; a forgotten compile would ship old translations.
    compiled = gettext.translation(i18n.DOMAIN, i18n.LOCALE_DIR, [code])
    for ids, strings, _flags in _po(code):
        if len(ids) == 2:
            assert compiled.ngettext(ids[0], ids[1], 2) == strings[1], FIX
        else:
            assert compiled.gettext(ids[0]) == strings[0], FIX
