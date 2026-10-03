# Host lists

A host list is one JSON file holding groups, hosts and their tags. CapyPanel shows one list at a
time and saves every edit to it right away.

## Groups and tags

- **Groups** nest as deep as you like ("Headquarters › Finance › Floor 3"). Removing a group
  removes the groups and hosts inside it, after asking.
- **Tags** cut across groups ("kiosk", "floor-3"). Click a tag in the left pane to see every host
  that carries it. Tags you've used before are suggested as you type, with their spelling kept.
- **Notes** hold anything else worth knowing about a host.

## Three kinds of list

| Kind | Where it lives | Who can change it |
|---|---|---|
| **Default** | `data\hosts.json` next to the app | Whoever Windows lets write that folder, normally administrators. Everyone else opens it read-only |
| **Personal** | Your own CapyPanel folder (see [Settings and files](settings-and-files.md)) | Only you. Created the first time it's needed |
| **Shared** | Anywhere you choose, e.g. a network folder | Whoever Windows lets write the file |

Windows permissions decide whether a list opens read-only, for every kind. A read-only list can
still be browsed and connected to; only editing is off.

**File > Recent lists** shows the lists you've opened, each with its kind and path.

## Which list opens at start

Choose it under **Settings > General > Open on startup**: the last used list (the default
choice), the default list, your personal list, or any list you've opened. If that list is
missing, CapyPanel opens the next one it can (default, then personal) and says so.

## Shared lists and editing at the same time

When two people edit the same shared list, CapyPanel never overwrites the other person's
changes. If the file changed since you opened it, your edit isn't saved, and you choose: save
your version as a copy, or reload the list with their changes.

## The file format

Lists are readable JSON with a schema version. Older versions of CapyPanel keep fields they don't
know about when they save, and a list written by a newer version is refused instead of being
damaged.
