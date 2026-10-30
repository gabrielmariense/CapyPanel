<h1 align="center">
  <img src="docs/images/capypanel-icon.png" width="96" height="96" alt=""><br>
  CapyPanel
</h1>

<p align="center">Every computer you look after, in one window.</p>

<p align="center">
  <a href="README.md"><img src="https://flagcdn.com/40x30/us.png" width="40" height="30" alt="English" title="English"></a>
  &nbsp;
  <a href="README.pt-BR.md"><img src="https://flagcdn.com/40x30/br.png" width="40" height="30" alt="Português (Brasil)" title="Português (Brasil)"></a>
</p>

CapyPanel is a Windows desktop app for IT staff: keep the computers you look after in organized
lists, see which ones are on and who is logged on to them, and open a remote screen on any of
them through Remote Desktop or the VNC viewer you already use. It keeps your printers too, with
the details you need and their web pages a click away.

> **Status: beta (0.21.0).** It runs from source; there's no installer yet.

![CapyPanel's Home page: the tool rail, the capybara, and a tile for Hosts and one for Printers](docs/images/home-dark.png)

## What it does

- Hosts
  - Remote connection: UltraVNC, RealVNC, Remote Desktop
  - Connection profiles
  - Shared lists, groups and tags
  - Status and logged-on users
  - Search, import and export
- Printers
  - Lists with brand, model, serial number and asset tag
  - Status, toner and supplies over SNMP
  - Web pages and reports

## Documentation

Also online, with search: **[gabrielmariense.github.io/CapyPanel](https://gabrielmariense.github.io/CapyPanel/)**.

- [Getting started](docs/getting-started.md): run CapyPanel and add your first hosts
- [Settings and files](docs/settings-and-files.md): what each setting does, and where CapyPanel
  keeps its files
- [Host lists](docs/hosts/host-lists.md): groups, tags, and the lists folders
- [Importing and exporting hosts](docs/hosts/importing.md): many hosts at once, in and out as CSV
- [Connecting](docs/hosts/connecting.md): VNC viewers, Remote Desktop, connection profiles and
  passwords
- [Checking hosts](docs/hosts/checking.md): status and logged-on users
- [Searching hosts](docs/hosts/searching.md): finding a host anywhere in the list
- [The Printers tool](docs/printers/printers.md): printers, their details and their web pages
- [Checking printers](docs/printers/checking.md): status, toner and supplies over SNMP
- [Printer lists](docs/printers/printer-lists.md): where printer lists live, and their settings
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

Icons: [Tabler Icons](https://tabler.io/icons) (MIT), notice in
`src/capypanel/ui/tabler/LICENSE`.
