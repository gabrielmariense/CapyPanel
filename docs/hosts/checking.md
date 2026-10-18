# Checking hosts

CapyPanel can check whether hosts are on and who is logged on to them. The results show in the
host table's **Status** and **User** columns and in the **Details** panel. They're kept in
memory only: never in the list file, and gone when CapyPanel closes. Editing a host's address
clears its results. To keep them, **Report** on the toolbar writes the last check into a CSV, and
offers to check the hosts first (see [Importing and exporting hosts](importing.md)).

## Refresh

**Refresh**, on the toolbar, checks every host the table shows: the group picked in the Groups
panel with its subgroups, a tag, All hosts, No group, or the results of a search. Nothing needs to
be selected.

- Click it and choose **Status** or **Logged-on users**.
- Right-click it for the **Refresh every host shown** panel: tick both and click **Run**.
  CapyPanel remembers the ticks, and its tooltip says what they are.
- **F5** does the same as that **Run**, on the hosts shown, without opening the panel. It's
  ignored while a check is already running.

To check only some hosts, select them and right-click > **Refresh status** or **Refresh logged-on
users**. A group's right-click menu has the same two items, for its hosts and those in the groups
inside it.

CapyPanel checks 8 hosts at a time; the status bar shows the progress and a **Stop** button.
Checking who is logged on to more than 50 hosts asks first. A host without an address, whose name
isn't a computer name, is skipped with a note in the status bar.

## Status

| Status | Meaning |
|---|---|
| **Online** | A ping, or one of the ports CapyPanel connects to, answered |
| **Offline** | Nothing answered within 2 seconds |
| **Host not found** | The name or address doesn't exist |

The ports are 445 (Windows file sharing), 22 (SSH) and each tool's own port, such as 5900 for VNC
and 3389 for Remote Desktop. A refused connection counts as an answer. Every address the name has
is tried, cable and Wi-Fi alike. Hover over a status to see when it was checked and which address
answered: a PC that answers only on its Wi-Fi address may have its cable out. The Details panel
says it under the host's name, as "Online · checked 10:41", or "Not checked: use Refresh".

Status uses no account and needs no administrator rights.

### Automatic status

**Settings > Hosts > General > Refresh > Refresh status by itself** can check the status of the
hosts shown every few minutes: **Every minute**, **Every 5 minutes**, **Every 15 minutes**, **Every
30 minutes**, or **Custom…** for anything from 1 to 120. It's **Off** to begin with — nothing is
checked by itself unless you turn it on — and turning it off again keeps your interval for next
time.

As the setting says: "Only ping and ports, never logged-on users, so no account is needed. Refresh
in the toolbar always works."

## Logged-on users

The **User** column shows who is logged on, as `DOMAIN\user`, with "(disconnected)" for a
disconnected session, or **No one**.

The Details panel lists each session under **Logged on**, with the time of the check, as in
"Logged on (3) · 10:40". Every row names the user, a badge saying **Active** or **Disconnected**,
and under it whether they're at the computer (**Console**) or on **Remote Desktop**, which PC they
came from, and since when. Active sessions come first. Before any check the section says
**Not checked**; with nobody logged on, **No one logged on**; and when a check failed, the reason
below, with the full explanation in its tooltip.

**View > Show users' domain** is on and remembered. Turn it off to see just `user` in the
column, the Details panel and searches; what you hover over still shows the whole
`DOMAIN\user`, so a local "admin" can't pass for the domain's.

CapyPanel reads this through Windows' own remote session service: nothing is installed on the
hosts, and it works whatever their language. It needs an administrator account on each host.

| Shown | Meaning |
|---|---|
| **Unreachable** | Port 445 (Windows file sharing) didn't answer: the PC is off, off the network, blocks file sharing, or isn't Windows |
| **No admin rights** | The account isn't an administrator on that host |
| **Account rejected** | The host refused the account |
| **Couldn't read** | The host answered, but the sessions couldn't be read |

After someone logs off, they may show as disconnected for a while or disappear, the same as in
Task Manager's Users tab. That's how Windows reports it.

### Which account is used

By default, your own Windows account. If hosts answer **No admin rights** or **Account
rejected**, CapyPanel asks for another account (`DOMAIN\user` and password) and retries only those
hosts. That account:

- stays in memory until CapyPanel closes, is never saved, and is used only to read who is logged
  on;
- is tried on one host at a time: if a host rejects it, CapyPanel stops and asks again instead of
  trying it on the others, so the account isn't locked out;
- is forgotten, like passwords, with **Connect > Forget typed passwords**.

On PCs that aren't in a domain, the built-in Administrator is the only local account Windows
accepts remotely.
