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
```

**Portable mode:** an empty `capypanel.portable` file next to the app keeps
settings and logs in a `userdata` folder beside it. When you run from source,
"next to the app" means the repository root.

Design decisions and the rules every feature follows: [`DECISIONS.md`](DECISIONS.md).

## License

[GPL-3.0](LICENSE).
