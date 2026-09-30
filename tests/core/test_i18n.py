from collections.abc import Iterator

import pytest

from capypanel.core import i18n


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
    assert i18n._("Ready") == "Ready"
    assert i18n.ngettext("{n} host", "{n} hosts", 2) == "{n} hosts"
