# Settings and files

Open Settings with **File > Settings…** (Ctrl+,). The window has two buttons: **Save**, which
saves and leaves it open, and **Close**. Close asks first when something isn't saved, and neither
button is the default one, so Enter never saves or closes by accident.

## General

- **Open on startup:** which host list opens when CapyPanel starts (see
  [Host lists](host-lists.md#which-list-opens-at-start)).
- **Language:** English or Português (Brasil). It changes as soon as you pick it — the Settings
  window included — with no restart and nothing to save. Also under **View > Language**.
- **Refresh:** check the status of the hosts shown every few minutes. Off by default; see
  [Checking hosts](checking.md#automatic-status).
- **Show first:** what the open list shows when it opens — All hosts, where you left off, or a
  group. Each list keeps its own choice (see
  [Host lists](host-lists.md#what-a-list-shows-first)).
- **Where CapyPanel keeps its files:** the shared files, your own files and the logs, each with
  an **Open folder** button. The paths are there to read, not to select; hover one to see it in
  full.

## Host lists

The same table and buttons as **File > Host lists…** (see
[Host lists](host-lists.md#the-host-lists-window)). The list you pick opens when you click Save.

## Connections

- **Connection profiles:** add, edit, duplicate and delete the profiles, and choose the
  default one, with an **Open folder** button for the folder they live in. See
  [Connecting](connecting.md#managing-profiles). CapyPanel fills that folder at its first start
  with the profiles it ships — RealVNC, Remote Desktop and UltraVNC — and a settings file,
  `_profiles.json`, which records the default profile and which shipped profiles have been added
  already, so one you delete doesn't come back. Where Windows doesn't let you create the folder,
  the page shows the built-in profiles instead and says "These are the built-in profiles: the
  folder isn't there yet."
- **Remote tools:** where each tool is installed, set once for everyone on the PC. Each shows
  **✓ Found** (by itself), **✓ Your choice** or **✗ Not found**, with only the buttons that fit:
  **Change path…** or **Locate…** to pick its `.exe` (a portable copy, say), **Find
  automatically** to forget that choice, and **Download** to open the viewer's website when it's
  missing. Remote Desktop Connection is built into Windows, so it normally shows **✓ Found** and
  has no Download. Like profiles, only people Windows lets write the folder can change them.

Under each folder on this page — the profiles and the remote tools — a line names the files
CapyPanel isn't using and why, such as "2 files skipped: broken.json (can't be read), clinics.json
(made by another user)". Hover it for the full paths and the errors; it's hidden when every file
is in use.

As everywhere in Settings, nothing on this page is written until you click Save. Leaving the page,
or closing Settings, with unsaved changes asks first: **Save changes**, **Discard changes** or
**Keep editing**.

## Appearance

| Theme | Look |
|---|---|
| Windows — follow system theme / dark / light | Native Windows styling, with your accent color |
| CapyPanel — dark / light | CapyPanel's own look, the same on every computer |
| Graphite, Paper | Two more of CapyPanel's own looks |

Also under **View > Theme**. Themes change colors only — the font, its size and the rounded
corners are the same in every one — and never change what the app does.

The Windows themes follow your Windows accent color (**Settings > Personalization > Colors**), and
everything built from it stays readable whichever one you pick: section headings, the default
button, highlights, and the Groups heading when you drag a group onto it. CapyPanel's own looks
keep their own accents instead, the same on every computer.

## Where CapyPanel keeps its files

CapyPanel keeps everything for all users of a PC in one folder, `C:\ProgramData\CapyPanel`,
with one private folder per user:

| What | Where |
|---|---|
| Default host list, shared by everyone on the PC | `hosts.json` |
| Connection profiles, their settings files, and which one is the default | `profiles\` |
| Viewer definitions added by your company, and where each viewer is installed | `tools\` |
| Your settings and personal list | `users\<you@DOMAIN>\` |
| Logs, one file per user | `logs\` |
| Built-in viewer definitions, and the starter profiles | Inside the app |

- **Your folder is private:** only you, administrators and Windows itself can open it.
  CapyPanel refuses to use a folder someone else created first in your name.
- **Shared files must come from someone trusted.** Any user can add files to ProgramData, so
  CapyPanel ignores a shared file (default list, profile, company viewer definition) made by
  another user who isn't an administrator, and logs it.
- **Logs never contain passwords.** They record which viewer started for which address, and the
  result of each login check.

### Portable mode

An empty file named `capypanel.portable` next to the app keeps everything (settings, lists,
logs) in a `userdata` folder beside it instead, for running from a USB stick or a shared folder.
When you run from source, "next to the app" means the repository folder.
