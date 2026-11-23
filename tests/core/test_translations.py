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
type Texts = tuple[str, ...]
type Key = tuple[str | None, Texts]


def _texts(value: object) -> Texts:
    if isinstance(value, tuple | list):
        return tuple(str(v) for v in value)
    return (str(value),) if value else ()


def _in_code() -> set[Key]:
    found = extract_from_dir(str(PACKAGE), [("**.py", "python")], keywords=DEFAULT_KEYWORDS)
    return {(context or None, _texts(message)) for *_, message, _notes, context in found}


def _po(code: str) -> list[tuple[Key, Texts, set[str]]]:
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
        for text in strings:
            assert _fields(text) <= _fields(ids[-1]), f"unknown field in {text!r}"
            if "&" in ids[0]:
                assert text.count("&") == 1, f"access key lost in {text!r}"


@pytest.mark.parametrize("code", TRANSLATED)
def test_compiled_catalog_matches_the_source(code: str) -> None:
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
    # "0 selecionados": only exactly one is singular.
    compiled = gettext.translation(i18n.DOMAIN, i18n.LOCALE_DIR, ["pt_BR"])
    assert compiled.ngettext("{n} selected", "{n} selected", 0) == "{n} selecionados"
    assert compiled.ngettext("{n} selected", "{n} selected", 1) == "{n} selecionado"


def test_no_text_writes_a_key_a_person_can_change_into_its_words() -> None:
    fixed_keys = {
        "F1", "Esc", "Ctrl+F", "Tab", "Shift+Tab", "Ctrl+Tab", "Ctrl+Shift+Tab", "Ctrl+Shift+W",
    }  # fmt: skip
    anywhere = re.compile(r"(?<![\w+])(?:F\d{1,2}|(?:Ctrl|Alt|Shift)\+\S+)")
    at_end = re.compile(r"\((?:also )?(?:Enter|Del)\)$")

    def names_one(text: str) -> bool:
        keys = {key.rstrip(".,;:)") for key in anywhere.findall(text)}
        return bool(keys - fixed_keys) or at_end.search(text) is not None

    named = {text for _context, texts in _in_code() for text in texts if names_one(text)}
    fixed = {
        "Details (Enter)",
        # Import hosts' table, where F2 is Qt's own key to edit a cell: F2 anywhere else is caught.
        "Double-click a cell, or press F2, to change it; the list above follows. Right-click "
        "for more.",
        # The terminal's find field, whose Enter and Shift+Enter are its own.
        "Older match (Enter)",
        "Newer match (Shift+Enter)",
    }
    assert named == fixed
    old = "Reads the status, toner and page count of every printer shown. Nothing is read until"
    assert names_one(f"{old} you press it or F5.")
    assert names_one("Open Settings (Ctrl+,)") and names_one("Home (Ctrl+0)")
