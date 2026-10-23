# Importing and exporting hosts

Hosts don't have to be typed in one by one. **Inventory > Import hosts…** reads a list you paste
or a CSV file, and **Report** on the toolbar writes what you have back out as CSV. The two use the
same format, so a list can make the round trip.

## Importing hosts

**Inventory > Import hosts…** opens the **Import hosts** window. Nothing changes in your list
until you click **Add {n} hosts**, and the window says so under its preview.

### Getting the list in

Paste a list into the box at the top, or click **Open a CSV file…** to read a `.csv` or `.txt`
file. Either way the lines fill the preview table below. Three shapes are understood, and the
**Formats…** button shows each one with an example:

| Format | What it looks like |
|---|---|
| **Hostnames** | One computer name per line |
| **Name and address** | A name, then the computer's name or IP address, separated by a comma, or two columns copied from Excel |
| **CSV with headers** | A first line naming the columns: `name, address, group, tags, notes` |

With headers the columns can come in any order, and their names work in English or in Portuguese
(`nome, endereço, grupo, tags, notas`). In a group cell, `/` separates the levels
("Headquarters/Front desk"); in a tags cell, `;` separates the tags. Columns CapyPanel has no use
for are ignored, and the summary names them: "Ignored columns: …".

A list with more than a name and an address but no header row can't be read, because CapyPanel
won't guess which column is which. It says "This list needs a header row." and points at
Formats….

### Checking it before it goes in

The preview table shows **Name**, **Address**, **Group**, **Tags**, **Notes** and a **Warning**
for every row. Right-click a row:

- **Edit cell** (F2) changes the value under the pointer; a double-click does the same.
- **Put in group ▸** puts the selected rows in a group, picked from the tree.
- **Set tags…** gives the selected rows the same tags, separated by `;`.
- **Leave out of the import** (Del) drops the rows from this import. The file isn't touched.
- **Add a row below** types a host in by hand.

Editing in the table rewrites the pasted text above as CSV with a header row, so the two always
agree. CapyPanel asks before doing that the first time.

### Where the hosts land

**Hosts with no group go to:** chooses where rows that name no group of their own end up: **No
group**, or any group in the list. It starts on the group you had picked when you opened the
window.

A group named in the file that doesn't exist yet is created by the import. The preview marks it
("A new group: the import creates it") and the summary names it: "New group: …".

### What gets added

The summary counts three things: "{n} hosts will be added.", and, when they apply, "{n}
skipped." and "{n} can't be added."

- A host already in your list is **skipped**, never overwritten. Its row says what it repeats,
  such as "Already in the list, in “Front desk”", or "Same name as row 7" for a repeat inside
  the file itself.
- A row that **can't be added** says why: "No name", "Not a computer name or IP address", or "No
  address: the name must then be the computer's name on the network".
- Tags and notes come in with their hosts.

**Add {n} hosts** adds them and closes the window; the status bar says how many arrived.

## Exporting hosts

**Report**, on the toolbar, opens the **Report** window. It only reads your list, so it works on a
read-only list too.

### Hosts, columns and presets

- **Hosts:** a dropdown of everything you can export, each with how many hosts it holds: the
  **search results** while a search is on, the **picked tags** while any are picked, the
  **selected hosts** when you have more than one selected, **All hosts**, **No group**, every
  group (with the hosts of the groups inside it) and **Tag: {tag}** for each tag. It opens on
  whatever the window is showing, every time.
- **Columns:** tick what each row should hold, grouped as **Host** (Name, Address, Group), **Tags
  and notes** (Tags, Notes) and **Last check** (Status, Logged-on users). The ticks are kept as
  soon as you change them, so closing the window never loses them.
- **Preset:** **For Import** ticks the hosts' own fields, "which Import hosts reads back: to move
  hosts to a list". Keep your own set with **Save as preset…**, and remove one with **Delete**.
  A name already in use asks "A preset named “{name}” already exists. Replace it?", with Cancel as
  the default. Ticks matching no preset read **Custom**.

### Status and logged-on users

Those two columns come from the last check (see [Checking hosts](checking.md)), so a host nobody
has checked exports empty. Ticking either one offers **Refresh**, which checks these hosts now and
shows "Checking 3 of 12…" with a **Stop** button while it runs.

With **Logged-on users** ticked, a warning stays on screen: "Includes who was logged on to each
PC. Keep the file private."

### Copy, or Export… to a file

**Preview** shows the rows that will go out. Then:

- **Copy** puts every row on the clipboard with tabs between the columns, to paste straight into
  Excel. It says how many hosts it copied and from where, and the window stays open, so another
  part of the list can go out next.
- **Export…** saves a CSV named after the list, and after the part of it you picked, says "Report
  saved: 12 hosts from All hosts." with the file under it, and offers **Open file** or **Open
  folder**.

**Close**, at the bottom, is the only way out: there's nothing to cancel, since every choice here
is kept as soon as it's made. The status bar repeats what went out.

The file uses the column separator your PC's Excel expects, a comma or a semicolon where that's
the local one, with tags separated by the other character. It's written so that accented names
open correctly.

What Report writes is read back by Import hosts, which makes **For Import** a way to copy hosts
between lists, or to keep a copy of a list before a big change.
