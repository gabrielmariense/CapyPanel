# Searching hosts

The box above the host table finds a host anywhere in the open list, whatever group or tag is
picked on the left. Type part of a name; upper and lower case don't matter. **Ctrl+F** jumps to
the box.

## What it searches

The box lists exactly what it covers, "Search name, address, user, tags, notes" when every column
is shown:

- the computer **name**, always;
- the **address**, the logged-on **users** and the **tags**, each one while its column is shown;
- the **notes**, always, even though they have no column of their own.

Hiding or showing a column searches again. Users come from the last **Logged-on users** check (see
[Checking hosts](checking.md)), so a host that hasn't been checked isn't found by who is on it.

## While you search

- What you typed is marked like a highlighter wherever it matched: in the table's columns, and in
  the notes in the Details pane.
- The results come from the whole list, so nothing is picked in the left pane. The Details pane
  tells you which group the selected host is in, and CapyPanel never jumps there by itself.
- The status bar adds **N found**.
- **Refresh** checks only the results, and automatic status only the hosts shown.
- **Inventory > Export hosts…** offers the results as what to export, counted, while the search
  is on (see [Importing and exporting hosts](importing.md)).

## Moving on and ending a search

- **Down** or **Enter** in the box moves to the first result. Neither connects, so a typo can't
  reach the wrong PC. In the table, a double-click and Enter connect as usual.
- **Esc** ends a search wherever you are, and the **×** in the box clears it. Either way you go
  back to the group or tag that was picked before.
- Picking a group or tag on the left ends the search, and so does switching host lists.
