# Printer lists

A printer list is one JSON file holding groups, printers and their tags, exactly as a host list
holds hosts. The Printers tool shows one list at a time and saves every edit to it right away.

Lists of the two kinds are kept apart. Each file records which kind it is, so opening a printer
list in Hosts, or a host list in Printers, is refused with "“{path}” isn't a printer list." rather
than a window full of empty rows.

## Where they live

CapyPanel keeps a folder for each kind of list, in both of its lists folders:

| Folder | Where |
|---|---|
| **Shared printer lists** | `C:\ProgramData\CapyPanel\lists\printers` |
| **Your printer lists** | `C:\ProgramData\CapyPanel\users\<you@DOMAIN>\lists\printers` |

Hosts uses `lists\hosts` in the same two places. Everything else works as it does for hosts: a list
saved in either folder shows up by itself, the shared folder is for everyone on the PC and yours is
private to you, and in portable mode both sit inside the app's own `userdata` folder. See
[Host lists](../hosts/host-lists.md#where-lists-live) for the naming rules and what Windows
permissions decide.

## The list dropdown

The open list's name sits on top of the Groups panel. Its menu holds every printer list CapyPanel
found or you added, then **New printer list**, **Open a printer list** (Ctrl+O) and **Manage
printer lists…**, which opens **Settings > Printers > Printer lists**.

## Groups and tags

Groups nest as deep as you like, printers with no group of their own sit under **No group**, and
tags cut across groups. Dragging, **Move to**, **Manage groups…** and removing a group all behave
as they do in Hosts, which [Host lists](../hosts/host-lists.md) describes.

## Settings

**Settings > Printers** has three sections:

- **Startup > List on startup:** which printer list opens with the tool, and **Show first**, what
  that list shows when it opens. Each list keeps its own answer.
- **Refresh:** the SNMP community string, the low supply level and how the Toner column shows,
  all under [Checking printers](checking.md).
- **Printer lists:** the table of every list with its type and what you can do to it, with
  **New…**, **Add existing…** and **Remove**. It's the same page as Host lists, down to what
  **Remove** asks, which [Host lists](../hosts/host-lists.md#settings-hosts-host-lists) covers.
