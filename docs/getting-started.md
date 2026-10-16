# Getting started

## Run CapyPanel

CapyPanel runs on Windows 10 22H2 or Windows 11. There's no installer yet, so it runs from source
with [uv](https://docs.astral.sh/uv/):

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

The first run downloads Python and the libraries CapyPanel needs; later runs start right away.
The version shows in the title bar, followed by the commit when you run from source, e.g.
`CapyPanel 0.18.0 (abc1234)`. Quote it when you report a problem.

Remote Desktop works out of the box, with the client built into Windows. For VNC you also need a
viewer: [UltraVNC](https://uvnc.com) or
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). See
[Connecting](connecting.md).

## The main window

| Part | What it shows |
|---|---|
| **Toolbar** (top) | **Connect**, and **Refresh** to check the hosts shown (see [Checking hosts](checking.md)) |
| **Groups** (left) | "All hosts" pinned on top with how many hosts the list has, and "No group" under it with how many are in none. Then **Groups**, with a **+** button to add one, and **Tags** |
| **Search** (above the hosts) | Finds a host anywhere in the list, whatever is picked on the left (see [Searching hosts](searching.md)) |
| **Hosts** (middle) | The hosts in the selected group or tag, with their **Status** and **User** |
| **Details** (right) | The selected host: its name and status, then **Connection** (address, group, profile), who's **logged on**, its **tags** and its **notes**. Click any value to copy it. With nothing selected, how many hosts are shown, and how many of them are online, offline, not found or not checked |
| **Status bar** | Which list is open, where it is, how many hosts it has, how many are online once anything has been checked, and how many are selected |

The toolbar, the status bar and the panes around the host table can be hidden from the **View**
menu, and the panes can be dragged wider or narrower. To switch to another list, use
**File > Host lists…** (see [Host lists](host-lists.md#the-host-lists-window)).

The window is yours to arrange. Right-click the host table's column titles to choose which columns
show, or **Fit columns to content** at the bottom of that menu to fit them all to their text;
double-clicking a column's edge fits that one. Widths are saved for next time, and nothing resizes
them behind your back — not a Refresh, not switching lists. **View > Reset layout** puts the
panes, the columns and anything you hid back to the start, and leaves your settings alone.

## Add your first hosts

1. A new list starts with one group, **Default group**. **Inventory > Add group…**
   (Ctrl+Shift+N) creates another; with a group selected, the new one goes inside it. The **+**
   beside the **Groups** heading, and a right-click on the heading or on empty space, add one at
   the top level instead.
2. **Inventory > Add host…** (Ctrl+N) adds a host to the selected group:
   - **Name:** how the host shows in the list.
   - **Address:** a computer name or IP address. Leave it blank if the name *is* the computer name
     (e.g. `PC-1234`).
   - **Group:** where it goes. **No group** is a choice too, for a host that doesn't belong
     anywhere yet.
   - **Tags:** type a tag and press Enter; Backspace on an empty box brings the last tag back for
     editing.
   - **Connection profile:** how to reach the host. "From group" follows the group's profile.
3. Double-click the host, select it and press Enter, or click **Connect** in the toolbar, to open
   a connection to it with its profile.

Right-click a host to connect, to refresh its status or its logged-on users, to copy the column
you clicked, or to edit, move or remove it. Right-clicking empty space offers **Add group…** in
the groups pane, and **Add host…** and **Add group…** in the host list. To move hosts to another
group, drag them onto it (see [Host lists](host-lists.md#arranging-groups-and-hosts)). Removing a
group asks what should happen to the groups and hosts in it (see
[Host lists](host-lists.md#removing-a-group)).

Edits are saved to the list file at once; there's no Save button. To add many hosts in one go,
from a spreadsheet or another inventory, see
[Importing and exporting hosts](importing.md).

## Help, and reporting a problem

The **Help** menu has three items:

- **Documentation** opens this site, in Portuguese when the app is in Portuguese.
- **Report a problem** opens a new issue on GitHub with the facts that matter already in it: the
  version, how CapyPanel is running, Windows, the theme, the language, Qt and Python. It never
  includes a user name, a computer, a domain or a path.
- **About CapyPanel** shows the app icon, the name and the version — click the version to copy it
  with its commit — above three tabs:

| Tab | What it holds |
|---|---|
| **About** | What CapyPanel is, the copyright, that it's free software under the GPL-3.0 with no warranty, links to the documentation and the source code, and a **Build** line with the commit and portable mode where they apply |
| **Credits** | Who made CapyPanel, and the icons it uses |
| **Licenses** | Every part it's built with — CapyPanel (GPL-3.0), Qt and Qt for Python (LGPL-3.0), Python (PSF License), Tabler Icons (MIT) — with its version and copyright. Click a license to read it in a window here; they all ship with CapyPanel, and a link opens the folder holding them |

**Report a problem** and **Open log folder** are in that window too, so a report can go out with
the logs attached.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Enter (in the host list) | Open a connection to the selected hosts |
| Ctrl+F / Esc | Search the whole list / end the search |
| F5 | Refresh the hosts shown, checking what the Refresh button's panel has ticked |
| Ctrl+M | Manual connection to an address that isn't in the list |
| Ctrl+Shift+C | Copy the selected hosts' addresses |
| Ctrl+N / Ctrl+Shift+N | Add host / Add group |
| F2 / Del | Edit / remove the selection |
| Ctrl+O | Host lists window |
| Ctrl+, | Settings |
| Ctrl+Q | Exit |
