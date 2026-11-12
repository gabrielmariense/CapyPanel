# Contributing to CapyPanel

How to build, test and translate CapyPanel. Em português: [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md).

## Setup

You need Windows 10 22H2 or 11 and [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 and
every dependency at the exact versions in `uv.lock`.

```
uv sync                     # install exactly the versions in uv.lock
uv run capypanel            # start the app
uv run pytest -n auto --dist loadgroup   # tests, spread over every CPU core, as CI runs them
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
| `src/capypanel/core/tools/presets/` | Viewer definitions and the starter profiles (JSON) |
| `src/capypanel/locale/` | Translations |
| `tests/` | Mirrors `src/` |

## Translations

Texts are translated with gettext. After changing or adding a text:

```
uv run python scripts/translations.py
```

Then translate the new entries in each `.po` file under `src/capypanel/locale/` and run the
script again to compile them. The tests fail until every text is translated and compiled.

## Reading a real printer

Before trusting what the window shows, you can ask one printer the same questions from a terminal:

```
uv run python scripts/read_printer.py 192.0.2.5
```

It asks for the community string without showing it, reads over SNMP (reading only) and prints
what CapyPanel understood, the MAC address and the firmware version included. `--public` uses
"public" without asking; `--v3` reads over SNMP v3 instead, asking for the user and the
authentication and encryption types and passwords, without showing the passwords;
`--brand-data` also prints the Ricoh or Brother data area as raw numbers; and `--firmware` prints
every standard place a printer may keep its firmware version, one per line, for finding which one
matches the version on the printer's own web page. The serial number is
printed only as its length, and the MAC address only as its maker's half, so the output is safe
to paste into an issue.

## Documentation website

The pages in `docs/` are also published as a website with
[MkDocs Material](https://squidfunk.github.io/mkdocs-material/), each time they change on
`main`. Each English page (`name.md`) has its Portuguese version beside it
(`name.pt-BR.md`); change both together. Pages about the whole app sit in `docs/`, and a tool's
own pages in a folder of its own: `docs/hosts/`, `docs/printers/` and `docs/profiles/`. Each page
opens with its tasks as short numbered steps, folds the details into `??? note` boxes, and ends
with a "Messages you may see" table. To preview the site while writing:

```
uv run --only-group docs mkdocs serve
```

## Versions

Versions are `0.MINOR.PATCH` until 1.0: a merged feature bumps MINOR, a fix-only change bumps
PATCH. Running from source, the title bar adds a build number and the commit to the version, as
in `0.25.0 build 1378 (abc1234)`. The build number counts every commit that led to it, so a
bigger number is always a newer build. The version itself comes from the checkout's own
`pyproject.toml`, so it's right straight after a pull, even before `uv sync`.
