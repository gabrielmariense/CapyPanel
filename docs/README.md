# CapyPanel documentation

Every computer you look after, in one window. CapyPanel is a Windows desktop app for IT staff:
keep the computers you look after in organized lists, see which ones are on and who is logged on
to them, and open a remote screen on any of them through Remote Desktop or the VNC viewer you
already use. It keeps your printers too, with the details you need and their web pages a click
away, and it finds the Windows user profiles nobody uses any more on a PC so you can delete them.

![CapyPanel's Home page: the tool rail, the capybara, and a tile each for Hosts, Printers and User profiles](images/home-dark.png)

## What it does

- Hosts
  - Remote connection: UltraVNC, RealVNC, Remote Desktop
  - Connection profiles
  - Accounts for other PCs, by PC, group or tag
  - Shared lists, groups and tags
  - Status, logged-on users, PC facts and mapped drives
  - Commands on a PC: its folders and consoles, its users, power and printers
  - Search, import and export
- Printers
  - Lists with brand, model, serial number and asset tag
  - Status, toner and supplies over SNMP, v2c or v3
  - Page counts from Doc360 MPS
  - Warnings when a printer needs attention
  - Web pages and reports
- User profiles
  - A PC's Windows profiles: who, when last used, how big
  - Which can be deleted, and why the others can't
  - Delete the ones you tick, on several PCs at once

## Pages

For people who use CapyPanel, and for people who set it up for a team.

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Running CapyPanel, the main window, adding hosts |
| [Settings and files](settings-and-files.md) | Every setting, and where CapyPanel keeps its files |
| [Host lists](hosts/host-lists.md) | Groups, tags, and the folders lists live in |
| [Importing and exporting hosts](hosts/importing.md) | Many hosts at once, in and out as CSV |
| [Connecting](hosts/connecting.md) | VNC viewers, Remote Desktop, connection profiles, accounts, passwords and the login check |
| [Checking hosts](hosts/checking.md) | Status, logged-on users, PC facts, and how CapyPanel reads other PCs |
| [Commands on a host](hosts/commands.md) | A PC's folders and consoles, its users, power, printers, programs and mapped drives |
| [Searching hosts](hosts/searching.md) | The search box, what it covers and how a search ends |
| [The Printers tool](printers/printers.md) | The Printers window, a printer's details, and web pages |
| [Checking printers](printers/checking.md) | Status, toner and supplies, and how they're read |
| [Printer lists](printers/printer-lists.md) | Where printer lists live, and their settings |
| [The User profiles tool](profiles/user-profiles.md) | A PC's Windows profiles, which can be deleted, and deleting them |
| [Development](development.md) | Building, testing and translating CapyPanel |

Getting started, Settings and files and Development are about the whole app. The six pages after
them belong to the **Hosts** tool, the three after those to **Printers**, and the last one to
**User profiles**.

These pages describe the current version (0.24.0). CapyPanel is in beta, so they grow with each
feature.
