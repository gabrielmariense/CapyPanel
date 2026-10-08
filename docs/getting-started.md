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
`CapyPanel 0.16.0 (abc1234)`. Quote it when you report a problem.

Remote Desktop works out of the box, with the client built into Windows. For VNC you also need a
viewer: [UltraVNC](https://uvnc.com) or
[RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/). See
[Connecting](connecting.md).

## The main window

| Part | What it shows |
|---|---|
| **Toolbar** (top) | **Connect**, and **Refresh** to check the hosts shown (see [Checking hosts](checking.md)) |
| **Groups** (left) | "All hosts" pinned on top, with how many hosts the list has. Then **Groups**, with a **+** button to add one, and **Tags** |
| **Search** (above the hosts) | Finds a host anywhere in the list, whatever is picked on the left (see [Searching hosts](searching.md)) |
| **Hosts** (middle) | The hosts in the selected group or tag, with their **Status** and **User** |
| **Information** (right) | The selected host's details, including its connection profile and where it comes from. With nothing selected, how many hosts are shown, and how many of them are online, offline, not found or not checked |
| **Status bar** | Which list is open, where it is, how many hosts it has, how many are online once anything has been checked, and how many are selected |

The toolbar, the status bar and each pane can be hidden from the **View** menu. Right-click the
host table's column titles to choose which columns show. To switch to another list, use
**File > Host lists…** (see [Host lists](host-lists.md#the-host-lists-window)).

## Add your first hosts

1. A new list starts with one group, **Default group**. **Inventory > Add group…**
   (Ctrl+Shift+N) creates another; with a group selected, the new one goes inside it.
2. **Inventory > Add host…** (Ctrl+N) adds a host to the selected group:
   - **Name:** how the host shows in the list.
   - **Address:** a computer name or IP address. Leave it blank if the name *is* the computer name
     (e.g. `PC-1234`).
   - **Tags:** type a tag and press Enter; Backspace on an empty box brings the last tag back for
     editing.
   - **Connection profile:** how to reach the host. "From group" follows the group's profile.
3. Double-click the host, select it and press Enter, or click **Connect** in the toolbar, to open
   a connection to it with its profile.

Right-click a host to connect, check it, show it in its group, copy its address or name, or edit
or remove it.
Right-clicking empty space offers **Add group…** in the groups pane, and **Add host…** and
**Add group…** in the host list. To move hosts to another group, drag them onto it (see
[Host lists](host-lists.md#arranging-groups-and-hosts)). Removing a group asks what should happen
to the groups and hosts in it (see
[Host lists](host-lists.md#removing-a-group)).

Edits are saved to the list file at once; there's no Save button.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Enter (in the host list) | Open a connection to the selected hosts |
| Ctrl+F / Esc | Search the whole list / end the search |
| Ctrl+G | Show the selected host in its group |
| Ctrl+M | Manual connection to an address that isn't in the list |
| Ctrl+Shift+C | Copy the selected hosts' addresses |
| Ctrl+N / Ctrl+Shift+N | Add host / Add group |
| F2 / Del | Edit / remove the selection |
| Ctrl+O | Host lists window |
| Ctrl+, | Settings |
| Ctrl+Q | Exit |
