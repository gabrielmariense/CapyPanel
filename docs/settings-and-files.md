# Settings and files

Open Settings with **File > Settings…** (Ctrl+,). **OK** saves and closes, **Save** saves and
keeps Settings open, and **Cancel** closes and drops anything not saved.

## General

- **Open on startup:** which host list opens when CapyPanel starts (see
  [Host lists](host-lists.md#which-list-opens-at-start)).
- **Language:** English or Português (Brasil), switched without a restart. Also under
  **View > Language**. The Settings window itself changes language the next time you open it.
- **Refresh:** check the status of the hosts shown every few minutes. Off by default; see
  [Checking hosts](checking.md#automatic-status).
- **Where CapyPanel keeps its files:** the shared files, your own files and the logs, each with
  an **Open folder** button.

## Host lists

The same table and buttons as **File > Host lists…** (see
[Host lists](host-lists.md#the-host-lists-window)). The list you pick opens when you click OK or
Save.

## Connections

- **Connection profiles:** add, edit, duplicate and delete the profiles, and choose the
  default one. See [Connecting](connecting.md#managing-profiles).
- **Remote tools:** where each tool is installed, set once for everyone on the PC. Each shows
  **✓ Found** (by itself), **✓ Your choice** or **✗ Not found**, with only the buttons that fit:
  **Change path…** or **Locate…** to pick its `.exe` (a portable copy, say), **Find
  automatically** to forget that choice, and **Download** to open the viewer's website when it's
  missing. Remote Desktop Connection is built into Windows, so it normally shows **✓ Found** and
  has no Download. Like profiles, only people Windows lets write the folder can change them.

As everywhere in Settings, nothing on this page is written until you click OK or Save. Leaving
the page with unsaved changes asks first: **Save changes**, **Discard changes** or **Keep
editing**.

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
