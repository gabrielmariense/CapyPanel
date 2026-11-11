# Settings and files

Settings is the gear at the bottom of the rail, and **File > Settings…** (Ctrl+,). **Every choice
applies as soon as you make it.** There is no Save button and no Close button: the window's **×**
or **Esc** closes it, and nothing ever asks you about unsaved changes.

![Settings on CapyPanel > General: the page list on the left, Appearance and Startup and closing on the right](images/settings-dark.png)

## How the window works

Down the left are a **Search settings** box and the list of pages, grouped: **CapyPanel** first,
then one group per tool that has settings, **Hosts** and **Printers**. **About** sits on its own at
the very bottom, below the groups.

| Group | Pages |
|---|---|
| **CapyPanel** | General |
| **Hosts** | General, Connecting, Credentials |
| **Printers** | General, Warnings and supplies, Connecting |

A click on a page shows that page alone. Settings opens on **CapyPanel > General**.

Each page is made of sections: a title with its settings on a soft card under it. A simple setting
is a row: its name, a one-line description under it, and its control at the right end. Anything
that holds several things, from host lists to licenses, is the same table everywhere: grid lines, a
header, six rows before it scrolls, the main actions as buttons under it, **every action for a row
on its right-click**, and a double-click for the obvious one. Every column shows its whole text,
and when they can't all fit, the table scrolls sideways; right-click the column titles for **Fit
columns to content**. The window opens at a fixed size, and a page taller than it scrolls.

### Searching the settings

Type three letters or more and the right side shows every section that mentions them, from every
page, each under where it lives, as in "Hosts › Connecting", with the matching words marked in
yellow. Words are matched from their start. The page list keeps only the pages with a match. The
settings work there, so you can change what you were looking for without going to its page. A
dropdown whose match is one of its choices, not the one showing, gets the mark on its arrow.
Clearing the box puts everything back, on the page you were on.

## CapyPanel > General

**Appearance > Theme:** "Windows themes follow Windows' look and accent; CapyPanel themes look the
same everywhere."

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

**Appearance > Language** is English or Português (Brasil). "The app's language. Changes at
once.", and that includes the Settings window itself, with no restart.

**Startup and closing > Open on startup** is what the window shows when CapyPanel starts: the
**Home page**, **The last used tool**, or a tool by name.

**Startup and closing > When closing** is what the window's **✕** does: **Ask each time**, the
default, **Keep running in the tray**, or **Quit**. "What the window's ✕ does. In the tray, Refresh
on its own and warnings keep working." See
[Getting started](getting-started.md#closing-capypanel-and-the-tray).

## Hosts > General

### Host lists

The table of every list CapyPanel found or you added, with what you can do to each, and the buttons
that make, add and remove them. The list dropdown over the Groups panel opens it through **Manage
host lists…**. [Host lists](hosts/host-lists.md#settings-hosts-general-host-lists) describes the table, the
buttons and what **Remove** asks.

Under it, two rows:

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

## Hosts > Connecting

![Settings > Hosts > Connecting: the connection profiles, the remote tools, and Read PC data with](images/settings-hosts-connecting-dark.png)

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

The section ends with **Read PC data with**: how CapyPanel reads the PC facts, installed
programs, mapped drives and user profiles of other PCs. **Automatic (recommended)**, **WMI
directly** or **WMI through PowerShell**; with Automatic, "in use:" beside it names the way it uses
on this PC. Like the
tools' paths, it's set once for everyone on this PC. Leave it on Automatic unless
[How CapyPanel reads other PCs](hosts/checking.md#how-capypanel-reads-other-pcs) gives you a
reason to pin one.

## Hosts > Credentials

![Settings > Hosts > Credentials: the Accounts table, and Saved credentials under Passwords](images/settings-hosts-credentials-dark.png)

**Accounts** is the table **Account | Used for | Kept in**, with **Add…**, **Edit…** and
**Remove**: which account signs in to which PCs, for Refresh's logged-on users and the commands
you run on a host. It's yours only, "kept in your own settings, never in the shared host lists".
[Connecting](hosts/connecting.md#accounts-for-other-pcs) explains how a PC finds its account.

**Passwords > Saved credentials** says how many logins CapyPanel keeps and where, as in "2 kept: 1
in Credential Manager, 1 temporary.", with **Manage…** to open the window that lists them (see
[Connecting](hosts/connecting.md#saved-credentials)).

## Printers

**Printers > General** holds **Printer lists**, the same table and buttons as Host lists, with
**List on startup** and **Show first** under it, working as they do for Hosts. They're under
[Printer lists](printers/printer-lists.md#settings).

**Printers > Warnings and supplies** holds **Refresh**: **Refresh on its own** and the **Windows
notification** about printers that need attention; and **Supplies**: the **Low supply level**
between 1 and 50 %, the **Bar marks** on the supply bars, and whether the **Toner column** shows
text or a bar.

**Printers > Connecting** holds **SNMP**: the **SNMP version**, v2c or v3, and the **SNMP account**
for it behind a **Change…** button; and **Doc360 MPS**: the **Doc360 MPS account** behind another
one, for printers whose page counters come from that portal.

[Checking printers](printers/checking.md) explains all of them. The User profiles tool has no
settings of its own: it uses Hosts' lists and Hosts' accounts.

## About

**Help > About CapyPanel** opens this page, pinned at the bottom of the list. Four cards:

| Card | What it holds |
|---|---|
| **CapyPanel** | The mascot, the name and the version (click it to copy it with its commit), "Every computer you look after, in one window.", the copyright and "Free software under the GPL-3.0, with no warranty: see Licenses.", which scrolls down to them, links to the documentation and the source code, a **Build** line with the commit and portable mode where they apply, and **Report a problem** beside **Open log folder** |
| **Credits** | Who made CapyPanel, its mascot, and the icons it uses |
| **Licenses** | The table **Software \| Version \| License \| Notice**: CapyPanel (GPL-3.0), Qt and Qt for Python (LGPL-3.0), Python (PSF License), cryptography (BSD-3-Clause, and the OpenSSL license, Apache-2.0, in the same notice, because its Windows build carries OpenSSL), cffi (MIT-0) and pycparser (BSD-3-Clause), which cryptography needs, pywin32 (BSD-3-Clause), which CapyPanel reads other PCs through, and Tabler Icons (MIT). **Read license** opens the shipped text in a window, also on a double-click or the row's right-click, and **Open folder** opens the folder they all ship in |
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
| Viewer definitions added by your company, where each viewer is installed, and how other PCs are read | `tools\` |
| Your settings, your accounts for other PCs among them | `users\<you@DOMAIN>\` |
| Your own lists, a folder per kind | `users\<you@DOMAIN>\lists\hosts\`, `…\lists\printers\` |
| Logs, one file per user | `logs\<you@DOMAIN>.log` |
| Every user profile you deleted, or tried to | `logs\<you@DOMAIN>.user-profiles.log` |
| Built-in viewer definitions, and the starter profiles | Inside the app |

- **Your folder is private:** only you, administrators and Windows itself can open it.
  CapyPanel refuses to use a folder someone else created first in your name.
- **Shared files must come from someone trusted.** Any user can add files to ProgramData, so
  CapyPanel ignores a shared file (a list, a profile, a company viewer definition) made by
  another user who isn't an administrator, and logs it.
- **Logs never contain passwords.** They record which viewer started for which address, the
  result of each login check, and, at each start, which way CapyPanel reads other PCs. The user
  profiles log keeps, for each delete, when, on which PC, whose profile and how it ended.

CapyPanel makes these folders at its first start. Lists from an earlier version are copied into
them once, by themselves: the `hosts.json` files of before 0.19, and the lists that 0.19 kept
directly in `lists\`. The older files are left where they are, so an older version still runs.

### Portable mode

An empty file named `capypanel.portable` next to the app keeps everything (settings, lists,
logs) in a `userdata` folder beside it instead, for running from a USB stick or a shared folder.
When you run from source, "next to the app" means the repository folder.
