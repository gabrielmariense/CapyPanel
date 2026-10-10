# Host lists

A host list is one JSON file holding groups, hosts and their tags. CapyPanel shows one list at a
time and saves every edit to it right away.

## Groups and tags

- **Groups** nest as deep as you like ("Headquarters › Finance › Floor 3").
- **Tags** cut across groups ("kiosk", "floor-3"). Click a tag in the left pane to see every host
  that carries it. Tags you've used before are suggested as you type, with their spelling kept.
- **Notes** hold anything else worth knowing about a host. They show in the Details pane, and
  searching always covers them.

A new list starts with one group, **Default group**.

## Arranging groups and hosts

Groups keep the order you give them. In the Groups pane:

- drag a group up or down to move it, or drop it onto another group to put it inside;
- drag a group onto the **Groups** heading, which lights up as you reach it, to move it to the
  top level;
- drag selected hosts from the host table onto a group to move them there.

Right-click a group > **Move to** lists **Top level** and every group this one can go into, drawn
as a tree; the group itself and its own subgroups aren't offered, and where it is now is ticked. A
group you collapsed stays collapsed as you work, and moving a group into a collapsed one opens the
way to it, so what you moved stays in sight.

Every change is saved right away. On a read-only list, dragging is off.

**Inventory > Manage groups…** shows the whole tree in a window, with **Move to**, **Move up**,
**Move down** and **Sort A–Z**, a one-time sort you can rearrange after. Dragging works there too,
and nothing changes until you click **OK**. Lists made before version 0.13.0 show their groups in
the order they were created; Sort A–Z puts them in order once.

## Removing a group

Right-click a group > **Remove**, or press Del with a group picked. An empty group only asks to
confirm. A group with groups or hosts in it asks what should happen to them:

- **Move them into "Floor 3"** — the group above it, or **Move them to the top level**. This is
  the default: its hosts go into that group, its own groups move up one level, and nothing is
  deleted.
- **Remove everything:** the group, every group inside it and all their hosts.

A top-level group can't send its own hosts up, because every host needs a group and "All hosts" is
the whole list rather than a group. The move is off in that case, with a note saying so; move
those hosts into another group first to keep them.

## Three types of list

| Type | Where it lives | Who can change it |
|---|---|---|
| **Default** | `C:\ProgramData\CapyPanel\hosts.json`, shared by everyone on the PC | Whoever Windows lets write it: whoever created it, and administrators. Everyone else opens it read-only. Created empty when it's missing |
| **Personal** | Your own CapyPanel folder (see [Settings and files](settings-and-files.md)) | Only you. Created the first time it's needed |
| **Added** | Anywhere you choose, e.g. a shared network folder | Whoever Windows lets write the file |

Windows permissions decide whether a list opens read-only, for every kind. A read-only list can
still be browsed and connected to; only editing is off.

Any user can add files to ProgramData, so **a default list made by another user (not an
administrator) isn't opened**: it could send your password to the wrong computer. The Host lists
window shows it as "Not used: made by another user", and an administrator can replace or delete
it.

## The Host lists window

**File > Host lists…** (Ctrl+O) shows every list you've opened or added, with its type and
whether you can edit it. The list in use is bold and marked "(in use)"; hover over a list to see
where it is. Double-click a list, or select it and click **Open**, to switch to it.

- **Add existing…** adds a list file from anywhere, such as a network folder.
- **New…** creates an empty list.
- **Copy current list to…** saves a copy of the open list somewhere else.
- **Remove from the list** only forgets a list here; it never deletes the file. The default and
  personal lists can't be removed.

The window remembers the lists in your settings, not in the list files. **Settings > Host lists**
shows the same table.

## Which list opens at start

Choose it under **Settings > General > Open on startup**: the last used list (the default
choice), the default list, your personal list, or any list you've added. If that list is
missing, CapyPanel opens the next one it can (default, then personal) and says so.

## Shared lists and editing at the same time

When two people edit the same shared list, CapyPanel never overwrites the other person's
changes. If the file changed since you opened it, your edit isn't saved, and you choose: save
your version as a copy, or reload the list with their changes.

## The file format

Lists are readable JSON with a schema version. Older versions of CapyPanel keep fields they don't
know about when they save, and a list written by a newer version is refused instead of being
damaged.
