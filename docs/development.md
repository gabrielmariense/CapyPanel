# Development

## Setup

You need Windows 10 22H2 or 11 and [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 and
every dependency at the exact versions in `uv.lock`.

```
uv sync                     # install exactly the versions in uv.lock
uv run capypanel            # start the app
uv run pytest               # tests
uv run ruff check           # lint
uv run ruff format          # format
uv run pyright              # type check
```

Every pull request runs the same checks on Windows in CI, and `main` only accepts changes that
pass them.

## Layout

| Folder | What's in it |
|---|---|
| `src/capypanel/core/` | The logic. It never imports a UI library (lint enforces it) |
| `src/capypanel/ui/` | The Qt (PySide6) interface |
| `src/capypanel/core/tools/presets/` | Built-in viewer definitions and connection profiles (JSON) |
| `src/capypanel/locale/` | Translations |
| `tests/` | Mirrors `src/` |

## Translations

Texts are translated with gettext. After changing or adding a text:

```
uv run python scripts/translations.py
```

Then translate the new entries in each `.po` file under `src/capypanel/locale/` and run the
script again to compile them. The tests fail until every text is translated and compiled.

## Versions

Versions are `0.MINOR.PATCH` until 1.0: a merged feature bumps MINOR, a fix-only change bumps
PATCH. Running from source, the title bar adds the commit to the version.
