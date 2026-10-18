# Host lists

A host list is one JSON file holding groups, hosts and their tags. CapyPanel shows one list at a
time and saves every edit to it right away. To put many hosts in at once, or to take them out as
a CSV file, see [Importing and exporting hosts](importing.md).

## Groups and tags

- **Groups** nest as deep as you like ("Headquarters › Finance › Floor 3").
- **Tags** cut across groups ("kiosk", "floor-3"). Click a tag in the Groups panel to see every
  host that carries it. Tags you've used before are suggested as you type, with their spelling
  kept.
- **Notes** hold anything else worth knowing about a host. They show in the Details panel, and
  searching always covers them.
- **No group** is where a host sits when you haven't put it in one. "No group (4)" shows under
  "All hosts" in the Groups panel, with however many hosts have no group, and hosts dragged onto it
  leave the group they were in.

A new list starts with one group, **Default group**.

## Arranging groups and hosts

Groups keep the order you give them. In the Groups panel:

- drag a group up or down to move it, or drop it onto another group to put it inside;
- drag a group onto the **Groups** heading, which lights up as you reach it, to move it to the
  top level;
- drag selected hosts from the host table onto a group to move them there.

Right-click a group > **Move to** lists **Groups** — the top of the panel, inside nothing — and
every group this one can go into, drawn as a tree; the group itself and its own subgroups aren't
offered, and where it is now is ticked. For hosts, right-click them > **Move to** lists **No
group** first, then the same tree. A group you collapsed stays collapsed as you work, and moving a
group into a collapsed one opens the way to it, so what you moved stays in sight.

Every change is saved right away. On a read-only list, dragging is off.

**Inventory > Manage groups…** shows the whole tree in a window, under a **Groups** root with
tree lines, with **Move to**, **Move up**, **Move down** and **Sort A–Z**, a one-time sort you can
rearrange after. Dragging works there too: drop a group onto **Groups**, or below the last row, to
take it out of every group. Nothing changes until you click **OK**. Lists made before version
0.13.0 show their groups in the order they were created; Sort A–Z puts them in order once.

## Removing a group

Right-click a group > **Remove selected**, or press Del with a group picked. An empty group only
asks to confirm. A group with anything in it asks what should happen first — "“Floor 3” holds 2
groups and 7 hosts. What should happen to them?" — and offers two ways out:

- **Move them to ▸** picks where they go, from the same tree as moving hosts: **No group**, or any
  group that isn't being removed. The group above this one is ticked, so the usual answer is one
  click. Nothing is deleted; the groups inside move along with their hosts, and with **No group**
  they end up directly under **Groups**.
- **Remove everything:** the group, every group inside it and all their hosts.

Cancel is the default button, so Enter or Esc leaves the list as it is.

## Where lists live

CapyPanel keeps lists in two folders, made at its first start:

| Folder | Where | Who it's for |
|---|---|---|
| **Shared lists** | `C:\ProgramData\CapyPanel\lists` | Everyone on the PC. The **default list** is `default.json` there |
| **Your lists** | `C:\ProgramData\CapyPanel\users\<you@DOMAIN>\lists` | Only you, and administrators. Your **personal list** is `personal.json` there |

**Every list saved in either folder shows up by itself** — nothing to add. Drop a file in the
shared folder and everyone on the PC has it in their dropdown; drop one in yours and it's yours
alone. In portable mode both folders are inside the app's own `userdata` folder (see
[Settings and files](../settings-and-files.md#portable-mode)).

A list from before version 0.19, when these were `hosts.json` files, is copied into the folders
once, by itself.

Lists are named "Default", "Personal", and every other one by its file name without `.json`. Two
lists with the same name show their folder's name after it, and the full path is always in the
tooltip.

Windows permissions decide whether a list opens read-only, for every list wherever it lives. A
read-only list can still be browsed and connected to; only editing is off. A list anywhere else —
a network share, say — is added once and then stays in the dropdown.

Any user can add files to ProgramData, so **a shared list made by another user who isn't an
administrator isn't opened**: it could send your password to the wrong computer. It's left out of
the dropdown, named in the log, and shown in Settings as "Not used: made by another user", where an
administrator can replace or delete it.

## The list dropdown

The open list's name sits on top of the Groups panel, and in the window title. Click it and the
menu holds:

- **every list CapyPanel found or you added**, the open one ticked, each with its path in the
  tooltip. Pick one to switch to it;
- **New list…**, below them, and **Open list…** (Ctrl+O), which opens any list file from anywhere
  and keeps it in the dropdown from then on;
- **Manage host lists…**, which opens
  [Settings > Hosts > Host lists](#settings-hosts-host-lists).

## Making a new list

**New list…**, in the dropdown or on the Settings page, opens **New host list**: a **Name**, and
**For:**

- **Everyone on this PC (shared)** saves it in the shared lists folder. Only people Windows lets
  write that folder can pick this; for everyone else it's greyed out, with a note saying why.
- **Only me (personal)** saves it in your own lists folder.
- **Somewhere else, e.g. a network share…** asks where in a file dialog.

A name already taken asks before replacing that file with an empty list. The new list opens at
once.

## Settings > Hosts > Host lists

The same lists as the dropdown, as a table of **List**, **Type** and **Access**:

| Column | What it says |
|---|---|
| **List** | The list's name, and "(in use)" on the open one. Its path is in the tooltip |
| **Type** | **Shared** (in the shared folder), **Yours** (in your own) or **Added** (a list from somewhere else) |
| **Access** | **Read/write**, **Read-only**, **Created when opened** for a default or personal list that isn't there yet, **File not found**, or **Not used: made by another user** |

**New…**, **Add existing…** and **Remove** are under the table. A row's right-click adds **Open**,
**Save a copy…** and **Open folder**. A double-click, or **Open**, opens a list; adding one or
saving a copy doesn't open it.

As the page says under the table: "Lists saved in a lists folder show up here by themselves; Remove
asks whether to delete the file too." **Remove** asks which you meant:

- **Remove from my lists** leaves the file alone. A list that lives in a lists folder is then
  hidden for you only, and **Add existing…** or **Open list…** brings it back.
- **Delete the file** moves it to the **Recycle Bin**, for everyone who uses it. The question shows
  the path on one line first.
- **Cancel** is the default button.

A list whose file can't be deleted, or isn't there at all, is simply taken out of your lists.
Removing the list you have open opens the default list. The default and personal lists can't be
removed.

## Which list opens at start

Choose it under **Settings > Hosts > General > Startup > Open on startup**: the last used list
(the default choice), the default list, your personal list, or any other list you have. If that
list can't be opened, CapyPanel opens the next one it can — the default list, then your personal
list — and says so.

## What a list shows first

Each list keeps its own answer, in **Settings > Hosts > General > Startup > Show first**:

- **All hosts**, the whole list;
- **Where I left off**, the group, tag or view you had open when you closed it;
- **A chosen group ▸**, picked from the tree, or No group.

The setting is for the list open now, and the note under it says so. With no list open it reads
"Open a host list to choose what it shows first." A group's right-click menu sets the same thing:
**Show this group first** is a tick, and clicking it again clears it.

## Shared lists and editing at the same time

When two people edit the same shared list, CapyPanel never overwrites the other person's
changes. If the file changed since you opened it, your edit isn't saved, and you choose: save
your version as a copy, or reload the list with their changes.

## The file format

Lists are readable JSON with a schema version. Older versions of CapyPanel keep fields they don't
know about when they save, and a list written by a newer version is refused instead of being
damaged.
