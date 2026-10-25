# Settings and files

Settings is the gear at the bottom of the rail, and **File > Settings…** (Ctrl+,). **Every choice
applies as soon as you make it.** There is no Save button and no Close button: the window's **×**
or **Esc** closes it, and nothing ever asks you about unsaved changes.

## How the window works

Down the left are a **Search settings** box and a list of everything Settings holds, grouped:
**CapyPanel** first, then one group per tool, **Hosts** and **Printers**. Under each group name are
its sections, indented. **About** sits on its own at the very bottom, below the groups.

| Group | Sections |
|---|---|
| **CapyPanel** | Startup, Language, Theme |
| **Hosts** | Startup, Refresh, Host lists, Connection profiles, Remote tools |
| **Printers** | Startup, Printer lists |

A group is one long page. Clicking a section in the list scrolls the page to it, and as you scroll,
the list follows and highlights where you are. Settings opens on **CapyPanel > Startup**.

Each section is a title with its settings on a soft card under it. A simple setting is a row: its
name, a one-line description under it, and its control at the right end. Anything that holds
several things, from host lists to licenses, is the same table everywhere: grid lines, a header,
six rows before it scrolls, the main actions as buttons under it, **every action for a row on its
right-click**, and a double-click for the obvious one. The window opens at a fixed size, and a page
taller than it scrolls.

### Searching the settings

Type three letters or more and the right side shows every section that mentions them, from every
group, each under the name of the group it came from, with the matching words marked in yellow.
Words are matched from their start. The settings work there, so you can change what you were
looking for without going to its group. A dropdown whose match is one of its choices, not the one
showing, gets the mark on its arrow. Clicking a group, or clearing the box, puts everything back.

## CapyPanel

**Startup > Open on startup** is what the window shows when CapyPanel starts: the **Home page**,
**The last used tool**, or a tool by name.

**Language** is English or Português (Brasil). "The app's language. Changes at once.", and that
includes the Settings window itself, with no restart.

**Theme:** "Windows themes follow Windows' look and accent; CapyPanel themes look the same
everywhere."

| Theme | Look |
|---|---|
| Windows — follow system theme / dark / light | Native Windows styling, with your accent color |
| CapyPanel — dark / light | CapyPanel's own look, the same on every computer |
| Graphite, Paper | Two more of CapyPanel's own looks |

Themes change colors only. The font, its size and the rounded corners are the same in every one,
and a theme never changes what the app does.

The Windows themes follow your Windows accent color (**Settings > Personalization > Colors**), and
everything built from it stays readable whichever one you pick: section headings, the default
button, highlights, and the Groups heading when you drag a group onto it. CapyPanel's own looks
keep their own accents instead, the same on every computer.

## Hosts

### Startup

- **List on startup:** which host list opens with the tool. "If that list can't be opened: the
  default list, then your personal list."
- **Show first:** what the open list shows when it opens (see
  [Host lists](hosts/host-lists.md#what-a-list-shows-first)). "For the list open now; each list
  keeps its own."

### Refresh

**Refresh status by itself** is one dropdown: **Off**, **Every minute**, **Every 5 minutes**,
**Every 15 minutes**, **Every 30 minutes**, or **Custom…**, which asks for anything from 1 to 120
minutes and then shows that interval among the choices. Turning it **Off** keeps the interval for
next time.

"Only ping and ports, never logged-on users, so no account is needed. Refresh in the toolbar always
works." It's off until you turn it on; see [Checking hosts](hosts/checking.md#automatic-status).

### Host lists

The table of every list CapyPanel found or you added, with what you can do to each, and the buttons
that make, add and remove them. The list dropdown over the Groups panel opens it through **Manage
host lists…**. [Host lists](hosts/host-lists.md#settings-hosts-host-lists) describes the table, the
buttons and what **Remove** asks.

### Connection profiles

The table **Profile | Tool | Signs in with**, with **Add…**, **Edit…**, **Delete…** and **Restore
built-in…** under it; a row's right-click adds **Duplicate…**, and a double-click edits. Remote
Desktop's sign-in reads "asked by Remote Desktop Connection itself", because CapyPanel asks for
nothing: the Remote Desktop client asks for the user and the password when it connects. What a
profile is made of is under [Connecting](hosts/connecting.md#managing-profiles).

**Restore built-in…** brings back the profiles CapyPanel ships with, and is greyed while none is
missing. It asks first, naming them: "Bring back 2 built-in profiles: RealVNC, Remote Desktop?",
and adds "Profiles you changed or made yourself stay as they are." Cancel is the default button.

"Shared by everyone on this PC." Changes are written for everyone the moment you make them, and
**Delete…** asks first. Where Windows doesn't let you write the folder, the note adds that it's
read-only, and only people it does let write can change them.

**Hosts with no profile use** is the last row of the section: "The profile a host connects with
when it has none of its own."

CapyPanel fills the profiles folder at its first start with the profiles it ships (RealVNC, Remote
Desktop and UltraVNC) and a settings file, `_profiles.json`, which records that row's choice and
which shipped profiles have been added already. Where the folder couldn't be created, the page
shows the built-in profiles and says so: "These are the built-in profiles: the folder is created
when you change one.", or "…the folder isn't there yet." where you can't create it at all.

### Remote tools

The table **Tool | Status | Where**: **✓ Found** when CapyPanel found it by itself, **✓ Your
choice** when a path was set here, or **✗ Not found**, whose tooltip says "Install it, or locate
its .exe."

- **Change path…** picks a tool's `.exe`, a portable copy for instance. A row's right-click then
  also offers **Use the automatic path**, which forgets that choice.
- **Download** opens the tool's website, and is there only for a tool that wasn't found. Remote
  Desktop Connection is built into Windows, so it has none.

"Where each tool is installed, set once for everyone on this PC." Like profiles, it's written at
once, and only where Windows lets you write the folder.

Under both tables, a line names the files CapyPanel isn't using and why, such as "2 files skipped:
broken.json (can't be read), clinics.json (made by another user)". Hover it for the full paths and
the errors; it's hidden when every file is in use.

## Printers

**Startup > List on startup** and **Show first** work as they do for Hosts, for printer lists.
**Printer lists** is the same table and the same buttons as Host lists. Both are under
[Printer lists](printers/printer-lists.md#settings).

## About

**Help > About CapyPanel** opens this page, pinned at the bottom of the list. Four cards:

| Card | What it holds |
|---|---|
| **CapyPanel** | The mascot, the name and the version (click it to copy it with its commit), "Every computer you look after, in one window.", the copyright and "Free software under the GPL-3.0, with no warranty: see Licenses.", which scrolls down to them, links to the documentation and the source code, a **Build** line with the commit and portable mode where they apply, and **Report a problem** beside **Open log folder** |
| **Credits** | Who made CapyPanel, its mascot, and the icons it uses |
| **Licenses** | The table **Software \| Version \| License \| Notice**: CapyPanel (GPL-3.0), Qt and Qt for Python (LGPL-3.0), Python (PSF License), Tabler Icons (MIT). **Read license** opens the shipped text in a window, also on a double-click or the row's right-click, and **Open folder** opens the folder they all ship in |
| **Folders** | Where CapyPanel keeps everything, three rows and an **Open folder** button |

The **Folders** table is the short version of the section below:

| Folder | What it holds |
|---|---|
| **Shared** | "For everyone on this PC: connection profiles, remote tools, and the shared lists in “lists”, a folder for each kind of list." |
| **Personal** | "Only for you and administrators: your settings, and your lists in “lists”, a folder for each kind of list." |
| **Logs** | "One per user, named after the account." |

Hover a folder to see what it holds, as the table says under itself. In portable mode it adds
"Portable mode: everything stays in the app's own folder." The paths are there to read, not to
select.

## Where CapyPanel keeps its files

CapyPanel keeps everything for all users of a PC in one folder, `C:\ProgramData\CapyPanel`,
with one private folder per user:

| What | Where |
|---|---|
| Lists shared with everyone on the PC, a folder per kind | `lists\hosts\`, `lists\printers\` |
| Connection profiles, their settings files, and which one hosts fall back to | `profiles\` |
| Viewer definitions added by your company, and where each viewer is installed | `tools\` |
| Your settings | `users\<you@DOMAIN>\` |
| Your own lists, a folder per kind | `users\<you@DOMAIN>\lists\hosts\`, `…\lists\printers\` |
| Logs, one file per user | `logs\` |
| Built-in viewer definitions, and the starter profiles | Inside the app |

- **Your folder is private:** only you, administrators and Windows itself can open it.
  CapyPanel refuses to use a folder someone else created first in your name.
- **Shared files must come from someone trusted.** Any user can add files to ProgramData, so
  CapyPanel ignores a shared file (a list, a profile, a company viewer definition) made by
  another user who isn't an administrator, and logs it.
- **Logs never contain passwords.** They record which viewer started for which address, and the
  result of each login check.

CapyPanel makes these folders at its first start. Lists from an earlier version are copied into
them once, by themselves: the `hosts.json` files of before 0.19, and the lists that 0.19 kept
directly in `lists\`. The older files are left where they are, so an older version still runs.

### Portable mode

An empty file named `capypanel.portable` next to the app keeps everything (settings, lists,
logs) in a `userdata` folder beside it instead, for running from a USB stick or a shared folder.
When you run from source, "next to the app" means the repository folder.
