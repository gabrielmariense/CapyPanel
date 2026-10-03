# CapyPanel

A Windows desktop app for IT staff: keep the computers on your network in one organized list,
and open a remote screen on any of them with the tools you already use.

- **Host lists** with nested groups, tags and notes. A list is a plain JSON file: keep a personal
  one, share one on a network folder, or publish a default list for everyone on the PC.
- **Remote screen (VNC)** through UltraVNC Viewer or RealVNC Viewer, opened with a double-click or
  Enter, for one host or many at once.
- **Connection profiles** say how each host is reached: which viewer, which login (user and
  password, or password only), and options such as UltraVNC's SecureVNC plugin. Set one on a
  group and every host inside follows it.
- **Passwords stay in memory**, one per profile, until CapyPanel closes. They're never saved, and
  never sent to a server that asks for a different kind of login.
- **English and Portuguese (Brazil)**, switched live. **Seven themes**, from native Windows to
  CapyPanel's own look.

Built for any organization: nothing is tied to one company's network, tools or language.

> **Status:** early development (version 0.9.0), working toward the first public alpha. It
> runs from source today; there's no installer yet.

## Documentation

- [Getting started](docs/getting-started.md): run CapyPanel and add your first hosts
- [Host lists](docs/host-lists.md): groups, tags, and default, personal and shared lists
- [Connecting](docs/connecting.md): VNC viewers, connection profiles and passwords
- [Settings and files](docs/settings-and-files.md): what each setting does, and where CapyPanel
  keeps its files
- [Development](docs/development.md): building, testing and translating

## Quick start (from source)

You need Windows 10 22H2 or 11 and [uv](https://docs.astral.sh/uv/), which installs Python and
everything else:

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

To open remote screens, install [UltraVNC](https://uvnc.com) or
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). CapyPanel launches them;
it never ships or downloads them.

## License

[GPL-3.0](LICENSE).
