"""Messages the docs quote under Messages you may see are the app's words, in both languages."""

import re
from pathlib import Path
from typing import Literal

import pytest
from babel.messages.pofile import read_po

from capypanel.core import i18n

pytestmark = pytest.mark.docs_links
DOCS = Path(__file__).resolve().parents[2] / "docs"
LOCALE = Path(i18n.LOCALE_DIR)
HEADING = re.compile(r"^#+ (Messages you may see|Mensagens que você pode ver)\b.*$", re.M)
ANCHOR = re.compile(r'<a id="([^"]*)"></a>')
QUOTED = re.compile(r'"((?:[^"\\]|\\.)+)"')
FIELD = re.compile(r"\{[^{}]*\}")
GAP = "\x00"  # a part that varies: {name} or … in the docs, {name} in the app
WORD = re.compile(r"[^\W\d_]{2,}")
DATED = re.compile(r"[^\W\d_]+ \d+|\d[\d.,]* [^\W\d_]+")  # "October 2026", "12 GB"
SENTENCES = re.compile(r"(?<=[.!?])\s+")
LIST = re.compile(r",\s*|\s*\(|\)")  # "a (x), b (y)": a list the code puts together
SSH_EXE = "sshexe-"  # rows quoting ssh.exe, whose words are its own, in English
NOT_OURS = ("[SSL: CERTIFICATE_VERIFY_FAILED]", "unable to get local issuer certificate")
Mode = Literal["whole", "start", "part"]  # all of an app string, its start, or any part of it


def _value(run: str, named: bool) -> bool:
    """A name, number or date the docs put where the app has a placeholder: never a sentence.
    A name the app shows in “” may have spaces."""
    if GAP in run or len(run) > 40 or run.endswith((".", "!", "?")):
        return False
    return named or run.split() == [run] or DATED.fullmatch(run) is not None


class _Catalog:
    """One language's app strings, a GAP for each placeholder, and the quotes they explain."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(dict.fromkeys(FIELD.sub(GAP, t) for t in texts if t))
        self.words = [{w.lower() for w in WORD.findall(t)} for t in self.texts]
        self.known: dict[tuple[str, Mode, int], bool] = {}

    def candidates(self, quote: str) -> list[str]:
        """The strings with most of the quote's words, or the quote with most of theirs."""
        want = {w.lower() for w in WORD.findall(quote)}
        if not want:
            return self.texts
        found = []
        for text, words in zip(self.texts, self.words, strict=True):
            shared = len(want & words)
            if shared and (2 * shared >= len(want) or 10 * shared >= 7 * len(words)):
                found.append((shared, text))
        return [text for _shared, text in sorted(found, key=lambda pair: -pair[0])]

    def explains(self, quote: str, mode: Mode = "part", depth: int = 0) -> bool:
        """Whether app strings hold `quote` as `mode` says, their placeholders filled, or hold
        each of its sentences."""
        key = (quote, mode, depth)
        if key not in self.known:
            self.known[key] = any(
                self.matches(quote, text, mode, depth) for text in self.candidates(quote)
            ) or (
                len(parts := [p for p in SENTENCES.split(quote) if p]) > 1
                and all(self.explains(p, mode, depth) for p in parts)
            )
        return self.known[key]

    def fill(self, run: str, depth: int, named: bool, mode: Mode | None) -> bool:
        """A value, or app strings as `mode` says; None: one word only."""
        if mode is None:
            return run.split() == [run] and _value(run, False)
        if _value(run, named):
            return True
        if depth >= 2:
            return False
        if self.explains(run, mode, depth + 1):
            return True
        items = [p.strip() for p in LIST.split(run) if p.strip()]
        return len(items) > 1 and all(self.fill(p, depth + 1, False, "whole") for p in items)

    def matches(self, quote: str, text: str, mode: Mode, depth: int) -> bool:
        """A GAP in the quote takes any part of the text; one in the text takes a run of the
        quote that fill() accepts."""
        n, m = len(quote), len(text)
        todo = [(0, j) for j in (range(m) if mode == "part" else [0])]
        seen = set(todo)
        while todo:
            i, j = todo.pop()
            if i == n:
                if j == m or mode != "whole":
                    return True
                continue
            steps: list[tuple[int, int]] = []
            if quote[i] == GAP:
                steps += [(i + 1, j)] + ([(i, j + 1), (i + 1, j + 1)] if j < m else [])
            elif j < m and text[j] != GAP:
                steps += [(i + 1, j + 1)] if quote[i] == text[j] else []
            elif j < m:
                for k in range(i + 1, n + 1):
                    if k < n and j + 1 < m and quote[k] not in (GAP, text[j + 1]):
                        continue
                    held: Mode | None = "whole"
                    if i == 0 and j > 0 and mode == "part":
                        held = None  # the quote starts in this placeholder: one word
                    elif k == n and mode != "whole":
                        held = "start"  # it ends in it, maybe partway through a string
                    edges = quote[i - 1 : i] + quote[k : k + 1]
                    named = edges == text[j - 1 : j] + text[j + 1 : j + 2] == "“”"
                    if self.fill(quote[i:k], depth, named, held):
                        steps.append((k, j + 1))
            for step in steps:
                if step not in seen:
                    seen.add(step)
                    todo.append(step)
        return False


def _catalog(language: str) -> _Catalog:
    if language == "en":
        path, translated = LOCALE / f"{i18n.DOMAIN}.pot", False
    else:
        path, translated = LOCALE / "pt_BR" / "LC_MESSAGES" / f"{i18n.DOMAIN}.po", True
    with path.open("rb") as f:
        texts = []
        for message in read_po(f):
            values = message.string if translated else message.id
            texts += list(values) if isinstance(values, tuple | list) else [values]
    return _Catalog([str(t) for t in texts if t])


def _pattern(quote: str) -> str:
    words = quote.replace("\\|", "|").replace("\\*", "*").replace("…", GAP)
    for other in NOT_OURS:
        words = words.replace(other, GAP)
    return re.sub(r"\x00(?:\s*\x00)+", GAP, FIELD.sub(GAP, words))  # gaps side by side: one


def _quotes(language: str) -> list[tuple[str, str]]:
    """Each message quoted in a Messages you may see table's first column, with where it is."""
    found = []
    pages = sorted(DOCS.rglob("*.pt-BR.md" if language == "pt-BR" else "*.md"))
    for page in pages:
        if language == "en" and page.name.endswith(".pt-BR.md"):
            continue
        text = page.read_text(encoding="utf-8")
        heading = HEADING.search(text)
        if heading is None:
            continue
        first = text[: heading.end()].count("\n") + 2
        for number, line in enumerate(text[heading.end() :].splitlines()[1:], first):
            if line.startswith("#"):
                break
            if not line.startswith("|") or re.match(r"^\|\s*-", line):
                continue
            cell = re.split(r"(?<!\\)\|", line)[1]
            if any(place.startswith(SSH_EXE) for place in ANCHOR.findall(cell)):
                continue
            where = f"{page.relative_to(DOCS).as_posix()}:{number}"
            found += [(where, quote) for quote in QUOTED.findall(ANCHOR.sub("", cell))]
    return found


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_each_message_the_docs_quote_is_the_app_s_wording(language: str) -> None:
    catalog = _catalog(language)
    quotes = _quotes(language)
    assert len(quotes) > 50  # the tables were found
    stale = [
        f"{where}: {quote}" for where, quote in quotes if not catalog.explains(_pattern(quote))
    ]
    assert stale == []


def test_names_filled_in_pass_and_a_reworded_message_does_not() -> None:
    catalog = _Catalog(
        [
            "Couldn't {action} on {host}: {reason}",
            "log off {user}",
            "access denied. It needs an admin account on that PC.",
            "Already in the list, {place}",
            "in “{group}”",
            "⚠ From {month}: no counts yet. Check the portal.",
            "{n} files skipped: {files}",
            "can't be read",
            "made by another user",
            "CapyPanel {thing}",
            "Opened {n} web pages.",
            "Only the first {n} open at once.",
            "{host} refused the account {account}",
            "{host} didn't accept “{password}”. Type the password again, or use another account.",
            "Couldn't reach GitHub: {reason}",
        ]
    )
    kept = [
        "Couldn't log off bruno on DESK-02: access denied. It needs an admin account on that PC.",
        "Couldn't … on DESK-02: access denied.",
        "Already in the list, in “Front desk”",
        "⚠ From October 2026: no counts yet.",
        "2 files skipped: broken.json (can't be read), clinics.json (made by another user)",
        "It needs an admin account",
        "Opened 12 web pages. Only the first 10 open at once.",
        "{host} refused the account {account}",
        "Couldn't reach GitHub: [SSL: CERTIFICATE_VERIFY_FAILED] … unable to get local issuer "
        "certificate",
    ]
    reworded = [
        "Couldn't sign out bruno on DESK-02: access denied.",
        "Couldn't log off bruno on DESK-02: access denied. It needs an administrator account.",
        "Couldn't log off bruno on DESK-02 now: access denied.",
        "Already in the list, under “Front desk”",
        "⚠ Since October 2026: no counts yet.",
        "2 files skipped: broken.json (cannot be read)",
        "CapyPanel is already running, but its window can't be brought forward: …",
        "Showed 10 web pages.",
        "{host} rejected the account {account}",
    ]
    assert [q for q in kept if not catalog.explains(_pattern(q))] == []
    assert [q for q in reworded if catalog.explains(_pattern(q))] == []
