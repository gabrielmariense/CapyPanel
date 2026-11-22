import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRAGMA = re.compile(r"#\s*(noqa|type:|pyright:|pragma:|fmt:|ruff:|i18n:|isort:|nosec)")
# Versions aren't checked: one stays where the code still reads that version's data.
HISTORY = re.compile(
    r"\b(Gabriel|Luna|Debora|Lisa|Alice|Kerrigan|Satya|Dante)\b"
    r"|\b20\d\d-\d\d-\d\d\b|(?i:\bbuild \d+\b)"
)


def _sources() -> list[Path]:
    found = [
        p
        for folder in ("src", "tests", "scripts", "packaging")
        for p in (ROOT / folder).rglob("*.py")
    ]
    found.append(ROOT / "packaging" / "capypanel.spec")
    return sorted(p for p in found if "vendor" not in p.relative_to(ROOT).parts)


def problems(name: str, source: str) -> list[str]:
    found: list[str] = []
    lines = source.splitlines()
    blocks: list[tuple[int, int]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT or PRAGMA.search(token.string):
            continue
        row, column = token.start
        found += [
            f"{name}:{row}: {m.group(0)!r} in a comment" for m in HISTORY.finditer(token.string)
        ]
        if token.string.startswith("#!") or lines[row - 1][:column].strip():
            continue
        if blocks and blocks[-1][1] == row - 1:
            blocks[-1] = (blocks[-1][0], row)
        else:
            blocks.append((row, row))
    found += [
        f"{name}:{a}-{b}: {b - a + 1} comment lines in a row" for a, b in blocks if b - a >= 2
    ]
    tree = ast.parse(source, name)
    first = tree.body[0] if tree.body else None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name.startswith("test")
            and ast.get_docstring(node) is not None
        ):
            found.append(f"{name}:{node.lineno}: a test with a docstring")
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            text = node.value.value
            if not isinstance(text, str):
                continue
            count = sum(1 for line in text.splitlines() if line.strip())
            if count > (1 if node is first else 2):
                kind = "file docstring" if node is first else "docstring"
                found.append(f"{name}:{node.lineno}: a {kind} of {count} lines")
            found += [
                f"{name}:{node.lineno}: {m.group(0)!r} in a docstring"
                for m in HISTORY.finditer(text)
            ]
    return found


def test_every_comment_and_docstring_keeps_the_rule() -> None:
    paths = _sources()
    assert Path(__file__).resolve() in paths
    found = []
    for path in paths:
        found += problems(path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8"))
    assert found == []


def test_the_check_finds_each_kind_of_problem() -> None:
    source = (
        '"""What it is for,\nas Luna asked."""\n'
        "# one\n# two\n# three\n"
        "x = 1  # since 2026-11-20, Gabriel's, Build 698\n"
        "# type: ignore\n# two lines\n# at most\n"
        "y = 2  # 0.19's lists are still read\n"
        'def f():\n    """Two lines\n    at most."""\n'
        'def g():\n    """One,\n    two,\n    three."""\n'
        'def test_f():\n    """A test has none."""\n'
    )
    assert problems("f.py", source) == [
        "f.py:6: '2026-11-20' in a comment",
        "f.py:6: 'Gabriel' in a comment",
        "f.py:6: 'Build 698' in a comment",
        "f.py:3-5: 3 comment lines in a row",
        "f.py:1: a file docstring of 2 lines",
        "f.py:1: 'Luna' in a docstring",
        "f.py:18: a test with a docstring",
        "f.py:15: a docstring of 3 lines",
    ]
