<h1 align="center">CapyPanel</h1>

<p align="center">
  <a href="README.md"><img src="https://flagcdn.com/40x30/us.png" width="40" height="30" alt="English" title="English"></a>
  &nbsp;
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/40x30/br.png" width="40" height="30" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

CapyPanel puts every computer you look after in one window. It's a Windows desktop app for IT
staff: keep your hosts in organized lists, and open a remote screen on any of them through Remote
Desktop or the VNC viewer you already use.

> **Status: beta (0.12.1).** It runs from source; there's no installer yet.

## Features

### Released

- Remote screen (UltraVNC, RealVNC)
- Remote Desktop (RDP)
- Connection profiles
- Shared host lists

### In development

- Logged-on users

### Planned

- SSH
- Search and status
- Actions on hosts

## Documentation

Also online, with search: **[gabrielmariense.github.io/CapyPanel](https://gabrielmariense.github.io/CapyPanel/)**.

- [Getting started](docs/getting-started.md): run CapyPanel and add your first hosts
- [Host lists](docs/host-lists.md): groups, tags, and default, personal and shared lists
- [Connecting](docs/connecting.md): VNC viewers, Remote Desktop, connection profiles and passwords
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

Remote Desktop uses the client built into Windows. For VNC, install [UltraVNC](https://uvnc.com)
or [RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/).

## License

[GPL-3.0](LICENSE).
