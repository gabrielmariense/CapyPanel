from collections.abc import Iterator
from pathlib import Path

import pytest

from capypanel.core import i18n, settings


@pytest.fixture(autouse=True)
def english_after_each_test() -> Iterator[None]:
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)


def test_unknown_language_falls_back_to_english() -> None:
    assert i18n.set_language("xx_XX") == "en"
    assert i18n.language() == "en"


def test_strings_without_a_catalog_pass_through() -> None:
    i18n.set_language("pt_BR")
    assert i18n.language() == "pt_BR"
    assert i18n._("A text no catalog has") == "A text no catalog has"
    assert i18n.ngettext("{n} host", "{n} hosts", 2) == "{n} hosts"


def test_a_first_start_follows_the_language_windows_is_shown_in() -> None:
    assert i18n.language_for(0x0416) == "pt_BR"  # Portuguese (Brazil)
    assert i18n.language_for(0x0816) == "pt_BR"  # Portuguese (Portugal): the closest we have
    assert i18n.language_for(0x0409) == "en"  # English (United States)
    assert i18n.language_for(0x0C0A) == "en"  # Spanish: no catalog, so English
    assert i18n.windows_language() in i18n.LANGUAGES  # this PC's, whatever it is


def test_a_saved_choice_wins_over_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "windows_language", lambda: "pt_BR")
    saved = tmp_path / "settings.json"
    assert settings.language_of(saved) == "pt_BR"  # nothing saved yet: Windows'
    saved.write_text('{"language": "en"}', encoding="utf-8")
    assert settings.language_of(saved) == "en"  # the person's choice
