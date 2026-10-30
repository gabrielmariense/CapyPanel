# The Printers tool

Printers is CapyPanel's second tool: an inventory of the printers you look after, with what it
takes to tell one from another and a way to open any printer's own web page. Open it from the
**Printers** tile on the Home page, the printer icon on the rail, or **Ctrl+2**.

It has its own lists, kept apart from the Hosts tool's (see
[Printer lists](printer-lists.md)).

## The window

![The Printers window: groups on the left, the printers in the middle, one printer's details on the right](../images/printers-dark.png)

| Part | What it shows |
|---|---|
| **Toolbar** | **Open web page**, **Refresh**, **Inventory** and **Report** |
| **Groups panel** (left) | The open list's name on top, as a dropdown, then "All printers" and the groups and tags of the list |
| **Printers panel** (middle) | The search box above the printers in the group or tag you picked |
| **Details panel** (right) | Everything known about the printer you selected. Click any value to copy it |
| **Status bar** | Which list is open, where it is, how many printers it holds and how many are selected |

**Refresh** reads the status and the supplies of every printer shown, over SNMP, and fills the
**Status** and **Toner** columns. It has a page of its own:
[Checking printers](checking.md).

**Inventory** holds **Add printer…** (Ctrl+N), **Add group…** and **Manage groups…**, the same
three as in Hosts.

### The table

The columns are **Name**, **Address**, **Status**, **Toner**, **Brand**, **Model**, **Serial
number**, **Asset tag** and **Tags**, in that order. Serial number and Asset tag start hidden:
right-click the column titles to show them. Status and Toner stay empty until you refresh. The
same right-click menu, and **Copy ▸** on a printer, list the columns in that order. Columns can't
be dragged into another order, in either tool.

Click a column title to sort by it, and again to reverse it. Numbers inside names sort as numbers,
so "P2" comes before "P10"; upper and lower case don't matter, and printers that tie are ordered by
name.

## Adding a printer

**Inventory > Add printer…** (Ctrl+N) asks for:

- **Name** and **Address**, the address being an IP address or a network name. A printer with no
  address is reached by its name.
- **Group** and **Tags**, which work as they do in Hosts.
- **Brand** and **Model**. Brand is a dropdown of common makes (Brother, Canon, Epson, HP, Kyocera,
  Lexmark, Ricoh, Samsung, Xerox, Zebra), and you can type any other one in.
- **Serial number** and **Asset tag**, the two numbers you need when you call support or do an
  audit. Brand and serial number are saved in capitals.
- **Page counters**, which says where the page counts will come from: **SNMP**, asked from the
  printer itself, or **Doc360 MPS**, the managed-print portal. Nothing reads counters yet; the
  setting records where they will be read from.
- **Notes**, for anything else.

**Edit selected…** (F2) opens the same window for printers already in the list.

The **Details** panel shows all of it, under **Connection** (address, group), **Supplies**,
**Printer** (brand, model, serial number, asset tag), **Page counters** (source and the printer's
own total), **Tags** and **Notes**. The status, the printer's messages and the supplies arrive
with a refresh, and so does the chance to copy the brand, model or serial number the printer
reports into your list.

## Opening a printer's web page

Almost every printer has a web page of its own for settings, counters and supplies.
**Open web page** opens it in your default browser, and so does a double-click on a printer or
pressing **Enter**. Right-click a printer and the same item is in bold, because it's what a
double-click does.

An address that starts with `https://` opens with https, exactly as you typed it, port and all, so
`https://prn-01.example.com:8443` reaches a printer whose web page is on another port. Anything
else opens with http. The **Address** field says so in its tooltip: "Start it with https:// if the
printer's web page needs it; otherwise it opens with http."

CapyPanel opens at most ten pages at once. Select more and the status bar says "Opened 10 web
pages. Only the first 10 open at once."

Only the address is handed to the browser. CapyPanel fetches nothing from the printer and signs in
to nothing.

## Finding a printer

The search box above the table covers every column on show, plus the notes, and its own text names
them, as in "Search name, address, brand, model, tags, notes". **Ctrl+F** jumps to it. Showing or
hiding a column changes what the search covers.

Tags narrow what the table shows, and you can pick several at once: the table then keeps only the
printers carrying all of them. A tinted strip above the table says which, as in "Only printers with
all of: floor-2, colour · 4 of 37 shown", with a **Clear** button; the **Tags** heading shows how
many are picked and offers a **×** to clear them. Picked tags stay as you move between groups and
while you search. When nothing matches, the table says "No printers in this group have all the
picked tags." and offers **Clear tags**.

A tag narrows the group you have picked. To see a tag across the whole list, pick **All printers**
first.

## Report

**Report** writes the printers you pick, with the columns you pick, to a CSV file. It works exactly
as it does for hosts, so [Importing and exporting hosts](../hosts/importing.md#exporting-hosts)
describes the window in full.

What differs is what goes in it. The columns are grouped as **Printer** (name, address, group,
brand, model), **Details** (serial number, asset tag, page counters, tags, notes) and **Last
check** (status, toner, as text). The built-in preset is **All details**.

Ticking Status or Toner lets the window refresh those printers itself, and it says how many of
them have never been checked. With neither ticked the button explains itself: "Tick Status or
Toner to read them".

The printers to export are the same kinds of choice as in Hosts: the search results or the picked
tags while either is on, the selected printers when you have more than one, every printer, those in
no group, each group with its subgroups, and each tag, every one of them counted.
