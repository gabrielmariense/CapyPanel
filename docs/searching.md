# Searching hosts

The box above the host table finds a host anywhere in the open list, whatever group or tag is
picked on the left. Type part of a name; upper and lower case don't matter. **Ctrl+F** jumps to
the box.

## What it searches

Only what you can see: the computer name always, the address while the **Address** column is
shown, and logged-on users while the **User** column is shown. The box says which, for example
"Search name, address, user". Showing or hiding a column searches again. Tags and notes aren't
searched.

Users come from the last **Logged-on users** check (see [Checking hosts](checking.md)), so a host
that hasn't been checked isn't found by who is on it.

## While you search

- The results come from the whole list, so a **Group** column appears after **Computer**, with
  each host's full group path ("Headquarters › Finance"). It isn't in the column chooser.
- What you typed is marked like a highlighter in the Computer, User and Address columns.
- Nothing is picked in the left pane.
- The status bar adds **N found**.
- **Refresh** checks only the results, and automatic status only the hosts shown.

## Moving on and ending a search

- **Down** or **Enter** in the box moves to the first result. Neither connects, so a typo can't
  reach the wrong PC. In the table, a double-click and Enter connect as usual.
- Right-click a host > **Show in group** (Ctrl+G) opens the group it's in, ends the search and
  keeps the host selected.
- **Esc** ends a search wherever you are, and the **×** in the box clears it. Either way you go
  back to the group or tag that was picked before.
- Picking a group or tag on the left ends the search, and so does switching host lists.
