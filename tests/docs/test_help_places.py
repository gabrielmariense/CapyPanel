import re
from pathlib import Path

import pytest

from capypanel.ui import help_links

pytestmark = pytest.mark.docs_links
DOCS = Path(__file__).resolve().parents[2] / "docs"
ANCHOR = re.compile(r'<a id="([^"]+)"></a>')
LANGUAGES = ("en", "pt-BR")


def _source(page: str, language: str) -> Path:
    name = page.rstrip("/") or "README"
    return DOCS / f"{name}{'.pt-BR' if language == 'pt-BR' else ''}.md"


def _ids(path: Path) -> list[str]:
    return ANCHOR.findall(path.read_text(encoding="utf-8"))


def _pages() -> list[Path]:
    return sorted(p for p in DOCS.rglob("*.md") if not p.name.endswith(".pt-BR.md"))


def test_every_place_the_app_opens_is_on_its_page_in_both_languages() -> None:
    missing = []
    for place, page in help_links.PLACES.items():
        for language in LANGUAGES:
            path = _source(page, language)
            if not path.exists() or place not in _ids(path):
                missing.append(f"{place} on {path.relative_to(DOCS)}")
    for page in help_links.TOPS:
        missing += [
            str(_source(page, language).relative_to(DOCS))
            for language in LANGUAGES
            if not _source(page, language).exists()
        ]
    assert missing == []


def test_a_page_carries_the_same_ids_in_both_languages() -> None:
    differ = []
    for english in _pages():
        portuguese = english.with_name(english.stem + ".pt-BR.md")
        if portuguese.exists() and sorted(_ids(english)) != sorted(_ids(portuguese)):
            only = set(_ids(english)) ^ set(_ids(portuguese))
            differ.append(f"{english.relative_to(DOCS)}: {sorted(only)}")
    assert differ == []


def test_an_id_is_used_once_across_the_site() -> None:
    seen: dict[str, str] = {}
    twice = []
    for english in _pages():
        for place in _ids(english):
            if place in seen:
                twice.append(f"{place}: {seen[place]} and {english.relative_to(DOCS)}")
            seen[place] = str(english.relative_to(DOCS))
    assert twice == []


def test_every_messages_row_has_an_id() -> None:
    bare = []
    for path in sorted(DOCS.rglob("*.md")):
        in_messages, row_before = False, False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("## "):
                in_messages = "messages-you-may-see" in line
            is_row = line.startswith("|")
            header = is_row and not row_before
            rule = is_row and set(line) <= set("|-: ")
            if in_messages and is_row and not header and not rule:
                first = line.split("|")[1]
                if not ANCHOR.search(first):
                    bare.append(f"{path.relative_to(DOCS)}:{number}")
            row_before = is_row
    assert bare == []
