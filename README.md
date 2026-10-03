<h1 align="center">CapyPanel</h1>

<p align="center">
  <a href="README.md"><img src="https://flagcdn.com/40x30/us.png" width="40" height="30" alt="English" title="English"></a>
  &nbsp;
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/40x30/br.png" width="40" height="30" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

CapyPanel puts every computer you look after in one window. It's a Windows desktop app for IT
staff: keep your hosts in organized lists, and open a remote screen on any of them with the VNC
viewer you already use.

Built for any organization: nothing is tied to one company's network, tools or language.

> **Status: alpha (0.10.0).** Usable today, and growing one feature at a time. It runs from
> source; there's no installer yet.

## Features

### Released

- Remote screen (UltraVNC, RealVNC)
- Connection profiles
- Shared host lists

### In development

- Remote Desktop (RDP)
- Logged-on users

### Planned

- SSH
- Search and status
- Actions on hosts

## Documentation

Also online, with search: **[gabrielmariense.github.io/CapyPanel](https://gabrielmariense.github.io/CapyPanel/)**.

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
