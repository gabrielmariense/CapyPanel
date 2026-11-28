# Settings and files

Settings is the gear at the bottom of the sidebar, and **File > Settings…** (Ctrl+,). **Every choice
applies as soon as you make it**: there's no Save button, and the window's **×** or **Esc** closes
it. This page lists every setting, page by page, and where CapyPanel keeps its files.

![Settings on CapyPanel > General: the page list on the left, with Keyboard shortcuts under General; Appearance, Startup and closing, and Updates, marked Everyone on this PC, on the right](images/settings-dark.png)

## Find a setting <a id="settings-find-a-setting"></a>

Type three letters or more in **Search settings**, at the top left. The right side shows every
section that mentions them, from every page, with the matching words marked in yellow, and the
settings work right there.

??? note "More about the window"

    - The pages are grouped: **CapyPanel** (General, Keyboard shortcuts), **Hosts** (General,
      Connecting, Credentials), **Printers** (General, Warnings and supplies, Connecting) and
      **SSH** (General).
      **About** sits apart at the very bottom. Settings opens on **CapyPanel > General**.
    - Each page is made of sections: a title with its settings on a soft card. A table looks the
      same everywhere: a thin line under each row, dividers to drag a column wider, the main
      actions as buttons under it, **every action for a row on its right-click**, and a
      double-click for the obvious one. Right-click the column titles for **Fit columns to
      content**.
    - Search matches words from their start, and the page list keeps only the pages with a match.
      A dropdown whose match is one of its choices gets the mark on its arrow. Clearing the box
      puts everything back.
    - The window opens at 960 × 740 the first time, or smaller on a small screen, such as a laptop
      at 125 % scale. You can make it any size: a page larger than the window scrolls, down and
      sideways. It opens again at the size and place you left it at.

??? note "Settings for everyone on this PC"

    Most settings are yours alone. A few are the same for everyone who uses CapyPanel on this PC,
    and their sections say **Everyone on this PC**, with a small computer, beside the title:

    - **CapyPanel > General > Updates**
    - **Hosts > Connecting**: **Connection profiles** (with **Hosts with no profile use**) and
      **Remote tools** (with **Read PC data with**)

    Under the title, one line says "A change here reaches everyone on this PC." If Windows doesn't
    let your account change them, the line reads "Read-only for you. An administrator of this PC
    can change it." and the controls are greyed. They're kept in the shared folder (see [Where
    CapyPanel keeps its files](#where-capypanel-keeps-its-files)), which only administrators and
    whoever created it can change.

    The shared host and printer lists are for everyone too: the lists tables say which list is
    **Shared** and which is **Personal**.

## CapyPanel > General <a id="settings-capypanel-general"></a>

| Setting | What it does | To begin with |
|---|---|---|
| **Theme** | The look: Windows (follow system, dark, light), CapyPanel (dark, light), Graphite or Paper | Windows, follow system |
| **Language** | English or Português (Brasil). "The app's language. Changes at once.", Settings included | The language Windows is shown in: Português (Brasil) for any Portuguese, English for the rest |
| **Open on startup** | What the window shows at start: the **Home page**, **The last used tool**, or a tool by name | Home page |
| **When closing** | What the window's **✕** does: **Ask each time**, **Keep running in the tray** or **Quit** (see [Getting started](getting-started.md#close-capypanel-or-keep-it-in-the-tray)) | Ask each time |

??? note "More about themes"

    "Windows themes follow Windows' look and accent; CapyPanel themes look the same everywhere."
    Themes change colors. Each one has its own shades of the warning colors (amber, red, green
    and grey), so warnings and Printers' dots and supply bars read clearly in the light themes too.
    The font and its size are the same in every one, and a theme never changes what the app does. The Windows themes follow your accent color (**Settings > Personalization > Colors**),
    and everything built from it stays readable.

### Updates <a id="settings-updates"></a>

**Everyone on this PC**: "A change here reaches everyone on this PC: an update replaces CapyPanel
for all of them."

| Setting | What it does | To begin with |
|---|---|---|
| **Check for updates** | **At every start**, **Once a day**, **Once a week** or **Off**. "Asks GitHub (api.github.com) for CapyPanel's newest release. Nothing is downloaded until you choose Install. Help › Check for updates works whatever is set." | At every start |

## CapyPanel > Keyboard shortcuts <a id="settings-capypanel-keyboard-shortcuts"></a>

![Settings on CapyPanel > Keyboard shortcuts: the commands under File, View and Help, each with its key, and Clear and Restore default under the list](images/settings-shortcuts-dark.png)

Every command a key can run is listed here, under **File**, **View**, **Help**, **Hosts**,
**Printers** and **SSH**, in the order you meet them in the app. **Key** shows the key it has now;
most commands start with none.

1. Double-click a command, or pick it and press **Enter**. Its key reads "Press the new key…".
2. Press the new key, with Ctrl, Alt or Shift if you like. **Esc** leaves the key as it was.

The new key works at once, and the menus show it. **Clear** takes the picked command's key away,
and **Restore default** gives back the one it came with.

??? note "More about keys"

    - A key another command already has moves only after a question: **Give it** moves it, and the
      other command is left with no key.
    - F1, Esc, Ctrl+F, Tab and Ctrl+Shift+W are kept for CapyPanel itself, as the line under the
      list says: "In an SSH terminal, all but Ctrl+Shift+W go to the server." **Help for this
      screen** shows F1 greyed: "F1 is kept for help and can't be changed." So is
      a key that types text on its own, such as a letter, a digit or Ç: use it with Ctrl or Alt.
      Press one and the field turns red and reads "Key not allowed", the reason shows in red
      under the list, and it keeps waiting for another key.
    - Each tool has its own rows, even for a command another has too, such as **Edit…** or
      **Remove**: a key given to one leaves the others' as they were.
    - **Connect** and **Open web page** read "Enter (in the list)": their key works only in the
      host or printer list.
    - The list ends with **SSH terminal**, under "Inside a terminal, every key goes to the server
      except the ones below and the keys that change tools or open Settings.": the terminal's own
      keys (Copy, Copy with text selected, Paste, Find, Bigger and Smaller text, Next and Previous
      tab, Close tab), greyed, since "The terminal's own keys can't be changed." (see [Work in the
      terminal](ssh/ssh.md#work-in-the-terminal)).
    - Restart, Shut down, Cancel the pending restart, Restart Print Spooler, and logging off or
      disconnecting someone aren't listed.
    - Tooltips and first-run guides name a command's key as it is now, so a key you change shows
      there at once, and a command with no key shows none.
    - Your keys are yours alone, kept in your settings file. Someone else on this PC keeps theirs.

## Hosts > General <a id="settings-hosts-general"></a>

| Setting | What it does | To begin with |
|---|---|---|
| **Host lists** | The table of every list, with **New…**, **Add existing…** and **Remove** (see [Switch, make and share lists](hosts/host-lists.md#switch-make-and-share-lists)) | The default and personal lists |
| **List on startup** | Which host list opens with the tool. "If that list can't be opened: the default list, then your personal list." | The last used list |
| **Show first** | What the open list shows when it opens: **All hosts**, **Where I left off**, or **A chosen group ▸**. "For the list open now; each list keeps its own." | All hosts |
| **Refresh status by itself** | Checks the status of the hosts shown every **minute**, **5**, **15** or **30 minutes**, or a **Custom…** interval from 1 to 120 (see [Checking hosts](hosts/checking.md#have-status-checked-on-its-own)) | Off |
| **Quick commands > Choose…** | "The buttons on top of a host's Details panel; the first four are also in its right-click menu. Yours, on this PC." (see [Choose your quick commands](hosts/commands.md#choose-your-quick-commands)) | C$ share, User's folder, Computer Management, Send a message… |

## Hosts > Connecting <a id="settings-hosts-connecting"></a>

![Settings > Hosts > Connecting: Connection profiles with their Password column, and Remote tools, each marked Everyone on this PC, and Read PC data with set to Automatic](images/settings-hosts-connecting-dark.png)

**Everyone on this PC**: both sections, **Connection profiles** and **Remote tools**, carry the
mark, with "A change here reaches everyone on this PC." under the title.

| Setting | What it does | To begin with |
|---|---|---|
| **Connection profiles** | The table **Profile \| Tool \| Password**, with **Add…**, **Edit…**, **Delete…** and **Restore built-in…** (see [Set up connection profiles](hosts/connecting.md#set-up-connection-profiles)) | UltraVNC, RealVNC, Remote Desktop |
| **Hosts with no profile use** | "The profile a host connects with when it has none of its own." | UltraVNC |
| **Remote tools** | The table **Tool \| Status \| Where**, with **Change path…** and **Download**: where each tool is installed | Found by itself |
| **Read PC data with** | How CapyPanel reads the PC facts, programs, mapped drives and user profiles of other PCs: **Automatic (recommended)**, **WMI directly** or **WMI through PowerShell** (see [How CapyPanel reads other PCs](hosts/checking.md#read-a-pcs-facts)) | Automatic |

??? note "More about profiles and tools"

    - A row's right-click adds **Duplicate…**, and a double-click edits. The **Password** column
      reads "Asked for by" and the viewer's name, "Saved in CapyPanel (user and password)" or
      "Saved in CapyPanel (password only)".
    - **Restore built-in…** brings back the profiles CapyPanel ships with, and is greyed while none
      is missing. It asks first, naming them, and adds "Profiles you changed or made yourself stay
      as they are." Cancel is the default button.
    - Changes are written for everyone the moment you make them. Where Windows doesn't let you
      change them, the line under the title says "Read-only for you. An administrator of this PC
      can change it."
    - CapyPanel fills the profiles folder at its first start, with a settings file,
      `_profiles.json`, that records **Hosts with no profile use** and which shipped profiles were
      added. Where the folder couldn't be created, the page shows the built-in profiles and says
      so.
    - A remote tool reads **✓ Found** when CapyPanel found it by itself, **✓ Your choice** when a
      path was set here, or **✗ Not found** ("Install it, or locate its .exe."). After **Change
      path…**, a row's right-click offers **Use the automatic path**. **Download** opens the
      tool's website, only for a tool that wasn't found.
    - Under both tables, a line names the files CapyPanel isn't using and why, such as "2 files
      skipped: broken.json (can't be read), clinics.json (made by another user)"; hover it for the
      full paths.
    - With **Automatic**, "in use:" beside it names the way it uses on this PC.

## Hosts > Credentials <a id="settings-hosts-credentials"></a>

![Settings > Hosts > Credentials: the Accounts table, and Saved credentials under Passwords](images/settings-hosts-credentials-dark.png)

| Setting | What it does | To begin with |
|---|---|---|
| **Accounts** | The table **Account \| Used for \| Kept in**: which account signs in to which PCs, for logged-on users and commands. "kept in your own settings, never in the shared host lists" (see [Use another account on some PCs](hosts/connecting.md#use-another-account-on-some-pcs)) | Empty: your Windows account everywhere |
| **Saved credentials** | How many logins CapyPanel keeps and where, as in "2 kept: 1 in Credential Manager, 1 temporary.", with **Manage…** (see [Forget a saved password](hosts/connecting.md#forget-a-saved-password)) | None kept |

## Printers <a id="settings-printers"></a>

| Page | Setting | What it does | To begin with |
|---|---|---|---|
| General | **Printer lists**, **List on startup**, **Show first** | As for Hosts (see [Keep printers in lists, groups and tags](printers/printers.md#keep-printers-in-lists-groups-and-tags)) | As for Hosts |
| Warnings and supplies | **Refresh on its own** | Reads every printer of the open list every **5**, **15**, **30** or **60 minutes** (see [Checking printers](printers/checking.md#have-printers-checked-on-their-own)) | Off |
| Warnings and supplies | **Warnings** | A row per reason (Offline, Out of paper, Out of toner, Paper jam, Stopped, Supply low), ticked for **In CapyPanel** and for **Windows notification** (see [Choose which problems warn](printers/checking.md#choose-which-problems-warn)) | Offline, Paper jam, Out of toner and Supply low, in both |
| Warnings and supplies | **Low supply level** | When a supply counts as low, 1 to 50 % | 10 % |
| Warnings and supplies | **Bar marks** | Marks on the supply bars, with **Change…** | The low level's mark |
| Warnings and supplies | **Toner column** | Text or a bar | Text |
| Connecting | **SNMP version** and **SNMP account** | v2c or v3, and the account for it (see [Set the SNMP account](printers/checking.md#set-the-snmp-account)) | v2c, "public" |
| Connecting | **Doc360 MPS account** | The portal login for printers whose page counters come from it (see [Get page counts from Doc360 MPS](printers/checking.md#get-page-counts-from-doc360-mps)) | Not set |

Profile cleanup has no settings of its own: it uses Hosts' lists and accounts.

## SSH > General <a id="settings-ssh-general"></a>

| Setting | What it does | To begin with |
|---|---|---|
| **Refresh status by itself** | Checks the SSH port of the hosts shown every **minute**, **5**, **15** or **30 minutes**, or a **Custom…** interval. "Only the SSH port, so nothing logs in. A server running fail2ban in a strict mode may count each check as a failed login and block this PC." (see [Check which hosts answer](ssh/ssh.md#check-which-hosts-answer)) | Off |
| **Terminal > Text size** | The terminal's text in every connection, from 8 to 20 pt. "In every connection. Ctrl+= and Ctrl+- in a terminal change it too." | 10 pt |
| **Terminal > Scrollback** | "Lines each connection keeps above its screen, to scroll back to, find and save. More lines take more memory." From 1,000 to 50,000; a shorter one lets the oldest lines go | 10,000 lines |
| **Separate windows > Open in** | Where **Connect in a separate window** opens ssh.exe: **A console window**, **Windows Terminal** when it's on this PC, or **Another program…** (see [Connect in a separate window](ssh/ssh.md#ssh-connect-in-a-separate-window)) | A console window |

SSH uses Hosts' lists, so they're set on **Hosts > General**.

## About <a id="settings-about"></a>

**Help > About CapyPanel** opens this page, at the bottom of the list. It has four cards:

| Card | What it holds |
|---|---|
| **CapyPanel** | The version (click it to copy it with its commit), the copyright and license, links to the documentation and the source code, a **Build** line, and **Report a problem** beside **Open log folder** |
| **Credits** | Who made CapyPanel, its mascot, and the icons it uses |
| **Licenses** | Every library CapyPanel ships, with its license; **Read license** opens the shipped text |
| **Folders** | Where CapyPanel keeps everything, with an **Open folder** button |

??? note "The Licenses and Folders cards in full"

    **Licenses** is the table **Software | Version | License | Notice**: CapyPanel (GPL-3.0), Qt
    and Qt for Python (LGPL-3.0), Python (PSF License), cryptography (BSD-3-Clause, and the OpenSSL
    license, Apache-2.0, in the same notice, because its Windows build carries OpenSSL), cffi
    (MIT-0) and pycparser (BSD-3-Clause), which cryptography needs, pywin32 (BSD-3-Clause), which
    CapyPanel reads other PCs through, truststore (MIT), which has Windows check GitHub's
    certificate, pyte (LGPL-3.0), which the SSH terminal is built on, ConPTY (MIT), Windows
    Terminal's console engine, which the SSH terminal runs on before Windows 11, and Tabler Icons
    (MIT). **Read license** also works on a double-click or the row's right-click, and **Open
    folder** opens the folder they all ship in.
    The CapyPanel card's "Free software under the GPL-3.0, with no warranty: see Licenses." scrolls
    down to them.

    **Folders** is the short version of the section below:

    | Folder | What it holds |
    |---|---|
    | **Shared** | "For everyone on this PC: connection profiles, remote tools, and the shared lists in “lists”, a folder for each kind of list." |
    | **Personal** | "Only for you and administrators: your settings, and your lists in “lists”, a folder for each kind of list." |
    | **Logs** | "One per user, named after the account." |

    In portable mode it adds "Portable mode: everything stays in the app's own folder."

## Where CapyPanel keeps its files <a id="settings-where-capypanel-keeps-its-files"></a>

Everything for all users of a PC is in one folder, `C:\ProgramData\CapyPanel`, with one private
folder per user:

| What | Where |
|---|---|
| Lists shared with everyone on the PC, a folder per kind | `lists\hosts\`, `lists\printers\` |
| Connection profiles, their settings files, and which one hosts fall back to | `profiles\` |
| Viewer definitions added by your company, where each viewer is installed, how other PCs are read, and how often to check for updates | `tools\` |
| Your settings, your accounts for other PCs among them | `users\<you@DOMAIN>\` |
| Your own lists, a folder per kind | `users\<you@DOMAIN>\lists\hosts\`, `…\lists\printers\` |
| Logs, one file per user | `logs\<you@DOMAIN>.log` |
| Every user profile you deleted, or tried to | `logs\<you@DOMAIN>.user-profiles.log` |
| Built-in viewer definitions, and the starter profiles | Inside the app |

While an update runs, its working files are in `%LOCALAPPDATA%\CapyPanel\update`, and they're
deleted once the new version is running (see [Update CapyPanel](download.md#update-capypanel)).

??? note "Who can read what"

    - **Your folder is private:** only you, administrators and Windows itself can open it.
      CapyPanel refuses to use a folder someone else created first in your name.
    - **Shared files must come from someone trusted.** Any user can add files to ProgramData, so
      CapyPanel ignores a shared file (a list, a profile, a company viewer definition) made by
      another user who isn't an administrator, and logs it.
    - **Logs never contain passwords.** They record which viewer started for which address, the
      result of each login check, and, at each start, which way CapyPanel reads other PCs. The user
      profiles log keeps, for each delete, when, on which PC, whose profile and how it ended.
    - CapyPanel makes these folders at its first start. Lists from an earlier version are copied
      into them once, by themselves: the `hosts.json` files of before 0.19, and the lists that 0.19
      kept directly in `lists\`. The older files are left where they are, so an older version still
      runs.

### Portable mode <a id="settings-portable-mode"></a>

An empty file named `capypanel.portable` next to the app keeps everything (settings, lists, logs)
in a `userdata` folder beside it instead, for running from a USB stick or a shared folder. When you
run from source, "next to the app" means the repository folder.

A portable copy's first start ends Home's guide with one more card, **A portable copy**: what it
keeps in `userdata`, that saved passwords stay in Windows Credential Manager on that PC, and that
lists and settings from another copy aren't brought in. **Open the userdata folder** opens the
folder. To use a list from another copy, open it with **Open list…** under the list's name, on top
of the Groups panel.

![The A portable copy card at the end of Home's guide, with Open the userdata folder](images/guide-portable-dark.png)

## Messages you may see <a id="settings-messages-you-may-see"></a>

| Message | What it means | What to do |
|---|---|---|
| <a id="settings-read-only"></a>"Read-only for you. An administrator of this PC can change it." | The settings in that section are the same for everyone on this PC, and Windows doesn't let your account change them | Ask an administrator of the PC to change them |
| <a id="settings-files-skipped"></a>"2 files skipped: broken.json (can't be read), clinics.json (made by another user)" | Under the profiles or the tools table: files in the shared folder that CapyPanel isn't using. Hover it for the full paths | Fix or remove a file that can't be read. A file made by another user who isn't an administrator is ignored on purpose: have an administrator put it there |
| <a id="settings-updates-not-saved"></a>"Couldn't save how often to check: …" | Windows refused to write the Updates setting, which is for everyone on this PC. Its reason follows the colon | Fix what the reason names, or ask an administrator to change it |
