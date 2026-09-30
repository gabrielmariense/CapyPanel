# CapyPanel

A desktop app for IT staff to manage the computers on their network from one window:

- keep an organized list of hosts, in groups and with tags;
- open remote connections through the tools you already have (VNC, RDP, later SSH);
- see who is logged on;
- later, act on many hosts at once.

Built for any organization: nothing is tied to one company's network or language.

> **Status:** in development. The first alpha (0.1) is being built one feature at
> a time. Not ready for use yet.

## For developers

You need Windows 10 22H2 or 11 and [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 and everything else.

```
uv sync                     # install exactly the versions in uv.lock
uv run capypanel            # start the app
uv run pytest               # tests
uv run ruff check           # lint
uv run ruff format          # format
uv run pyright              # type check
uv run python scripts/translations.py   # after changing any text: update and compile translations
```

**Translations** live in `src/capypanel/locale/` (gettext). After changing a text, run the
script above, translate the new entries in each `.po` file, then run it again. The tests fail
until every text is translated and compiled.

**Portable mode:** an empty `capypanel.portable` file next to the app keeps
everything (settings, lists, logs) in a `userdata` folder beside it. When you run from source,
"next to the app" means the repository root.

**Layout:**
- `src/capypanel/core/` is the logic, and never imports a UI library (lint enforces it).
- `src/capypanel/ui/` is the Qt interface.
- `tests/` mirrors `src/`.

## License

[GPL-3.0](LICENSE).
