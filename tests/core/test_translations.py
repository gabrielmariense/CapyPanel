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
type Key = tuple[str | None, Texts]  # the context (most texts have none) and the texts


def _texts(value: object) -> Texts:
    if isinstance(value, tuple | list):
        return tuple(str(v) for v in value)
    return (str(value),) if value else ()


def _in_code() -> set[Key]:
    found = extract_from_dir(str(PACKAGE), [("**.py", "python")], keywords=DEFAULT_KEYWORDS)
    return {(context or None, _texts(message)) for *_, message, _notes, context in found}


def _po(code: str) -> list[tuple[Key, Texts, set[str]]]:
    """(context and source texts, translated texts, flags) for every entry but the header."""
    path = i18n.LOCALE_DIR / code / "LC_MESSAGES" / f"{i18n.DOMAIN}.po"
    with path.open("rb") as f:
        catalog = read_po(f, locale=code)
    return [
        ((m.context or None, _texts(m.id)), _texts(m.string), set(m.flags)) for m in catalog if m.id
    ]


def _fields(text: str) -> set[str]:
    return set(re.findall(r"\{\w+\}", text))


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_text_in_the_code_is_in_the_catalog(code: str) -> None:
    catalog = {key for key, _strings, _flags in _po(code)}
    assert not _in_code() - catalog, f"new texts not in the {code} catalog; {FIX}"
    assert not catalog - _in_code(), f"texts no longer used are still in the catalog; {FIX}"


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_text_is_translated_with_the_same_fields(code: str) -> None:
    for (_context, ids), strings, flags in _po(code):
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
    for (context, ids), strings, _flags in _po(code):
        if len(ids) == 2 and context:
            assert compiled.npgettext(context, ids[0], ids[1], 2) == strings[1], FIX
        elif len(ids) == 2:
            assert compiled.ngettext(ids[0], ids[1], 2) == strings[1], FIX
        elif context:
            assert compiled.pgettext(context, ids[0]) == strings[0], FIX
        else:
            assert compiled.gettext(ids[0]) == strings[0], FIX


def test_portuguese_zero_is_plural() -> None:
    # "0 selecionados", not "0 selecionado": only exactly one is singular (maintainer's call).
    compiled = gettext.translation(i18n.DOMAIN, i18n.LOCALE_DIR, ["pt_BR"])
    assert compiled.ngettext("{n} selected", "{n} selected", 0) == "{n} selecionados"
    assert compiled.ngettext("{n} selected", "{n} selected", 1) == "{n} selecionado"
