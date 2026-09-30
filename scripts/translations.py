"""Update the translations after changing any text in the app:

    uv run python scripts/translations.py

1. extract: collects every _() / ngettext() / N_() text from the code into capypanel.pot;
2. update: merges new and changed texts into each language's .po file (for translators);
3. compile: builds the .mo files the app reads.
Then translate the new entries in the .po files and run it again."""

import sys
from pathlib import Path

from babel.messages.frontend import CommandLineInterface

from capypanel.core.i18n import DEFAULT_LANGUAGE, LANGUAGES

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "capypanel"
LOCALE = PACKAGE / "locale"
TEMPLATE = LOCALE / "capypanel.pot"


def pybabel(*args: str) -> None:
    CommandLineInterface().run(["pybabel", "-q", *args])


def main() -> int:
    LOCALE.mkdir(exist_ok=True)
    # No line numbers in the files: they'd change on every edit and bury real changes in diffs.
    pybabel(
        "extract", "--no-location", "--sort-output", "--project=CapyPanel",
        "--add-comments=i18n:", "-o", str(TEMPLATE), str(PACKAGE),
    )  # fmt: skip
    for code in LANGUAGES:
        if code != DEFAULT_LANGUAGE and not (LOCALE / code).exists():
            pybabel("init", "-i", str(TEMPLATE), "-d", str(LOCALE), "-D", "capypanel", "-l", code)
    pybabel(
        "update",
        "-i",
        str(TEMPLATE),
        "-d",
        str(LOCALE),
        "-D",
        "capypanel",
        "--no-wrap",
        "--ignore-obsolete",
    )
    pybabel("compile", "-d", str(LOCALE), "-D", "capypanel", "--statistics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
