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
The version shows in the title bar. When you run from source it's followed by a build number
and the commit, e.g. `CapyPanel 0.25.0 build 1378 (abc1234)`; a bigger build number is a newer
build. Quote it when you report a problem.

Remote Desktop works out of the box, with the client built into Windows. For VNC you also need a
viewer: [UltraVNC](https://uvnc.com) or
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). See
[Connecting](hosts/connecting.md).

## The Home page

CapyPanel opens on its Home page: the capybara, the app's line, and a tile for each of its tools
with one line about it and its shortcut. Click a tile to open that tool.

| Tool | What it's for |
|---|---|
| **Hosts** (Ctrl+1) | "Your computers: connect, see who's logged on, check them." |
| **Printers** (Ctrl+2) | "Your printers: status and toner, web pages, reports." |
| **User profiles** (Ctrl+3) | "A PC's Windows profiles: see which can be deleted." |

![The Home page: the rail on the left, the capybara and the app's name, and a tile for each tool](images/home-dark.png)

Home is the top button on the rail, **View > Home**, and **Ctrl+0**. Every tool is always there;
there's nothing to turn on. To start somewhere else, set **Settings > CapyPanel > General > Open
on startup** to the last used tool, or to one by name.

The rest of this page is about the **Hosts** tool. Printers has its own pages, starting at
[The Printers tool](printers/printers.md), and so has
[User profiles](profiles/user-profiles.md).

## The Hosts window

![The Hosts window: groups on the left, the hosts in the middle, one host's details on the right](images/main-window-dark.png)

| Part | What it shows |
|---|---|
| **The rail** (left edge) | **Home** (Ctrl+0) at the top, then one icon per tool with its name in a tooltip, **Hosts** (Ctrl+1), **Printers** (Ctrl+2) and **User profiles** (Ctrl+3), and **Settings** (Ctrl+,) at the bottom. Where you are has a tinted square behind its icon |
| **Toolbar** (top) | The buttons of the tool you're in. For Hosts: **Connect**, **Refresh all**, **Commands**, **Inventory** and **Report** |
| **Groups panel** (left) | The open list's name on top, as a dropdown that switches lists. Then "All hosts" with how many hosts the list has, and "No group" under it with how many are in none. Then **Groups**, with a **+** button to add one, and **Tags**; drag the line above Tags to give either more room, and it's remembered |
| **Hosts panel** (middle) | The search box (see [Searching hosts](hosts/searching.md)) above the hosts in the selected group or tag, with their **Status** and **User** |
| **Details panel** (right) | The selected host: its name and status, a grid of buttons for its [commands](hosts/commands.md) (**Refresh**, **Commands**, **Users ▾**, **Power ▾**, then your [quick commands](hosts/commands.md#quick-commands)), then **Connection** (address, group, what **Connect with** opens and the account **Commands run as**; see [Connecting](hosts/connecting.md#in-the-details-panel)), who's **logged on**, the **PC facts**, its **tags** and its **notes**. Click any value to copy it. With nothing selected, how many hosts are shown, and how many of them are online, offline, not found or not checked |
| **Status bar** | The open list and its counts, as in "Shared · Clinic · 8 hosts · 3 online · 1 selected": its kind (**Default**, **Personal** or **Shared**, with a shared list's name after it), how many hosts it has, how many are online once anything has been refreshed, and how many are selected. Rest the mouse on it to see the list's file path; a click copies the path ("Copied: …") |

The menu bar is the same whichever tool you're in, and holds nothing a tool owns:

- **File** opens **Settings…** (Ctrl+,) and closes CapyPanel with **Exit** (Ctrl+Q).
- **View** goes to **Home** and to each tool, then shows or hides the panels of the tool you're
  in, the **Toolbar** and the **Status bar**. In Hosts it also holds **Customize the details
  panel…** (see [below](#customizing-the-details-panel)) and **Show users' domain** (see
  [Checking hosts](hosts/checking.md#logged-on-users)). It stays open while you tick, so several
  parts can be shown or hidden in one go.
- **Help** has **Documentation**, **Report a problem** and **About CapyPanel**.

The window is yours to arrange. Drag the edge between two panels to move it, or **double-click**
the right edge of the **Groups panel** or the **Hosts panel** to make that panel exactly as wide as
what's in it, the widest group or tag or the table's columns, with the panel beside it taking
the rest. Right-click the host table's column titles to choose which columns show, or **Fit columns
to content** at the bottom of that menu to fit them all to their text; double-clicking a column's
edge fits that one. Widths are saved for next time, and nothing resizes them behind your back,
not a Refresh and not switching lists.

To work on another list, use the dropdown on top of the Groups panel: it lists every list CapyPanel
found, and makes, opens and manages them (see [Host lists](hosts/host-lists.md#the-list-dropdown)).

### Customizing the Details panel

**View > Customize the details panel…**, or a right-click on the Details panel, opens a window with
two tabs. **Quick commands** picks the buttons under the fixed row (see
[Commands on a host](hosts/commands.md#quick-commands)). **Information** has one tick per part of
the panel: **Connection**, **Logged-on users**, **PC facts**, **Tags** and **Notes**. "Untick what
you don't use. Hiding a part never stops a check." An unticked part hides at once, and the foot of
the panel then says how many are hidden, as in "2 parts hidden · Customize…", the last word a link
back to this window. The host's name, its status and a pending restart's warning always show. The
choice is "Only for you, on this PC."

## Add your first hosts

The **Inventory** button on the toolbar holds everything that puts hosts in a list.

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

   **Add** puts it in the list.
3. Double-click the host, select it and press Enter, or click **Connect** in the toolbar, to open
   a connection to it with its profile.

A new list says "This list has no hosts yet. Add one, or import several at once." with **Add
host…** and **Import hosts…** buttons right there, and an empty group says "This group has no
hosts yet." with **Add host…**.

Right-click a host to connect, to refresh it with **Refresh host**, to run one of your first four
quick commands or open **All commands…** (see [Commands on a host](hosts/commands.md)), to copy a
column through **Copy ▸**, or to edit, move or remove it. With several hosts selected, the menu
also picks the account their commands run as, from **Commands run as ▸**. **Copy** lists
every column the table shows, one line per selected host, and **Address** keeps Ctrl+Shift+C.
Right-clicking empty space offers **Add group…** in the groups panel, and **Add host…** and
**Add group…** in the host list. To move hosts
to another group, drag them onto it (see
[Host lists](hosts/host-lists.md#arranging-groups-and-hosts)). Removing a group asks what should
happen to the groups and hosts in it (see [Host lists](hosts/host-lists.md#removing-a-group)).

Edits are saved to the list file at once; there's no Save button. To add many hosts in one go,
from a spreadsheet or another inventory, see
[Importing and exporting hosts](hosts/importing.md).

## Closing CapyPanel and the tray

The window's **✕** usually quits CapyPanel, as do **File > Exit** (Ctrl+Q) and Windows logging off
or shutting down, which never ask anything.

While something works on its own, though, quitting stops it: the Printers tool can
[refresh on its own](printers/checking.md#refresh-on-its-own) and warn you about a printer that
needs attention. CapyPanel then keeps an icon in the **Windows tray**, carrying the same red count
as the rail, with "CapyPanel" and what the count means in its tooltip. A click on the icon opens
the window again, and its menu holds **Open CapyPanel** in bold, a line per tool with something to
report, as in "3 printers need attention…", which opens that tool with just those items listed,
and **Quit CapyPanel**.

![The tray menu: Open CapyPanel, the printers that need attention, and Quit CapyPanel](images/tray-menu-dark.png)

With something working on its own, the **✕** asks what you meant: "Keep CapyPanel running in the
tray?", "Refresh on its own and warnings keep working while CapyPanel is in the tray. Quit stops
them.", with **Keep in tray** as the default button, **Quit**, **Cancel**, and a "Don't ask again
(change it in Settings › CapyPanel › General)" box. **Settings > CapyPanel > General > When
closing** answers it for good, with **Ask each time**, **Keep running in the tray** or **Quit**.
With nothing working on its own, the ✕ quits straight away.

Quitting while the User profiles tool is deleting profiles asks first, whichever way you quit
from CapyPanel itself: "Quitting now cancels the profiles still queued. The profile being deleted
on each host finishes first; CapyPanel quits after that." **Cancel the rest and quit** does
that; **Continue** keeps CapyPanel open and the deletes going (see
[The User profiles tool](profiles/user-profiles.md#deleting)).

## Help, and reporting a problem

The **Help** menu has three items:

- **Documentation** opens this site, in Portuguese when the app is in Portuguese.
- **Report a problem** opens a new issue on GitHub with the facts that matter already in it: the
  version, how CapyPanel is running, Windows, the theme, the language, Qt and Python. It never
  includes a user name, a computer, a domain or a path.
- **About CapyPanel** opens Settings on its **About** page: the version to click and copy with its
  commit, who made CapyPanel, every license it ships, where it keeps its files, and **Report a
  problem** beside **Open log folder**, so a report can go out with the logs attached (see
  [Settings and files](settings-and-files.md#about)).

When something goes wrong inside CapyPanel itself, a window says "Something went wrong. The
details were saved to the app log." with the details under it, and **Copy all** to paste them
into a report. It's one window however many times it happens: a second error is added to it, and
the same error again is counted ("This error happened 3 times:") instead of shown twice.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Enter (in the host list) | Open a connection to the selected hosts |
| Ctrl+F / Esc | Search the whole list / end the search |
| F5 | Refresh the hosts shown, checking what the Refresh button's panel has ticked |
| Ctrl+M | The Commands window for an address that isn't in the list |
| Ctrl+E | Open the selected host's C$ share |
| Ctrl+Shift+O | Open a path on the selected host |
| Ctrl+Shift+U | Open the logged-on user's folder |
| Ctrl+Shift+M | Computer Management, pointed at the selected host |
| Ctrl+Shift+C | Copy the selected hosts' addresses |
| Ctrl+N / Ctrl+Shift+N | Add host / Add group |
| F2 / Del | Edit / remove the selection |
| Ctrl+0 / Ctrl+1 / Ctrl+2 / Ctrl+3 | Home / the Hosts tool / the Printers tool / the User profiles tool |
| Ctrl+O | Open a host list file |
| Ctrl+, | Settings |
| Ctrl+Q | Exit |
